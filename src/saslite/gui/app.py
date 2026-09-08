"""SASLite Web GUI — Flask backend."""

from __future__ import annotations

import hashlib
import io
import math
import re
import secrets
import sys
import threading
import traceback
import tokenize
import webbrowser
from argparse import ArgumentParser
from datetime import date, datetime
from html import escape
from pathlib import Path

import pandas as pd
from flask import Flask, Response, jsonify, request

from saslite import SasInterpreter
from saslite.gui.project_profiles import expected_profile

app = Flask(__name__, static_folder="static")
app.config.setdefault("SAS_FACTORY", SasInterpreter)
app.config["SAS_SESSION"] = app.config["SAS_FACTORY"]()
app.config.setdefault("SAS_LOCK", threading.RLock())
app.config.setdefault("SAS_API_TOKEN", secrets.token_urlsafe(32))
app.config.setdefault("MAX_CONTENT_LENGTH", 100 * 1024 * 1024)

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DATASET_NAME_RE = re.compile(r"[^A-Z0-9_]+")


def get_sas() -> SasInterpreter:
    """Return the persistent interpreter for the current GUI app instance."""
    sas = app.config.get("SAS_SESSION")
    if sas is None:
        sas = app.config["SAS_FACTORY"]()
        app.config["SAS_SESSION"] = sas
    return sas


def reset_sas() -> SasInterpreter:
    """Reset the GUI interpreter; useful for tests and explicit state isolation."""
    sas = app.config["SAS_FACTORY"]()
    app.config["SAS_SESSION"] = sas
    return sas


def configure_session(settings: dict[str, object]) -> dict[str, object]:
    """Build a replacement before touching the active session."""
    options = {}
    for key in ("profile", "profile_file", "profile_root", "project_file", "work_dir"):
        value = settings.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = value.strip() if value else None
        if value and key != "profile":
            value = str(Path(value).expanduser().resolve())
        options[key] = value
    root = options["profile_root"]
    if root and not Path(root).is_dir():
        raise ValueError(f"Project root does not exist: {root}")
    sas = app.config["SAS_FACTORY"](**options)
    sas.reporter.configure(color=False)
    state = {**options, "name": getattr(sas._profile, "name", None)}
    app.config["SAS_SESSION"] = sas
    app.config["SAS_PROFILE_STATE"] = state
    return state


@app.route("/api/profile", methods=["GET", "POST"])
def api_profile():
    with _sas_lock():
        if request.method == "GET":
            return jsonify(app.config.get("SAS_PROFILE_STATE", {"name": None}))
        body = _json_body()
        if body is None:
            return jsonify(success=False, error="Invalid JSON body"), 400
        try:
            state = configure_session(body)
        except Exception as exc:
            return jsonify(success=False, error=str(exc)), 400
        return jsonify(success=True, profile=state)


@app.route("/api/profile/source", methods=["GET", "POST"])
def api_profile_source():
    with _sas_lock():
        state = app.config.get("SAS_PROFILE_STATE", {})
        filename = state.get("profile_file")
        editable = bool(filename)
        if not filename and state.get("profile") == "example":
            filename = str(Path(__file__).resolve().parents[1] / "profiles" / "example.py")
        if not filename:
            return jsonify(success=False, error="Connect a profile to view its code"), 400
        try:
            path = Path(filename)
            original = path.read_bytes()
            encoding, _ = tokenize.detect_encoding(io.BytesIO(original).readline)
            revision = hashlib.sha256(original).hexdigest()
            if request.method == "POST":
                body = _json_body()
                if not editable:
                    return jsonify(success=False, error="Built-in profiles are read-only; connect a local Python file to edit"), 400
                if body is None or not isinstance(body.get("content"), str):
                    return jsonify(success=False, error="Profile content must be a string"), 400
                if body.get("path") != str(path) or body.get("revision") != revision:
                    return jsonify(success=False, error="Profile changed outside this editor. Reload its code before saving."), 409
                content = body["content"]
                if b"\r\n" in original:
                    content = content.replace("\r\n", "\n").replace("\n", "\r\n")
                updated = content.encode(encoding)
                compile(updated, str(path), "exec")
                path.write_bytes(updated)
                revision = hashlib.sha256(updated).hexdigest()
                original = updated
            return jsonify(success=True, path=str(path), content=original.decode(encoding),
                           revision=revision, editable=editable)
        except Exception as exc:
            return jsonify(success=False, error=str(exc)), 400


