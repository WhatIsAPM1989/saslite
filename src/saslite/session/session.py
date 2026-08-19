"""Session: the central runtime state object."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any

import pandas as pd

from saslite.runtime.dataset import Dataset
from saslite.project_config import ProjectConfig
from saslite.storage.path_resolver import StorageRouter
from saslite.storage.memory import MemoryBackend


@dataclass(frozen=True, slots=True)
class SchemaExpectation:
    """A source variable assumed to exist under the weak schema policy."""

    variable: str
    sources: tuple[str, ...]
    contexts: tuple[str, ...]


class MacroScope:
    """Scope for macro variables and macro definitions."""

    def __init__(self, name: str = "_GLOBAL_", parent: MacroScope | None = None) -> None:
        self.name = name
        self.parent = parent
        self.variables: dict[str, str] = {}
        self.macros: dict[str, Any] = {}

    def define_var(self, name: str, value: str) -> None:
        self.variables[name.upper()] = value

    def resolve_var(self, name: str) -> str | None:
        key = name.upper()
        if key in self.variables:
            return self.variables[key]
        if self.parent:
            return self.parent.resolve_var(key)
        return None

    def has_var(self, name: str) -> bool:
        return self.resolve_var(name) is not None


class Session:
    """Central session object holding all runtime state."""

    def __init__(self, storage: StorageRouter | None = None) -> None:
        self.storage = storage or StorageRouter()
        # Weak is the initial schema policy. Missing variables referenced from
        # existing input datasets use missing-value semantics and are reported
        # together after the run instead of mutating the source descriptor.
        self.schema_policy = "weak"
        self.library_metadata = {}
        self.metadata_dir: str | None = None
        self.project_config_path: str | None = None
        self._schema_expectations: dict[
            tuple[tuple[str, ...], str], set[str]
        ] = {}
        self._macro_stack: list[MacroScope] = [MacroScope("_GLOBAL_")]
        self._formats: dict[str, Any] = {}
        self._options: dict[str, Any] = {
            "LINESIZE": 80,
            "PAGESIZE": 60,
            "FIRSTOBS": 1,
            "OBS": None,
            "MISSING": ".",
            "NODATE": False,
            "NONUMBER": False,
            "MPRINT": False,
            "SYMBOLGEN": False,
            "MLOGIC": False,
            # SAS character lengths are byte lengths. DATA-step overflow
            # diagnostics use this codec and preserve the full Python value.
            "ENCODING": "utf-8",
        }
        self._debug_output: list[str] = []
        # Automatic macro variables
        global_scope = self._macro_stack[0]
        global_scope.define_var("SYSLAST", "")
        global_scope.define_var("SYSERR", "0")
        global_scope.define_var("SYSNOBS", "0")

    def clear_schema_expectations(self) -> None:
        """Start a fresh source-schema audit for one public execution."""
        self._schema_expectations.clear()

    def configure_project(self, config: ProjectConfig) -> None:
        """Apply project defaults and metadata-discovered strict libraries."""
        self.schema_policy = config.default_schema
        self.library_metadata = dict(config.library_metadata)
        self.metadata_dir = str(config.metadata_dir) if config.metadata_dir else None
        self.project_config_path = str(config.path) if config.path else None
        for libref in self.library_metadata:
            if self.storage.get_backend(libref) is None:
                self.storage.register(libref, MemoryBackend())

    def schema_policy_for(self, libref: str) -> str:
        """Return the effective schema policy for a library reference."""
        return (
            "strict"
            if str(libref).upper() in self.library_metadata
            else self.schema_policy
        )

    @property
    def has_strict_schema_policy(self) -> bool:
        """Whether the active project config contains any strict policy."""
        return (
            self.schema_policy == "strict"
            or bool(self.library_metadata)
        )

    def record_schema_expectation(
        self,
        variable: str,
        sources: list[str] | tuple[str, ...],
        context: str,
    ) -> None:
        """Record a weak-schema assumption without changing any dataset."""
        normalized_sources = tuple(dict.fromkeys(
            str(source).upper() for source in sources if str(source).strip()
        )) or ("<INPUT>",)
        logical_name = variable.upper()
        new_source_set = set(normalized_sources)
        merged_contexts = {context.upper()}

        # A variable can first be encountered after two source branches were
        # merged and later through a branch whose origin is known precisely.
        # Keep the narrowest supported attribution instead of printing both
        # ``ADAM.ADAE.X`` and ``X in one of ADAM.ADAE, ADAM.ADSL``.
        for existing_key in list(self._schema_expectations):
            existing_sources, existing_variable = existing_key
            if existing_variable != logical_name:
                continue
            existing_source_set = set(existing_sources)
            if existing_source_set.issubset(new_source_set):
                self._schema_expectations[existing_key].add(context.upper())
                return
            if new_source_set.issubset(existing_source_set):
                merged_contexts.update(self._schema_expectations.pop(existing_key))

        key = (normalized_sources, logical_name)
        self._schema_expectations.setdefault(key, set()).update(merged_contexts)

    @property
    def schema_expectations(self) -> list[SchemaExpectation]:
        """Return weak-schema assumptions in deterministic display order."""
        return [
            SchemaExpectation(
                variable=variable,
                sources=sources,
                contexts=tuple(sorted(contexts)),
            )
            for (sources, variable), contexts in sorted(
                self._schema_expectations.items(),
                key=lambda item: (item[0][0], item[0][1]),
            )
        ]

    @property
    def macro_scope(self) -> MacroScope:
        return self._macro_stack[-1]

    @property
    def global_scope(self) -> MacroScope:
        return self._macro_stack[0]

    def push_macro_scope(self, name: str) -> MacroScope:
        scope = MacroScope(name, parent=self.macro_scope)
        self._macro_stack.append(scope)
        return scope

    def pop_macro_scope(self) -> None:
        if len(self._macro_stack) > 1:
            self._macro_stack.pop()

    def set_macro_var(self, name: str, value: str) -> None:
        self.macro_scope.define_var(name, value)

    def get_macro_var(self, name: str) -> str | None:
        return self.macro_scope.resolve_var(name)

    def get_option(self, name: str, default: Any = None) -> Any:
        return self._options.get(name.upper(), default)

    def set_option(self, name: str, value: Any) -> None:
        self._options[name.upper()] = value

    def get_dataset(self, libref: str, name: str) -> Dataset:
        libref_upper = libref.upper()
        backend, ds_name = self.storage.resolve(libref_upper, name)
        library_schema = self.library_metadata.get(libref_upper)
        dataset_schema = (
            library_schema.datasets.get(ds_name.upper())
            if library_schema is not None
            else None
        )
        if library_schema is not None and dataset_schema is None:
            raise KeyError(
                f"Dataset {libref_upper}.{ds_name} does not exist in strict metadata"
            )
        ds = backend.read(ds_name)
        if dataset_schema is not None:
            ds = self._dataset_with_metadata_schema(
                libref_upper,
                ds_name,
                ds,
                dataset_schema,
            )
        elif ds is None:
            raise KeyError(f"Dataset {libref_upper}.{ds_name} does not exist")
        if ds.weak_schema_sources is None:
            # A dataset first encountered through a storage backend is an
            # input to the local run.  Keep this root name when the data later
            # flows through WORK datasets so expectations are never blamed on
            # an interpreter-created intermediate table.
            ds.weak_schema_sources = (f"{libref_upper}.{ds_name.upper()}",)
        return ds

    @staticmethod
    def _dataset_with_metadata_schema(
        libref: str,
        member: str,
        physical: Dataset | None,
        schema: Any,
    ) -> Dataset:
        """Build an in-memory view whose descriptor is the strict manifest."""
        row_count = physical.nrow if physical is not None else 0
        physical_columns = (
            {str(column).upper(): column for column in physical.data.columns}
            if physical is not None
            else {}
        )
        columns: dict[str, pd.Series] = {}
        for variable in schema.variables.values():
            source_column = physical_columns.get(variable.logical_name)
            if source_column is not None and physical is not None:
                columns[variable.name] = physical.data[source_column].reset_index(drop=True)
            else:
                missing = "" if variable.dtype == "character" else float("nan")
                columns[variable.name] = pd.Series([missing] * row_count)
        frame = pd.DataFrame(columns)
        metadata = deepcopy(schema)
        metadata.libref = libref
        metadata.member_name = member.upper()
        metadata.row_count = row_count
        return Dataset(
            name=member,
            data=frame,
            metadata=metadata,
            weak_schema_sources=(f"{libref}.{member.upper()}",),
        )

    def put_dataset(self, libref: str, name: str, dataset: Dataset) -> None:
        backend, ds_name = self.storage.resolve(libref, name)
        if dataset.weak_schema_sources is None:
            # Interpreter-created outputs are closed unless their executor
            # explicitly propagates open source-schema lineage.
            dataset.weak_schema_sources = ()
        backend.write(ds_name, dataset)
        self.global_scope.define_var("SYSLAST", f"{libref.upper()}.{ds_name}")

    def weak_schema_sources_for(
        self,
        dataset_names: list[str] | tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve intermediate dataset names back to open source schemas."""
        return tuple(
            source
            for source in self.schema_sources_for(dataset_names)
            if self.schema_policy_for(source.split(".", 1)[0]) == "weak"
        )

    def schema_sources_for(
        self,
        dataset_names: list[str] | tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve intermediate names to all original schema sources."""
        resolved: list[str] = []
        for dataset_name in dataset_names:
            text = str(dataset_name).strip().upper()
            if text.count(".") != 1 or text.startswith("DERIVED TABLE "):
                continue
            libref, member = text.split(".", 1)
            try:
                dataset = self.get_dataset(libref, member)
            except KeyError:
                continue
            for source in dataset.weak_schema_sources or ():
                if source not in resolved:
                    resolved.append(source)
        return tuple(resolved)

    def dataset_exists(self, libref: str, name: str) -> bool:
        backend, ds_name = self.storage.resolve(libref, name)
        library_schema = self.library_metadata.get(libref.upper())
        if library_schema is not None:
            return ds_name.upper() in library_schema.datasets
        return backend.exists(ds_name)

    def list_datasets(self, libref: str) -> list[str]:
        """List physical and metadata-only members without duplicates."""
        backend = self.storage.get_backend(libref)
        physical = backend.list_datasets() if backend is not None else []
        library_schema = self.library_metadata.get(libref.upper())
        metadata_members = list(library_schema.datasets) if library_schema else []
        return list(dict.fromkeys([
            *(str(name).upper() for name in physical),
            *(str(name).upper() for name in metadata_members),
        ]))

    def dictionary_columns(self) -> Dataset:
        """Build the read-only DICTIONARY.COLUMNS view for this session."""
        rows: list[dict[str, Any]] = []
        for libref in self.storage.list_libraries():
            backend = self.storage.get_backend(libref)
            if backend is None:
                continue
            for member_name in self.list_datasets(libref):
                try:
                    dataset = self.get_dataset(libref, member_name)
                except (KeyError, OSError, ValueError):
                    # One unreadable member must not hide metadata for every
                    # other registered library.
                    continue
                if dataset is None:
                    continue
                for varnum, column_name in enumerate(dataset.columns, start=1):
                    variable = dataset.metadata.get_variable(str(column_name))
                    dtype = variable.dtype if variable is not None else "character"
                    is_character = dtype == "character"
                    length = variable.length if variable is not None else None
                    if length is None:
                        if is_character:
                            series = dataset.data[column_name]
                            nonmissing = series.dropna().astype(str)
                            length = max((len(value) for value in nonmissing), default=1)
                        else:
                            length = 8
                    rows.append(
                        {
                            "LIBNAME": libref.upper(),
                            "MEMNAME": str(member_name).upper(),
                            "NAME": (
                                variable.name
                                if variable is not None
                                else str(column_name)
                            ),
                            "TYPE": "char" if is_character else "num",
                            "LENGTH": int(length),
                            "VARNUM": varnum,
                            "LABEL": (
                                variable.label or ""
                                if variable is not None
                                else ""
                            ),
                            "FORMAT": (
                                variable.format or ""
                                if variable is not None
                                else ""
                            ),
                        }
                    )

        columns = [
            "LIBNAME", "MEMNAME", "NAME", "TYPE",
            "LENGTH", "VARNUM", "LABEL", "FORMAT",
        ]
        frame = pd.DataFrame(rows, columns=columns)
        return Dataset.from_dataframe(
            frame,
            name="COLUMNS",
            libref="DICTIONARY",
        )

    def add_debug_output(self, message: str) -> None:
        """Add a debug message to the output log."""
        self._debug_output.append(message)

    def get_debug_output(self) -> list[str]:
        """Get all debug output messages."""
        return self._debug_output.copy()

    def clear_debug_output(self) -> None:
        """Clear debug output messages."""
        self._debug_output.clear()
