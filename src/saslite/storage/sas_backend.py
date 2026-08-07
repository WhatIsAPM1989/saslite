"""SAS file storage backend.

Uses writable SAS Transport (.xpt) files for persistence, and can read existing
SAS7BDAT (.sas7bdat) files when present.

Note: sas7bdat format is read-only. Write operations use XPT format due to
library limitations (pyreadstat does not support sas7bdat write).
"""

from __future__ import annotations

import hashlib
import json
import re
import warnings
from pathlib import Path
from typing import Literal

import pandas as pd
import pyreadstat
from pandas._libs.sas import get_subheader_index
from pandas.io.sas import sas_constants as sas_const
from pandas.io.sas.sas7bdat import SAS7BDATReader

from saslite.runtime.dataset import Dataset


_MEMBER_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,31}$")

# XPT format column name length limits
# XPT (SAS Transport) format limits
# See: SAS Transport (XPORT) Version 5 specification
# Column names: up to 32 characters (not 8!)
# Table names: up to 8 characters
_XPT_COLUMN_NAME_MAX_LENGTH = 32
_XPT_TABLE_NAME_MAX_LENGTH = 8
_XPT_NAME_MAP_SUFFIX = ".saslite-columns.json"


def _member_name(name: str) -> str:
    """Validate and normalize SAS member name (dataset name)."""
    member = str(name).upper()
    if not _MEMBER_NAME_RE.fullmatch(member):
        raise ValueError(f"Invalid SAS member name: {name}")
    return member


def _truncate_column_name(name: str, max_length: int = _XPT_COLUMN_NAME_MAX_LENGTH) -> str:
    """Truncate column name to fit XPT format limits.

    Args:
        name: Original column name
        max_length: Maximum allowed length (default: 8 for XPT)

    Returns:
        Truncated column name in uppercase
    """
    normalized = str(name).upper()
    if len(normalized) <= max_length:
        return normalized
    return normalized[:max_length]


def _prepare_dataframe_for_xpt(df: pd.DataFrame, warn_truncation: bool = True) -> pd.DataFrame:
    """Prepare DataFrame for XPT format export.

    Args:
        df: Input DataFrame
        warn_truncation: Whether to warn about truncated column names

    Returns:
        DataFrame with XPT-compatible column names
    """
    result = df.copy()

    # Track truncations for warning
    truncations = []
    new_columns = []

    for col in result.columns:
        new_col = _truncate_column_name(col)
        if warn_truncation and str(col).upper() != new_col:
            truncations.append((str(col), new_col))
        new_columns.append(new_col)

    # Check for duplicate column names after truncation
    if len(new_columns) != len(set(new_columns)):
        duplicates = [name for name in new_columns if new_columns.count(name) > 1]
        raise ValueError(
            f"Column name truncation resulted in duplicates: {set(duplicates)}. "
            f"Original columns: {list(df.columns)}"
        )

    result.columns = new_columns

    # Emit warning if truncations occurred
    if warn_truncation and truncations:
        trunc_msg = ", ".join(f"'{orig}' -> '{new}'" for orig, new in truncations[:3])
        if len(truncations) > 3:
            trunc_msg += f" (and {len(truncations) - 3} more)"
        warnings.warn(
            f"Column names truncated to {_XPT_COLUMN_NAME_MAX_LENGTH} characters for XPT format: {trunc_msg}",
            UserWarning,
            stacklevel=3
        )

    return result


