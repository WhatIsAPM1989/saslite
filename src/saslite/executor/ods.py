"""Output Delivery System destinations used by presentation procedures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from saslite.ast.proc import ProcNode
from saslite.ast.data_step import DatasetRefNode
from saslite.diagnostics.reporter import Reporter
from saslite.runtime.dataset import Dataset
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session


def handle_ods(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """Track ODS OUTPUT tables and file-based RTF/LISTING destinations."""
    action = str(proc.options.get("ACTION", "")).upper()
    if not hasattr(session, "_ods_output_targets"):
        session._ods_output_targets = {}
    if not hasattr(session, "_ods_output_items"):
        session._ods_output_items = []

    if action == "OUTPUT":
        new_items = list(proc.options.get("TABLE_ITEMS", []))
        if not new_items:
            new_items = list(proc.options.get("TABLES", {}).items())
        replaced = {str(name).upper() for name, _target in new_items}
        session._ods_output_items = [
            item for item in session._ods_output_items
            if str(item[0]).upper() not in replaced
        ] + new_items
        session._ods_output_targets.update(proc.options.get("TABLES", {}))
        return StepResult(success=True)

    if action == "OUTPUT_CLOSE":
        session._ods_output_targets.clear()
        session._ods_output_items.clear()
        return StepResult(success=True)

    if action != "CONTROL":
        return StepResult(success=True)

    destination = str(proc.options.get("DESTINATION", "")).upper()
    if destination not in {"RTF", "LISTING"}:
        # SELECT, EXCLUDE, and GRAPHICS are accepted compatibility controls.
        return StepResult(success=True)

    destinations = _document_destinations(session)
    if proc.options.get("CLOSE"):
        closed = destinations.pop(destination, None)
        notes = []
        if closed is not None:
            notes.append(f"ODS {destination} closed {closed['path']}")
        return StepResult(success=True, notes=notes)

    raw_path = proc.options.get("FILE", proc.options.get("BODY", ""))
    if not raw_path:
        if destination == "LISTING":
            # ODS LISTING; restores the normal terminal listing.
            destinations.pop(destination, None)
            return StepResult(success=True)
        return StepResult(success=False, error="ODS RTF requires FILE=")

    path = _resolve_destination_path(str(raw_path), session)
    try:
        if destination == "RTF":
            _write_rtf_document(path, [])
        else:
            path.write_text("", encoding="utf-8")
    except OSError as exc:
        return StepResult(
            success=False,
            error=f"Unable to open ODS {destination} file {path}: {exc}",
        )

    destinations[destination] = {"path": path, "blocks": []}
    return StepResult(
        success=True,
        notes=[f"ODS {destination} opened {path}"],
    )


def write_report_destinations(
    session: Session,
    frame: pd.DataFrame,
    *,
    title: str,
    listing_text: str,
) -> list[str]:
    """Append a PROC REPORT result to every active document destination."""
    written: list[str] = []
    for destination, state in _document_destinations(session).items():
        path = state["path"]
        if destination == "RTF":
            state["blocks"].append(_render_rtf_table(frame, title))
            _write_rtf_document(path, state["blocks"])
        elif destination == "LISTING":
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(listing_text)
                if not listing_text.endswith("\n"):
                    stream.write("\n")
        written.append(f"ODS {destination} wrote {path}")
    return written


def output_items(session: Session, proc: ProcNode | None = None) -> list[tuple[Any, Any]]:
    """Return active ODS OUTPUT assignments, preserving duplicate table targets.

    SAS permits the same output object to be routed to more than one data set,
    commonly with different target data-set options.  The historical mapping
    on ``Session`` cannot represent duplicates, so consumers should use this
    ordered form.
    """
    items = list(getattr(session, "_ods_output_items", []))
    if not items:
        items = list(getattr(session, "_ods_output_targets", {}).items())
    if proc is not None:
        for statement in proc.statements:
            if not isinstance(statement, dict) or statement.get("action") != "ods":
                continue
            local_items = list(statement.get("table_items", []))
            items.extend(local_items or statement.get("tables", {}).items())
    return items


def write_output_tables(
    session: Session,
    tables: dict[str, pd.DataFrame],
    *,
    proc: ProcNode | None = None,
) -> list[str]:
    """Materialize requested ODS output objects as SASLite data sets."""
    normalized = {str(name).upper(): frame for name, frame in tables.items()}
    written: list[str] = []
    for table_name, target in output_items(session, proc):
        frame = normalized.get(str(table_name).upper())
        if frame is None or not isinstance(target, DatasetRefNode):
            continue
        dataset = Dataset.from_dataframe(
            frame.copy(),
            name=target.name,
            libref=target.libref,
        )
        # Import lazily: registry imports the ODS handler through the facade,
        # while several PROC modules also depend on this helper.
        from saslite.executor.proc.registry import _apply_export_dataset_options

        dataset = _apply_export_dataset_options(dataset, target.options, session)
        session.put_dataset(target.libref, target.name, dataset)
        written.append(f"{str(table_name)}={target.libref}.{target.name}")
    return written


def _document_destinations(session: Session) -> dict[str, dict[str, Any]]:
    if not hasattr(session, "_ods_document_destinations"):
        session._ods_document_destinations = {}
    return session._ods_document_destinations


def _resolve_destination_path(value: str, session: Session) -> Path:
    fileref = session.get_macro_var(f"_FILEREF_{value.upper()}")
    path = Path(fileref if fileref is not None else value).expanduser()
    return path.resolve()


def _write_rtf_document(path: Path, blocks: list[str]) -> None:
    document = (
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Courier New;}}"
        "\n"
        r"\viewkind4\uc1\fs20"
        "\n"
        + "\n".join(blocks)
        + "\n}"
    )
    path.write_text(document, encoding="ascii")


def _render_rtf_table(frame: pd.DataFrame, title: str) -> str:
    columns = [str(column) for column in frame.columns]
    count = max(1, len(columns))
    cell_width = max(1200, 9600 // count)
    boundaries = "".join(
        f"\\cellx{cell_width * (index + 1)}" for index in range(count)
    )

    lines = [f"\\pard\\b {_rtf_escape(title)}\\b0\\par"]
    if not columns:
        lines.append(r"\pard (no columns)\par")
        return "\n".join(lines)

    def row(values: list[Any], *, bold: bool = False) -> str:
        prefix = "\\b " if bold else ""
        suffix = "\\b0 " if bold else ""
        cells = "".join(
            f"\\intbl {prefix}{_rtf_escape(_display_value(value))}{suffix}\\cell"
            for value in values
        )
        return f"\\trowd\\trgaph108{boundaries}{cells}\\row"

    lines.append(row(columns, bold=True))
    for values in frame.itertuples(index=False, name=None):
        lines.append(row(list(values)))
    lines.append(r"\pard\par")
    return "\n".join(lines)


def _display_value(value: Any) -> str:
    try:
        if pd.isna(value):
            return "."
    except (TypeError, ValueError):
        pass
    return str(value)


def _rtf_escape(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character in "\\{}":
            escaped.append("\\" + character)
        elif character == "\n":
            escaped.append(r"\line ")
        elif 32 <= codepoint < 127:
            escaped.append(character)
        else:
            for offset in range(0, len(character.encode("utf-16-le")), 2):
                unit = int.from_bytes(
                    character.encode("utf-16-le")[offset:offset + 2],
                    "little",
                )
                signed = unit if unit < 32768 else unit - 65536
                escaped.append(f"\\u{signed}?")
    return "".join(escaped)