def _request_host_name() -> str:
    host = request.host.lower()
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    return host.rsplit(":", 1)[0]


def _authorized_api_request() -> bool:
    expected = app.config["SAS_API_TOKEN"]
    provided = request.headers.get("X-SASLite-Token", "")
    return secrets.compare_digest(provided, expected)


@app.before_request
def _protect_local_api():
    """Reject rebinding hosts and require a token for state-changing API calls."""
    if _request_host_name() not in _ALLOWED_HOSTS:
        return jsonify({"success": False, "error": "Forbidden host"}), 403

    if (
        request.path.startswith("/api/")
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and not _authorized_api_request()
    ):
        return jsonify({"success": False, "error": "Unauthorized"}), 403


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


def _json_body() -> dict[str, object] | None:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _sas_lock():
    return app.config["SAS_LOCK"]


def _safe_dataset_name(filename: str) -> str:
    name = Path(filename).stem.upper()
    name = _DATASET_NAME_RE.sub("_", name).strip("_")
    if not name:
        name = "DATA"
    if not (name[0].isalpha() or name[0] == "_"):
        name = f"_{name}"
    return name[:32]


def _dataset_summary(libref: str, backend: object, name: str) -> dict[str, object] | None:
    try:
        ds = backend.read(name)
    except Exception:
        return None
    if not ds:
        return None
    return {
        "libref": libref,
        "name": name,
        "full_name": f"{libref}.{name}",
        "rows": ds.nrow,
        "columns": ds.ncol,
        "col_names": list(ds.data.columns),
    }


def _json_safe_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _json_safe_rows(df: pd.DataFrame) -> list[dict[str, object]]:
    rows = df.to_dict(orient="records")
    return [
        {key: _json_safe_value(value) for key, value in row.items()}
        for row in rows
    ]


@app.route("/")
def index():
    html_path = Path(app.static_folder or "static") / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("__SASLITE_API_TOKEN__", escape(app.config["SAS_API_TOKEN"], quote=True))
    return Response(html, mimetype="text/html")


