"""Corporate SAS library metadata manifests."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re

from saslite.runtime.metadata import DatasetMetadata, VariableMetadata


_SAS_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,31}$")
_REQUIRED_COLUMNS = (
    "DATASET", "NAME", "TYPE", "LENGTH", "POSITION",
    "FORMAT", "INFORMAT", "LABEL",
)


@dataclass(frozen=True, slots=True)
class LibrarySchema:
    """Strict descriptor for every exported dataset in one SAS library."""

    libref: str
    path: Path
    datasets: dict[str, DatasetMetadata]


def load_metadata_directory(path: str | Path) -> dict[str, LibrarySchema]:
    """Load every library metadata CSV in a directory."""
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Metadata directory not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Metadata path must be a directory: {root}")

    libraries: dict[str, LibrarySchema] = {}
    for manifest_path in sorted(root.glob("*.csv")):
        schema = load_library_metadata(manifest_path)
        if schema.libref in libraries:
            previous = libraries[schema.libref].path
            raise ValueError(
                f"Duplicate metadata for library {schema.libref}: "
                f"{previous} and {manifest_path}"
            )
        libraries[schema.libref] = schema
    return libraries


def load_library_metadata(path: str | Path) -> LibrarySchema:
    """Parse one semicolon-separated SASLite metadata export."""
    manifest_path = Path(path).expanduser().resolve()
    fallback_libref = manifest_path.stem.upper()
    _validate_sas_name(fallback_libref, "library", manifest_path)

    marker_libref: str | None = None
    csv_lines: list[str] = []
    for raw_line in manifest_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("----- BEGIN ") or line.startswith("----- END "):
            continue
        if line.startswith("#SASLITE_METADATA;"):
            marker = next(csv.reader([line], delimiter=";"))
            if len(marker) < 3 or marker[1] != "1":
                raise ValueError(
                    f"Unsupported SASLite metadata marker in {manifest_path}: {line}"
                )
            marker_libref = marker[2].strip().upper()
            _validate_sas_name(marker_libref, "library marker", manifest_path)
            continue
        csv_lines.append(raw_line)

    libref = marker_libref or fallback_libref
    if marker_libref is not None and marker_libref != fallback_libref:
        raise ValueError(
            f"Metadata filename {manifest_path.name} implies library "
            f"{fallback_libref}, but its marker declares {marker_libref}"
        )
    if not csv_lines:
        raise ValueError(f"Metadata file has no CSV table: {manifest_path}")

    reader = csv.DictReader(csv_lines, delimiter=";", quotechar='"')
    headers = tuple(str(name).strip().upper() for name in (reader.fieldnames or []))
    if headers != _REQUIRED_COLUMNS:
        raise ValueError(
            f"Invalid metadata header in {manifest_path}; expected "
            + ";".join(_REQUIRED_COLUMNS)
        )

    rows_by_dataset: dict[str, list[tuple[int, VariableMetadata]]] = {}
    seen_variables: set[tuple[str, str]] = set()
    for row_number, raw_row in enumerate(reader, start=2):
        row = {
            str(key).strip().upper(): "" if value is None else str(value).strip()
            for key, value in raw_row.items()
        }
        dataset = row["DATASET"].upper()
        name = row["NAME"]
        logical_name = name.upper()
        _validate_sas_name(dataset, f"dataset on row {row_number}", manifest_path)
        _validate_sas_name(logical_name, f"variable on row {row_number}", manifest_path)

        key = (dataset, logical_name)
        if key in seen_variables:
            raise ValueError(
                f"Duplicate variable {dataset}.{logical_name} in {manifest_path}"
            )
        seen_variables.add(key)

        dtype_text = row["TYPE"].lower()
        if dtype_text in {"char", "character"}:
            dtype = "character"
        elif dtype_text in {"num", "numeric"}:
            dtype = "numeric"
        else:
            raise ValueError(
                f"Invalid TYPE {row['TYPE']!r} on row {row_number} of {manifest_path}"
            )
        try:
            length = int(row["LENGTH"])
            position = int(row["POSITION"])
        except ValueError as exc:
            raise ValueError(
                f"LENGTH and POSITION must be integers on row {row_number} "
                f"of {manifest_path}"
            ) from exc
        if length <= 0 or position <= 0:
            raise ValueError(
                f"LENGTH and POSITION must be positive on row {row_number} "
                f"of {manifest_path}"
            )

        variable = VariableMetadata(
            name=name,
            logical_name=logical_name,
            dtype=dtype,
            length=length,
            format=row["FORMAT"] or None,
            informat=row["INFORMAT"] or None,
            label=row["LABEL"] or None,
        )
        rows_by_dataset.setdefault(dataset, []).append((position, variable))

    if not rows_by_dataset:
        raise ValueError(f"Metadata file contains no variables: {manifest_path}")

    datasets: dict[str, DatasetMetadata] = {}
    for dataset, positioned_variables in rows_by_dataset.items():
        positions = [position for position, _variable in positioned_variables]
        if len(positions) != len(set(positions)):
            raise ValueError(
                f"Duplicate POSITION in dataset {libref}.{dataset} of {manifest_path}"
            )
        variables = {
            variable.logical_name: variable
            for _position, variable in sorted(positioned_variables)
        }
        datasets[dataset] = DatasetMetadata(
            libref=libref,
            member_name=dataset,
            variables=variables,
        )

    return LibrarySchema(libref=libref, path=manifest_path, datasets=datasets)


def _validate_sas_name(value: str, kind: str, path: Path) -> None:
    if not _SAS_NAME.fullmatch(value):
        raise ValueError(f"Invalid SAS {kind} name {value!r} in {path}")
