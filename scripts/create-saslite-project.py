#!/usr/bin/env python3
"""Create the conventional local SASLite structure in a project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


DEFAULT_INPUT_LIBRARIES = {
    "ADAM": "adam",
    "ADAMP": "adam",
    "RAW": "raw",
    "SDTM": "sdtm",
}
DEFAULT_OUTPUT_LIBRARIES = {
    "QCOSI": "qcosi",
    "OSIP": "osip",
}
_SAS_LIBREF = re.compile(r"^[A-Z_][A-Z0-9_]{0,7}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create SASLite config, localsetup, and local directories",
    )
    parser.add_argument("project", help="New or existing project root")
    parser.add_argument(
        "--input-lib",
        action="append",
        metavar="LIBREF=FOLDER",
        help="Input library mapping; repeat to replace example defaults",
    )
    parser.add_argument(
        "--output-lib",
        action="append",
        metavar="LIBREF=FOLDER",
        help="Output library mapping; repeat to replace example defaults",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite generated config and localsetup files",
    )
    args = parser.parse_args(argv)

    try:
        input_libraries = _parse_mappings(
            args.input_lib,
            DEFAULT_INPUT_LIBRARIES,
            option="--input-lib",
        )
        output_libraries = _parse_mappings(
            args.output_lib,
            DEFAULT_OUTPUT_LIBRARIES,
            option="--output-lib",
        )
        create_project(
            Path(args.project),
            input_libraries=input_libraries,
            output_libraries=output_libraries,
            force=args.force,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def create_project(
    project_root: Path,
    *,
    input_libraries: dict[str, str],
    output_libraries: dict[str, str],
    force: bool = False,
) -> None:
    root = project_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    local_root = root / "_local"
    metadata_dir = local_root / "config" / "metadata"
    data_root = local_root / "data"
    output_root = local_root / "output"
    work_root = local_root / "work"
    fixtures_root = root / "fixtures"

    directories = {metadata_dir, work_root}
    directories.update(data_root / folder for folder in input_libraries.values())
    directories.update(output_root / folder for folder in output_libraries.values())
    directories.update(fixtures_root / libref for libref in input_libraries)
    for directory in sorted(directories):
        directory.mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "default_schema": "weak",
        "metadata_dir": "_local/config/metadata",
        "fixtures_dir": "fixtures",
    }
    _write_generated(
        root / "saslite-project.json",
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        force=force,
    )
    _write_generated(
        local_root / "config" / "localsetup.sas",
        _localsetup_text(root, input_libraries, output_libraries),
        force=force,
    )
    _write_generated(
        metadata_dir / "README.txt",
        (
            "Copy one SASLite metadata export per library into this directory.\n"
            "Use <libref>.csv names, for example sdtm.csv or adam.csv.\n"
            "Run: python3 clean-sas-log-metadata.py\n"
            "The cleaner removes SAS log page breaks and keeps .bak backups.\n"
            "Every valid CSV found here makes that library strict automatically.\n"
        ),
        force=force,
    )
    _write_generated(
        metadata_dir / "clean-sas-log-metadata.py",
        _metadata_cleaner_text(),
        force=force,
    )
    _ensure_gitignore(root / ".gitignore")

    print(f"SASLite project structure is ready: {root}")
    print(f"Project config: {root / 'saslite-project.json'}")
    print(f"Local setup: {local_root / 'config' / 'localsetup.sas'}")
    print(f"Metadata directory: {metadata_dir}")
    print(f"Fixture directory: {fixtures_root}")


def _parse_mappings(
    values: list[str] | None,
    defaults: dict[str, str],
    *,
    option: str,
) -> dict[str, str]:
    if values is None:
        return dict(defaults)
    mappings: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} expects LIBREF=FOLDER, got {value!r}")
        raw_libref, raw_folder = value.split("=", 1)
        libref = raw_libref.strip().upper()
        folder = raw_folder.strip().strip("/")
        if not _SAS_LIBREF.fullmatch(libref):
            raise ValueError(f"Invalid SAS libref for {option}: {raw_libref!r}")
        if not folder or Path(folder).is_absolute() or ".." in Path(folder).parts:
            raise ValueError(f"Invalid relative folder for {option}: {raw_folder!r}")
        mappings[libref] = folder
    return mappings


def _localsetup_text(
    project_root: Path,
    input_libraries: dict[str, str],
    output_libraries: dict[str, str],
) -> str:
    project_text = project_root.as_posix()
    if '"' in project_text:
        raise ValueError("Project path must not contain a double quote")
    lines = [
        "/* Local-only setup generated by SASLite. */",
        "%macro localsetup;",
        "  %let execution_areax=DEV;",
        f"  %let saslite_data_root={project_text}/_local/data;",
        f"  %let saslite_output_root={project_text}/_local/output;",
        "",
        "  libname work memory;",
    ]
    for libref, folder in input_libraries.items():
        lines.append(
            f'  libname {libref.lower()} "&saslite_data_root./{folder}";'
        )
    lines.append("")
    for libref, folder in output_libraries.items():
        lines.append(
            f'  libname {libref.lower()} "&saslite_output_root./{folder}";'
        )
    lines.extend(["%mend localsetup;", ""])
    return "\n".join(lines)


def _metadata_cleaner_text() -> str:
    return '''#!/usr/bin/env python3
"""Remove SAS log pagination from SASLite metadata CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import sys