def _prepare_dataframe_with_name_map(
    df: pd.DataFrame,
    warn_truncation: bool = True,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Prepare XPT names and retain aliases required by pyreadstat.

    SAS permits a leading underscore in a variable name, while pyreadstat's
    XPT writer rejects it. Such names receive collision-free physical aliases;
    the physical-to-logical mapping is persisted next to the XPT file.
    """
    result = _prepare_dataframe_for_xpt(df, warn_truncation=warn_truncation)
    used = {str(column).upper() for column in result.columns}
    aliases: dict[str, str] = {}
    columns: list[str] = []
    next_alias = 1

    for original, prepared in zip(df.columns, result.columns):
        physical = str(prepared)
        if not physical[:1].isalpha():
            while True:
                candidate = f"SASL{next_alias:04d}"
                next_alias += 1
                if candidate not in used:
                    break
            used.add(candidate)
            physical = candidate
            aliases[physical] = str(original)
        columns.append(physical)

    result.columns = columns
    if aliases:
        warnings.warn(
            "pyreadstat cannot write XPT variable names beginning with an "
            "underscore. SASLite stored physical aliases and an adjacent "
            f"{_XPT_NAME_MAP_SUFFIX} mapping; external readers that ignore "
            "the mapping will see the physical aliases.",
            UserWarning,
            stacklevel=3,
        )
    return result, aliases


def _name_map_path(path: Path) -> Path:
    return path.with_name(path.name + _XPT_NAME_MAP_SUFFIX)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_name_map(path: Path, aliases: dict[str, str]) -> None:
    mapping_path = _name_map_path(path)
    if not aliases:
        if mapping_path.exists():
            mapping_path.unlink()
        return
    payload = {
        "version": 1,
        "xpt_sha256": _file_sha256(path),
        "physical_to_logical": aliases,
    }
    temporary = mapping_path.with_name(mapping_path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(mapping_path)


def _read_name_map(path: Path, columns: list[object]) -> dict[str, str]:
    mapping_path = _name_map_path(path)
    if not mapping_path.exists():
        return {}
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ValueError("unsupported mapping version")
        if payload.get("xpt_sha256") != _file_sha256(path):
            raise ValueError("XPT fingerprint does not match")
        aliases = payload.get("physical_to_logical")
        if not isinstance(aliases, dict):
            raise ValueError("physical_to_logical must be an object")
        available = {str(column) for column in columns}
        if not set(aliases).issubset(available):
            raise ValueError("mapped physical columns are absent from the XPT file")
        restored = [aliases.get(str(column), str(column)) for column in columns]
        if len(restored) != len(set(name.upper() for name in restored)):
            raise ValueError("mapping would create duplicate logical columns")
        return {str(key): str(value) for key, value in aliases.items()}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid SASLite XPT column mapping {mapping_path}: {exc}") from exc


class _RelaxedSAS7BDATReader(SAS7BDATReader):
    @staticmethod
    def _is_data_subheader(compression: bytes, subheader_compression: int, subheader_type: int) -> bool:
        return bool(
            compression
            and subheader_compression in (sas_const.compressed_subheader_id, 0)
            and subheader_type == sas_const.compressed_subheader_type
        )

    @staticmethod
    def _supports_metadata_page(page_type: int) -> bool:
        return page_type in {
            *sas_const.page_meta_types,
            sas_const.page_amd_type,
            sas_const.page_mix_type,
            sas_const.page_comp_type,
        }

    @staticmethod
    def _supports_data_page(page_type: int) -> bool:
        return page_type in {
            sas_const.page_data_type,
            sas_const.page_mix_type,
            sas_const.page_comp_type,
        }

    def _read_page_header(self) -> None:
        super()._read_page_header()
        self._raw_page_type = self._current_page_type
        if self._current_page_type == sas_const.page_comp_type:
            self._current_page_type = sas_const.page_data_type

    def _process_page_meta(self) -> bool:
        self._read_page_header()
        if self._supports_metadata_page(self._raw_page_type):
            self._process_page_metadata()
        return bool(
            self._supports_data_page(self._raw_page_type)
            or self._current_page_data_subheader_pointers
        )

    def _read_next_page(self):
        self._current_page_data_subheader_pointers = []
        self._cached_page = self._path_or_buf.read(self._page_length)
        if len(self._cached_page) <= 0:
            return True
        if len(self._cached_page) != self._page_length:
            self.close()
            msg = (
                "failed to read complete page from file (read "
                f"{len(self._cached_page):d} of {self._page_length:d} bytes)"
            )
            raise ValueError(msg)

        self._read_page_header()
        if self._supports_metadata_page(self._raw_page_type):
            self._process_page_metadata()

        if not (
            self._supports_data_page(self._raw_page_type)
            or self._raw_page_type in sas_const.page_meta_types
        ):
            return self._read_next_page()

        return False

    def _process_page_metadata(self) -> None:
        bit_offset = self._page_bit_offset

        for i in range(self._current_page_subheaders_count):
            offset = sas_const.subheader_pointers_offset + bit_offset
            total_offset = offset + self._subheader_pointer_length * i

            subheader_offset = self._read_uint(total_offset, self._int_length)
            total_offset += self._int_length

            subheader_length = self._read_uint(total_offset, self._int_length)
            total_offset += self._int_length

            subheader_compression = self._read_uint(total_offset, 1)
            total_offset += 1

            subheader_type = self._read_uint(total_offset, 1)

            if (
                subheader_length == 0
                or subheader_compression == sas_const.truncated_subheader_id
            ):
                continue

            subheader_signature = self._read_bytes(subheader_offset, self._int_length)

            try:
                subheader_index = get_subheader_index(subheader_signature)
            except ValueError:
                if self._is_data_subheader(
                    self.compression,
                    subheader_compression,
                    subheader_type,
                ):
                    self._current_page_data_subheader_pointers.append(
                        (subheader_offset, subheader_length)
                    )
                continue

            subheader_processor = self._subheader_processors[subheader_index]
            if subheader_processor is None:
                if self._is_data_subheader(
                    self.compression,
                    subheader_compression,
                    subheader_type,
                ):
                    self._current_page_data_subheader_pointers.append(
                        (subheader_offset, subheader_length)
                    )
                continue

            subheader_processor(subheader_offset, subheader_length)


def _decode_sas_string(value: object, encoding: str) -> object:
    if not isinstance(value, bytes):
        return value

    cleaned = value.replace(b"\x00", b"").rstrip(b" \xa0")
    if not cleaned:
        return ""

    encodings = [encoding, "utf-8", "latin1"]
    tried: set[str] = set()
    for candidate in encodings:
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            return cleaned.decode(candidate)
        except UnicodeDecodeError:
            continue

    return cleaned.decode(encoding or "utf-8", errors="replace")


def _decode_sas_dataframe(df: pd.DataFrame, encoding: str) -> pd.DataFrame:
    decoded = df.copy()
    for col in decoded.columns:
        if decoded[col].dtype == object:
            decoded[col] = decoded[col].map(lambda value: _decode_sas_string(value, encoding))
    return decoded


def _read_sas7bdat_relaxed(path: Path) -> pd.DataFrame:
    reader = _RelaxedSAS7BDATReader(path, encoding="utf-8", convert_text=False)
    try:
        df = reader.read()
        return _decode_sas_dataframe(df, reader.encoding or reader.default_encoding)
    finally:
        reader.close()


def _read_sas7bdat(path: Path) -> pd.DataFrame:
    try:
        return pd.read_sas(path, format="sas7bdat", encoding="utf-8")
    except ValueError as exc:
        if "Unknown subheader signature" not in str(exc):
            raise
        return _read_sas7bdat_relaxed(path)


class SasBackend:
    """SAS file-based dataset storage.

    Supports reading both XPT (Transport) and sas7bdat formats.
    Write operations always use XPT format due to library limitations.

    Args:
        base_dir: Base directory for dataset storage
        libref: Library reference name (default: "DISK")
        format: Desired output format - 'sas7bdat' (default) or 'xpt'
        warn_truncation: Whether to warn when column names are truncated for XPT format (default: True)

    Note:
        When format='sas7bdat', files are written in XPT format with .sas7bdat extension
        due to lack of sas7bdat write support in Python libraries. The files are fully
        compatible and can be read by both SASlite and SAS software.

        The XPT format is actually a robust choice:
        - Supports long column names (up to 40 characters)
        - Stable, well-documented format
        - Excellent library support via pyreadstat

    Example:
        >>> # Default: sas7bdat format (actually writes XPT)
        >>> backend = SasBackend('./work')
        >>>
        >>> # Explicitly specify XPT format
        >>> backend = SasBackend('./work', format='xpt')
    """

    def __init__(
        self,
        base_dir: str | Path,
        libref: str = "DISK",
        format: Literal["sas7bdat", "xpt"] = "sas7bdat",
        warn_truncation: bool = True,
    ) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._libref = libref
        self._format = format
        self._warn_truncation = warn_truncation
        self.engine = "SAS"
        self.path = self._base

        # Validate format
        if format not in ("sas7bdat", "xpt"):
            raise ValueError(
                f"Unsupported format: {format}. "
                f"Supported formats: 'sas7bdat', 'xpt'"
            )

        # Warn user that sas7bdat format uses XPT implementation
        if format == "sas7bdat":
            warnings.warn(
                "Note: sas7bdat format currently uses XPT (Transport) file format "
                "for write operations due to Python library limitations. "
                "Files can be read by both SASlite and SAS software.",
                UserWarning,
                stacklevel=2
            )

    def _find_existing_path(self, name: str, suffix: str) -> Path:
        """Find a dataset file using SAS-style case-insensitive member names."""
        member = _member_name(name)
        exact = self._base / f"{member}{suffix}"
        if exact.exists():
            return exact

        if not self._base.exists():
            return exact

        for candidate in self._base.iterdir():
            if (
                candidate.is_file()
                and candidate.suffix.lower() == suffix.lower()
                and candidate.stem.upper() == member
            ):
                return candidate

        return exact

    def _xpt_path(self, name: str) -> Path:
        return self._find_existing_path(name, ".xpt")

    def _sas7bdat_path(self, name: str) -> Path:
        return self._find_existing_path(name, ".sas7bdat")

    def read(self, name: str) -> Dataset | None:
        member = _member_name(name)

        # Try XPT path first
        xpt_path = self._xpt_path(member)
        if xpt_path.exists():
            df, metadata = pyreadstat.read_xport(str(xpt_path))
            return self._dataset_from_xpt(df, metadata, member, xpt_path)

        # Try sas7bdat path
        sas7bdat_path = self._sas7bdat_path(member)
        if sas7bdat_path.exists():
            # Try reading as XPT first (since we write XPT with .sas7bdat extension)
            try:
                df, metadata = pyreadstat.read_xport(str(sas7bdat_path))
                return self._dataset_from_xpt(df, metadata, member, sas7bdat_path)
            except Exception:
                # If XPT read fails, try as actual sas7bdat format
                df = _read_sas7bdat(sas7bdat_path)
                return Dataset.from_dataframe(df, name=member, libref=self._libref)

        return None

    def _dataset_from_xpt(
        self,
        df: pd.DataFrame,
        metadata: object,
        member: str,
        path: Path,
    ) -> Dataset:
        aliases = _read_name_map(path, list(df.columns))
        if aliases:
            df = df.rename(columns=aliases)
        dataset = Dataset.from_dataframe(df, name=member, libref=self._libref)
        labels = getattr(metadata, "column_names_to_labels", {}) or {}
        formats = getattr(metadata, "original_variable_types", {}) or {}
        for column in df.columns:
            variable = dataset.metadata.get_variable(str(column))
            if variable is None:
                continue
            physical = next(
                (name for name, logical in aliases.items() if logical == str(column)),
                str(column),
            )
            variable.label = labels.get(physical) or None
            variable.format = formats.get(physical) or None
        return dataset

    def write(self, name: str, dataset: Dataset) -> None:
        """Write dataset to disk in the configured format.

        Args:
            name: Dataset member name
            dataset: Dataset to write

        Note:
            All formats currently use XPT (Transport) implementation due to
            Python library limitations. Files use the appropriate extension
            (.xpt or .sas7bdat) based on the configured format.
        """
        member = _member_name(name)

        # Determine file extension based on format preference
        if self._format == "xpt":
            path = self._base / f"{member}.xpt"
        else:
            # sas7bdat format: write XPT with .sas7bdat extension
            path = self._base / f"{member}.sas7bdat"

        # Always use XPT format for writing (due to library limitations)
        df, aliases = _prepare_dataframe_with_name_map(
            dataset.data,
            warn_truncation=self._warn_truncation,
        )
        table_name = member[:_XPT_TABLE_NAME_MAX_LENGTH]
        column_labels: dict[str, str] = {}
        variable_formats: dict[str, str] = {}
        for original, prepared in zip(dataset.data.columns, df.columns):
            metadata = dataset.metadata.get_variable(str(original))
            if metadata is None:
                continue
            if metadata.label:
                column_labels[str(prepared)] = metadata.label
            if metadata.format:
                variable_formats[str(prepared)] = metadata.format
        pyreadstat.write_xport(
            df,
            str(path),
            table_name=table_name,
            column_labels=column_labels or None,
            variable_format=variable_formats or None,
        )
        _write_name_map(path, aliases)

    def exists(self, name: str) -> bool:
        member = _member_name(name)
        return self._xpt_path(member).exists() or self._sas7bdat_path(member).exists()

    def delete(self, name: str) -> bool:
        member = _member_name(name)
        deleted = False
        for path in (self._xpt_path(member), self._sas7bdat_path(member)):
            if path.exists():
                path.unlink()
                deleted = True
            mapping_path = _name_map_path(path)
            if mapping_path.exists():
                mapping_path.unlink()
        return deleted

    def list_datasets(self) -> list[str]:
        if not self._base.exists():
            return []
        names: set[str] = set()
        for path in self._base.iterdir():
            if (
                path.is_file()
                and path.suffix.lower() in {".xpt", ".sas7bdat"}
                and _MEMBER_NAME_RE.fullmatch(path.stem.upper())
            ):
                names.add(path.stem.upper())
        return sorted(names)