@app.route("/api/execute", methods=["POST"])
def api_execute():
    """Execute SAS code."""
    body = _json_body()
    if body is None:
        return jsonify({"success": False, "error": "Invalid JSON body"}), 400
    code = body.get("code", "")

    if not code.strip():
        return jsonify({"success": False, "error": "Empty code"})

    with _sas_lock():
        sas = get_sas()
        captured = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_reporter_stream = sas.reporter._stream

        try:
            sys.stdout = captured
            sys.stderr = captured
            sas.reporter._stream = captured
            sas.reporter.configure(color=False)

            result = sas.execute(code, source_name=body.get("source_path") or "<input>")
            output_text = captured.getvalue()

            steps = []
            for step in result.steps:
                steps.append({
                    "success": step.success,
                    "error": step.error,
                    "notes": step.notes,
                    "warnings": step.warnings,
                    "artifacts": [
                        {
                            "kind": artifact.kind,
                            "mime_type": artifact.mime_type,
                            "data": artifact.data,
                            "title": artifact.title,
                            "width": artifact.width,
                            "height": artifact.height,
                        }
                        for artifact in step.artifacts
                    ],
                })

            return jsonify({
                "success": result.success,
                "error": result.error,
                "output": output_text,
                "steps": steps,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({
                "success": False,
                "error": str(e),
            })
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sas.reporter._stream = old_reporter_stream


@app.route("/api/datasets", methods=["GET"])
def api_datasets():
    """List all datasets."""
    with _sas_lock():
        sas = get_sas()
        datasets = []
        for libref, backend in sas.session.storage._backends.items():
            for name in backend.list_datasets():
                summary = _dataset_summary(libref, backend, name)
                if summary:
                    datasets.append(summary)
    return jsonify({"datasets": datasets})


@app.route("/api/libraries", methods=["GET"])
def api_libraries():
    """List all libraries with their datasets grouped by library."""
    with _sas_lock():
        sas = get_sas()
        libraries = []
        for libref, backend in sas.session.storage._backends.items():
            ds_list = []
            for name in backend.list_datasets():
                summary = _dataset_summary(libref, backend, name)
                if summary:
                    ds_list.append({
                        "name": summary["name"],
                        "rows": summary["rows"],
                        "columns": summary["columns"],
                        "col_names": summary["col_names"],
                    })

            # Determine library description
            engine = getattr(backend, "engine", "MEMORY")
            path = str(getattr(backend, "path", "") or "")
            if libref == "WORK":
                desc = "Work Library"
                icon = "work"
            elif path:
                desc = path
                icon = "disk"
            else:
                desc = "Memory Library"
                icon = "memory"

            libraries.append({
                "libref": libref,
                "description": desc,
                "engine": engine,
                "path": path,
                "icon": icon,
                "schema_policy": sas.session.schema_policy_for(libref),
                "datasets": sorted(ds_list, key=lambda d: d["name"]),
                "count": len(ds_list),
            })

    # WORK first, then alphabetical
    libraries.sort(key=lambda lib: (0 if lib["libref"] == "WORK" else 1, lib["libref"]))
    return jsonify({"libraries": libraries})


@app.route("/api/datasets/<libref>/<name>", methods=["GET"])
def api_get_dataset(libref: str, name: str):
    """Get dataset content as JSON."""
    with _sas_lock():
        sas = get_sas()
        try:
            ds = sas.session.get_dataset(libref.upper(), name.upper())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except KeyError:
            return jsonify({"error": f"Dataset {libref}.{name} not found"}), 404

        df = ds.data.copy()

    columns = []
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        if "int" in dtype_str:
            col_type = "int"
        elif "float" in dtype_str:
            col_type = "float"
        elif "datetime" in dtype_str:
            col_type = "datetime"
        elif "bool" in dtype_str:
            col_type = "bool"
        else:
            col_type = "str"
        columns.append({"name": col, "type": col_type})

    return jsonify({
        "libref": libref.upper(),
        "name": name.upper(),
        "columns": columns,
        "rows": _json_safe_rows(df),
        "total_rows": len(df),
    })


@app.route("/api/datasets/<libref>/<name>", methods=["DELETE"])
def api_delete_dataset(libref: str, name: str):
    """Delete a dataset."""
    try:
        with _sas_lock():
            sas = get_sas()
            backend = sas.session.storage.get_backend(libref.upper())
            if backend and backend.exists(name.upper()):
                backend.delete(name.upper())
                return jsonify({"success": True})
        return jsonify({"error": "Dataset not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/open-file", methods=["POST"])
def api_open_file():
    """Open a .sas file and return its content."""
    body = _json_body()
    if body is None:
        return jsonify({"success": False, "error": "Invalid JSON body"}), 400
    filepath = body.get("path", "")
    if not filepath:
        return jsonify({"success": False, "error": "No file path provided"})
    try:
        p = Path(filepath).expanduser().resolve()
        if not p.exists():
            return jsonify({"success": False, "error": f"File not found: {filepath}"})
        if not p.suffix.lower() == ".sas":
            return jsonify({"success": False, "error": "Only .sas files are supported"})
        content = p.read_text(encoding="utf-8", errors="replace")
        with _sas_lock():
            recommendation = expected_profile(str(p), app.config.get("SAS_PROFILE_STATE", {}))
        return jsonify(success=True, content=content, filename=p.name, path=str(p),
                       recommendation=recommendation)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/save-file", methods=["POST"])
def api_save_file():
    """Save editor text to a local SAS program."""
    body = _json_body()
    if (body is None or not isinstance(body.get("path"), str)
            or not body["path"].strip() or not isinstance(body.get("content"), str)):
        return jsonify(success=False, error="A path and text content are required"), 400
    try:
        path = Path(body["path"]).expanduser().resolve()
        if path.suffix.lower() != ".sas":
            return jsonify(success=False, error="Only .sas files are supported"), 400
        with _sas_lock():
            if path.exists() and not body.get("overwrite"):
                return jsonify(success=False, error="File already exists", exists=True), 409
            # Write beside the destination so replacement is atomic.
            import os
            import tempfile
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                                 dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(body["content"])
                if path.exists():
                    temporary.chmod(path.stat().st_mode & 0o777)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return jsonify(success=True, path=str(path))
    except (OSError, ValueError) as exc:
        return jsonify(success=False, error=str(exc)), 400


@app.route("/api/program-profile", methods=["POST"])
def api_program_profile():
    body = _json_body()
    if body is None or not isinstance(body.get("path"), str):
        return jsonify(success=False, error="A program path is required"), 400
    try:
        with _sas_lock():
            recommendation = expected_profile(body["path"], app.config.get("SAS_PROFILE_STATE", {}))
            if body.get("create") is True:
                target = recommendation["settings"].get("profile_file")
                if recommendation["exists"] or not target:
                    return jsonify(success=False, error="Profile already exists; reload the recommendation"), 409
                if target != body.get("expected_profile_file"):
                    return jsonify(success=False, error="Expected profile changed; reload the recommendation"), 409
                destination = Path(target)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation: never overwrite an existing project profile.
                with destination.open("x", encoding="utf-8") as output:
                    output.write(recommendation["template"])
                recommendation = expected_profile(body["path"], app.config.get("SAS_PROFILE_STATE", {}))
            return jsonify(success=True, recommendation=recommendation)
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 400


@app.route("/api/program-files", methods=["POST"])
def api_program_files():
    """Local file chooser retains real paths, unlike a browser upload input."""
    body = _json_body()
    if body is None:
        return jsonify(success=False, error="Invalid JSON body"), 400
    try:
        folder = Path(body.get("directory") or Path.cwd()).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("Choose a directory")
        entries = [dict(name=p.name, path=str(p), directory=p.is_dir())
                   for p in folder.iterdir()
                   if not p.name.startswith('.') and (p.is_dir() or p.suffix.lower() == '.sas')]
        entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
        return jsonify(success=True, directory=str(folder), parent=str(folder.parent), entries=entries)
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 400


@app.route("/api/import-data", methods=["POST"])
def api_import_data():
    """Import a data file (sas7bdat, xpt, csv, excel) into WORK library."""
    body = _json_body()
    if body is None:
        return jsonify({"success": False, "error": "Invalid JSON body"}), 400
    filepath = body.get("path", "")
    if not filepath:
        return jsonify({"success": False, "error": "No file path provided"})
    try:
        p = Path(filepath)
        if not p.exists():
            return jsonify({"success": False, "error": f"File not found: {filepath}"})

        suffix = p.suffix.lower()
        dataset_name = _safe_dataset_name(p.name)

        if suffix == ".sas7bdat":
            from saslite.storage.sas_backend import _read_sas7bdat
            df = _read_sas7bdat(p)
        elif suffix == ".xpt":
            import pyreadstat
            df, _ = pyreadstat.read_xport(str(p))
        elif suffix == ".csv":
            df = pd.read_csv(p)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(p)
        else:
            return jsonify({"success": False, "error": f"Unsupported format: {suffix}"})

        from saslite.runtime.dataset import Dataset
        ds = Dataset.from_dataframe(df, name=dataset_name, libref="WORK")
        with _sas_lock():
            sas = get_sas()
            sas.session.put_dataset("WORK", dataset_name, ds)

        return jsonify({
            "success": True,
            "dataset": f"WORK.{dataset_name}",
            "rows": ds.nrow,
            "columns": ds.ncol,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/upload-data", methods=["POST"])
def api_upload_data():
    """Upload a data file via browser and import into WORK library."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"})
    f = request.files["file"]
    if not f.filename:
        return jsonify({"success": False, "error": "Empty filename"})

    import tempfile
    suffix = Path(f.filename).suffix.lower()
    dataset_name = _safe_dataset_name(f.filename)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        f.save(tmp)
        tmp_path = tmp.name

    try:
        if suffix == ".sas7bdat":
            from saslite.storage.sas_backend import _read_sas7bdat
            df = _read_sas7bdat(Path(tmp_path))
        elif suffix == ".xpt":
            import pyreadstat
            df, _ = pyreadstat.read_xport(tmp_path)
        elif suffix == ".csv":
            df = pd.read_csv(tmp_path)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(tmp_path)
        else:
            return jsonify({"success": False, "error": f"Unsupported format: {suffix}"})

        from saslite.runtime.dataset import Dataset
        ds = Dataset.from_dataframe(df, name=dataset_name, libref="WORK")
        with _sas_lock():
            sas = get_sas()
            sas.session.put_dataset("WORK", dataset_name, ds)

        return jsonify({
            "success": True,
            "dataset": f"WORK.{dataset_name}",
            "rows": ds.nrow,
            "columns": ds.ncol,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        tmp_file = Path(tmp_path)
        if tmp_file.exists():
            tmp_file.unlink()


@app.route("/api/file-dialog", methods=["POST"])
def api_file_dialog():
    """Use the desktop window or macOS system picker, preserving the real path."""
    body = _json_body()
    if body is None:
        return jsonify(success=False, error="Invalid JSON body"), 400
    mode = body.get("mode", "open")
    if mode not in ("open", "import"):
        return jsonify(success=False, error="Unknown file dialog mode"), 400
    try:
        webview = sys.modules.get("webview")
        window = webview.windows[0] if webview and webview.windows else None
        if window:
            types = ("SAS Files (*.sas)", "All Files (*.*)") if mode == "open" else (
                "Data Files (*.sas7bdat;*.xpt;*.csv;*.xlsx;*.xls)", "All Files (*.*)")
            result = window.create_file_dialog(
                webview.OPEN_DIALOG, directory="", allow_multiple=False, file_types=types,
            )
            if result:
                return jsonify(success=True, path=result[0])
            return jsonify(success=False, cancelled=True)
        if sys.platform == "darwin":
            from saslite.gui.file_dialog import choose_macos_file
            return jsonify(choose_macos_file(mode))
        return jsonify(success=False, error="Native file dialog unavailable")
    except Exception as exc:
        return jsonify(success=False, error=str(exc))


def main(argv: list[str] | None = None) -> int:
    """Launch the browser-based GUI."""
    parser = ArgumentParser(
        prog="saslite-gui",
        description="Start the SASLite browser GUI.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening a browser tab.",
    )
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--profile", choices=["example"])
    profiles.add_argument("--profile-file", help="Trusted local Python profile")
    parser.add_argument("--profile-root", help="Project root directory")
    parser.add_argument("--project-file", help="Project configuration JSON")
    parser.add_argument("--workdir", help="DISK library directory")
    args = parser.parse_args(argv)
    try:
        configure_session(dict(profile=args.profile, profile_file=args.profile_file,
                               profile_root=args.profile_root, project_file=args.project_file,
                               work_dir=args.workdir))
    except Exception as exc:
        parser.error(str(exc))

    if sys.platform == "darwin":
        from saslite.gui.file_dialog import warm_macos_picker
        threading.Thread(target=warm_macos_picker, daemon=True).start()

    url = f"http://{args.host}:{args.port}"
    print("SASLite Web GUI starting...")
    print(f"Open {url} in your browser")
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