_PAGE_HEADER = re.compile(
    r"^\\s*(?:\\d+\\s+)?The SAS System(?:\\s+.*)?$",
    re.IGNORECASE,
)
_BEGIN = "----- BEGIN SASLITE METADATA:"
_END = "----- END SASLITE METADATA:"
_CSV_HEADER = (
    '"DATASET";"NAME";"TYPE";"LENGTH";"POSITION";'
    '"FORMAT";"INFORMAT";"LABEL"'
)


def clean_metadata(text: str, source: Path) -> str:
    lines = text.replace("\\f", "").splitlines()
    lines = [line for line in lines if not _PAGE_HEADER.fullmatch(line)]

    begin_indexes = [
        index for index, line in enumerate(lines)
        if line.strip().startswith(_BEGIN)
    ]
    if begin_indexes:
        start = begin_indexes[0]
        end = next(
            (
                index for index in range(start + 1, len(lines))
                if lines[index].strip().startswith(_END)
            ),
            None,
        )
        if end is None:
            raise ValueError(f"BEGIN marker has no matching END marker in {source}")
        lines = lines[start:end + 1]

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    stripped = {line.strip() for line in lines}
    if not any(line.startswith("#SASLITE_METADATA;") for line in stripped):
        raise ValueError(f"SASLite metadata marker not found in {source}")
    if _CSV_HEADER not in stripped:
        raise ValueError(f"SASLite CSV header not found in {source}")
    return "\\n".join(lines) + "\\n"


def clean_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8-sig")
    cleaned = clean_metadata(original, path)
    if cleaned == original:
        print(f"Unchanged: {path}")
        return False

    backup = path.with_name(path.name + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(cleaned, encoding="utf-8")
    temporary.replace(path)
    print(f"Cleaned: {path} (backup: {backup.name})")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove SAS log page headers from SASLite metadata CSV files",
    )
    parser.add_argument("files", nargs="*", type=Path, help="CSV files to clean")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    paths = args.files or sorted(script_dir.glob("*.csv"))
    if not paths:
        print(f"No CSV files found in {script_dir}")
        return 0

    try:
        for path in paths:
            clean_file(path.expanduser().resolve())
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _write_generated(path: Path, content: str, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        print(f"Keeping existing file: {path}")
        return
    path.write_text(content, encoding="utf-8")


def _ensure_gitignore(path: Path) -> None:
    marker = "# SASLite local runtime"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = f"{prefix}\n{marker}\n_local/\n"
    path.write_text(existing + block, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
