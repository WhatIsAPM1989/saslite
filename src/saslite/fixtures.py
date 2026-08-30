"""Dummy fixture CSV support for metadata-backed project datasets."""

from __future__ import annotations

import csv
from pathlib import Path
import re

import pandas as pd

from saslite.runtime.dataset import Dataset
from saslite.runtime.metadata import DatasetMetadata


_SAS_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,31}$")


def fixture_path(
    root: str | Path,
    libref: str,
    member: str,
    *,
    existing_only: bool = False,
) -> Path | None:
    """Return the case-insensitive path for ``fixtures/LIBREF/MEMBER.csv``."""
    fixtures_root = Path(root)
    library = _sas_name(libref, "library")
    dataset = _sas_name(member, "dataset")

    library_dir = _case_insensitive_child(
        fixtures_root,
        library,
        directories=True,
    )
    if library_dir is None:
        if existing_only:
            return None
        library_dir = fixtures_root / library

    csv_path = _case_insensitive_child(
        library_dir,
        f"{dataset}.csv",
        directories=False,
    )
    if csv_path is not None:
        return csv_path
    if existing_only:
        return None
    return library_dir / f"{dataset}.csv"


def load_fixture(
    path: str | Path,
    *,
    schema: DatasetMetadata,
    libref: str,
    member: str,
) -> Dataset:
    """Read a semicolon fixture and validate it against manifest metadata."""
    fixture = Path(path)
    try:
        with fixture.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=";", quotechar='"')
            header = next(reader, None)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Fixture must be UTF-8 encoded: {fixture}") from exc

    if not header or not any(str(name).strip() for name in header):
        raise ValueError(f"Fixture has no header: {fixture}")
    names = [str(name).strip() for name in header]
    if any(not name for name in names):
        raise ValueError(f"Fixture contains an empty column name: {fixture}")
    logical_names = [name.upper() for name in names]
    duplicates = sorted({name for name in logical_names if logical_names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"Fixture contains duplicate column(s) {', '.join(duplicates)}: {fixture}"
        )

    unknown = [name for name in logical_names if schema.get_variable(name) is None]
    if unknown:
        raise ValueError(
            f"Fixture column(s) not present in strict metadata for "
            f"{libref.upper()}.{member.upper()}: {', '.join(unknown)} ({fixture})"
        )

    try:
        frame = pd.read_csv(
            fixture,
            sep=";",
            quotechar='"',
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            encoding="utf-8-sig",
        )
    except pd.errors.ParserError as exc:
        raise ValueError(f"Invalid fixture CSV {fixture}: {exc}") from exc
    frame.columns = logical_names

    converted: dict[str, pd.Series] = {}
    for logical_name in logical_names:
        variable = schema.get_variable(logical_name)
        assert variable is not None
        values = frame[logical_name]
        if variable.dtype == "character":
            too_long = values.map(
                lambda value: len(str(value).encode("utf-8")) > (variable.length or 0)
            )
            if variable.length is not None and bool(too_long.any()):
                row = int(too_long[too_long].index[0]) + 2
                raise ValueError(
                    f"Fixture value for {logical_name} on row {row} exceeds "
                    f"metadata length {variable.length}: {fixture}"
                )
            converted[logical_name] = values.astype(object)
            continue

        missing = values.str.strip().isin({"", "."})
        numeric = pd.to_numeric(values.where(~missing), errors="coerce")
        invalid = ~missing & numeric.isna()
        if bool(invalid.any()):
            index = invalid[invalid].index[0]
            row = int(index) + 2
            value = values.loc[index]
            raise ValueError(
                f"Fixture value {value!r} for numeric variable {logical_name} "
                f"on row {row} is invalid: {fixture}"
            )
        converted[logical_name] = numeric

    physical = Dataset.from_dataframe(
        pd.DataFrame(converted),
        name=member.upper(),
        libref=libref.upper(),
    )
    physical.weak_schema_sources = (f"{libref.upper()}.{member.upper()}",)
    return physical


def create_fixture(
    root: str | Path,
    *,
    libref: str,
    member: str,
    schema: DatasetMetadata,
    force: bool = False,
) -> Path:
    """Create a header-only fixture CSV from one manifest descriptor."""
    target = fixture_path(root, libref, member)
    assert target is not None
    if target.exists() and not force:
        raise FileExistsError(
            f"Fixture already exists: {target}; pass --force to replace it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter=";",
                quotechar='"',
                lineterminator="\n",
            )
            writer.writerow(schema.variable_names())
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def parse_dataset_reference(value: str) -> tuple[str, str]:
    """Parse and validate a required ``LIBREF.DATASET`` reference."""
    parts = str(value).strip().split(".")
    if len(parts) != 2:
        raise ValueError(f"Expected LIBREF.DATASET, got {value!r}")
    return _sas_name(parts[0], "library"), _sas_name(parts[1], "dataset")


def _sas_name(value: str, kind: str) -> str:
    name = str(value).strip().upper()
    if not _SAS_NAME.fullmatch(name):
        raise ValueError(f"Invalid SAS {kind} name: {value!r}")
    return name


def _case_insensitive_child(
    parent: Path,
    name: str,
    *,
    directories: bool,
) -> Path | None:
    if not parent.is_dir():
        return None
    matches = [
        child
        for child in parent.iterdir()
        if child.name.upper() == name.upper()
        and (child.is_dir() if directories else child.is_file())
    ]
    if len(matches) > 1:
        kind = "directories" if directories else "files"
        raise ValueError(
            f"Ambiguous case-insensitive fixture {kind} in {parent}: "
            + ", ".join(str(path.name) for path in sorted(matches))
        )
    return matches[0] if matches else None
