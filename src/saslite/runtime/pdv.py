"""Program Data Vector (PDV) — the core of DATA step execution."""

from __future__ import annotations

import math
from typing import Any

from saslite.runtime.metadata import VariableMetadata
from saslite.runtime.types import MISSING_NUMERIC, is_missing


class LagState:
    """Centralized LAG/DIF state management."""

    def __init__(self) -> None:
        self._buffers: dict[tuple[str, int], list[Any]] = {}

    def lag(self, var_name: str, value: Any, n: int = 1) -> Any:
        """LAGn(var) — return value from n observations ago."""
        key = (var_name.upper(), n)
        buf = self._buffers.setdefault(key, [])
        if len(buf) >= n:
            result = buf.pop(0)
        else:
            result = None
        buf.append(value)
        return result


class ByState:
    """Centralized BY-group state management."""

    def __init__(self) -> None:
        self._by_vars: list[str] = []
        self._first_flags: dict[str, bool] = {}
        self._last_flags: dict[str, bool] = {}
        self._prev_by_values: dict[str, Any] = {}

    def set_by_vars(self, by_vars: list[str]) -> None:
        """Set BY variables for FIRST./LAST. tracking."""
        self._by_vars = [v.upper() for v in by_vars]
        self._first_flags = {v: False for v in self._by_vars}
        self._last_flags = {v: False for v in self._by_vars}
        self._prev_by_values = {v: None for v in self._by_vars}

    def update_flags(self, variables: dict[str, Any], next_row: dict[str, Any] | None) -> None:
        """Update FIRST./LAST. flags based on current and next row."""
        for bv in self._by_vars:
            cur_val = variables.get(bv)
            prev_val = self._prev_by_values.get(bv)
            self._first_flags[bv] = (prev_val is None) or (prev_val != cur_val)

            if next_row is not None:
                next_val = None
                for k, v in next_row.items():
                    if k.upper() == bv:
                        next_val = v
                        break
                self._last_flags[bv] = (next_val is None) or (next_val != cur_val)
            else:
                self._last_flags[bv] = True

            self._prev_by_values[bv] = cur_val

    def get_first(self, var: str) -> bool:
        return self._first_flags.get(var.upper(), False)

    def get_last(self, var: str) -> bool:
        return self._last_flags.get(var.upper(), False)


class PDVVariable:
    """A variable slot in the PDV."""

    __slots__ = ("name", "value", "metadata", "retained", "initialized")

    def __init__(self, name: str, metadata: VariableMetadata) -> None:
        self.name = name
        self.metadata = metadata
        self.retained = metadata.retained
        self.initialized = False
        # Initialize based on type
        if metadata.dtype == "character":
            self.value: Any = ""
        else:
            self.value: Any = MISSING_NUMERIC


class PDV:
    """Program Data Vector — holds current observation state."""

    def __init__(self, character_encoding: str = "utf-8") -> None:
        self.variables: dict[str, PDVVariable] = {}
        self._n: int = 0
        self._error: int = 0
        self.output_flag: bool = False
        self.delete_flag: bool = False
        self.stop_flag: bool = False
        # Centralized state management
        self._retain_state: dict[str, Any] = {}
        self._lag_state: LagState = LagState()
        self._by_state: ByState = ByState()
        self._character_encoding = character_encoding
        self._character_overflows: dict[str, dict[str, Any]] = {}
        self._runtime_diagnostics: dict[str, dict[str, Any]] = {}
        # Names that the DATA-step compiler knows can receive a value from an
        # input data set or an executable statement.  SAS's "uninitialized"
        # note is about variables with no such source at all; it is not a
        # path-sensitive warning every time a condition leaves a value missing.
        self._produced_variables: set[str] = set()
        self._input_sources: list[str] = []

    def set_input_sources(self, names: list[str]) -> None:
        """Describe input data sets for actionable missing-schema warnings."""
        self._input_sources = list(dict.fromkeys(name.upper() for name in names))

    def has_compile_time_source(self, name: str) -> bool:
        """Whether an input or executable statement can initialize a name."""
        return name.upper() in self._produced_variables

    def add_variable(self, name: str, metadata: VariableMetadata) -> PDVVariable:
        """Add a variable to the PDV."""
        var = PDVVariable(name, metadata)
        self.variables[name.upper()] = var
        return var

    def ensure_variable(self, name: str, dtype: str = "numeric") -> PDVVariable:
        """Ensure a variable exists, creating it if needed."""
        key = name.upper()
        if key not in self.variables:
            meta = VariableMetadata(
                name=name,
                logical_name=key,
                dtype=dtype,  # type: ignore[arg-type]
            )
            self.add_variable(key, meta)
        return self.variables[key]

    def mark_produced(self, name: str) -> None:
        """Mark a variable as having a compile-time source of values."""
        self._produced_variables.add(name.upper())

    def set_by_vars(self, by_vars: list[str]) -> None:
        """Set BY variables for FIRST./LAST. tracking."""
        self._by_state.set_by_vars(by_vars)

    def update_by_flags(self, next_row: dict[str, Any] | None = None) -> None:
        """Update FIRST./LAST. flags based on current and next row."""
        current_values = {k: v.value for k, v in self.variables.items()}
        self._by_state.update_flags(current_values, next_row)

    def get(self, name: str) -> Any:
        """Get variable value."""
        key = name.upper()
        # Automatic variables
        if key == "_N_":
            return self._n
        if key == "_ERROR_":
            return self._error
        if key == "_NULL_":
            return None

        # FIRST./LAST. auto-variables
        if key.startswith("FIRST."):
            bv = key[6:]
            return self._by_state.get_first(bv)
        if key.startswith("LAST."):
            bv = key[5:]
            return self._by_state.get_last(bv)

        var = self.variables.get(key)
        if var is None:
            if key in self._produced_variables:
                return MISSING_NUMERIC
            source_text = self._input_source_text()
            self.record_runtime_diagnostic(
                f"uninitialized:{key}",
                f"Variable {name} is uninitialized{source_text}. SASLite used "
                "a numeric missing value; check the local fixture schema or "
                "initialize the variable before reading it.",
            )
            return MISSING_NUMERIC
        if key not in self._produced_variables:
            source_text = self._input_source_text()
            self.record_runtime_diagnostic(
                f"uninitialized:{key}",
                f"Variable {var.metadata.name} is uninitialized{source_text}. "
                "SASLite used its missing value; check the local fixture schema "
                "or initialize the variable before reading it.",
            )
        return var.value

    def _input_source_text(self) -> str:
        if not self._input_sources:
            return ""
        return " and is absent from input dataset(s) " + ", ".join(self._input_sources)

    def set(self, name: str, value: Any) -> None:
        """Set variable value."""
        key = name.upper()
        if key in ("_N_", "_ERROR_", "_NULL_"):
            return  # Cannot set automatic variables

        var = self.variables.get(key)
        if var is None:
            # Auto-create variable — infer type from value
            if isinstance(value, str):
                dtype = "character"
            else:
                dtype = "numeric"
            var = self.ensure_variable(name, dtype)
        self._assign_value(var, value)

    def reset_for_iteration(self) -> None:
        """Reset PDV for a new iteration (non-retained variables)."""
        self.output_flag = False
        self.delete_flag = False
        self.stop_flag = False
        self._error = 0

        for var in self.variables.values():
            if not var.retained:
                if var.metadata.dtype == "character":
                    var.value = ""
                else:
                    var.value = MISSING_NUMERIC
                var.initialized = False

    def increment_n(self) -> None:
        self._n += 1

    def snapshot_output_row(self) -> dict[str, Any]:
        """Capture current PDV state as an output row."""
        row: dict[str, Any] = {}
        for name, var in self.variables.items():
            row[var.metadata.name] = var.value
        return row

    def load_row(self, row: dict[str, Any]) -> None:
        """Load a row into the PDV."""
        for col_name, value in row.items():
            key = col_name.upper()
            if key in self.variables:
                self._assign_value(self.variables[key], value)

    def character_length_warnings(self) -> list[str]:
        """Summarize values SAS would truncate at their declared byte length."""
        warnings: list[str] = []
        for event in self._character_overflows.values():
            count = event["count"]
            value_word = "value" if count == 1 else "values"
            location = (
                f"_N_={event['first_n']}"
                if event["first_n"] > 0
                else "initialization"
            )
            warnings.append(
                f"Character truncation risk for variable {event['name']}: "
                f"{count} {value_word} exceeded the declared LENGTH "
                f"{event['limit']} bytes (maximum {event['maximum']} bytes; "
                f"first at {location}: {event['preview']}; encoding "
                f"{self._character_encoding}). SAS would truncate the value; "
                "SASLite preserved it for validation. Increase LENGTH or "
                "shorten the assigned value."
            )
        return warnings

    def runtime_warnings(self) -> list[str]:
        """Return aggregated DATA-step diagnostics in first-occurrence order."""
        warnings: list[str] = []
        for event in self._runtime_diagnostics.values():
            location = (
                f"_N_={event['first_n']}"
                if event["first_n"] > 0
                else "initialization"
            )
            repeated = (
                f" The condition occurred {event['count']} times."
                if event["count"] > 1
                else ""
            )
            warnings.append(
                f"{event['message']} First occurrence at {location}.{repeated}"
            )
        return warnings

    def has_runtime_diagnostic(self, key: str) -> bool:
        """Whether a diagnostic key was observed during iteration."""
        return key in self._runtime_diagnostics

    def record_runtime_diagnostic(self, key: str, message: str) -> None:
        """Aggregate a warning-worthy SAS DATA-step log condition."""
        event = self._runtime_diagnostics.get(key)
        if event is None:
            self._runtime_diagnostics[key] = {
                "message": message,
                "first_n": self._n,
                "count": 1,
            }
        else:
            event["count"] += 1

    def _assign_value(self, variable: PDVVariable, value: Any) -> None:
        self._record_character_overflow(variable, value)
        self._record_assignment_conversion(variable, value)
        variable.value = value
        variable.initialized = True

    def _record_assignment_conversion(
        self,
        variable: PDVVariable,
        value: Any,
    ) -> None:
        if is_missing(value):
            return
        name = variable.metadata.name
        dtype = variable.metadata.dtype
        if dtype == "numeric" and isinstance(value, str):
            self.record_runtime_diagnostic(
                f"conversion:char-to-num:{variable.metadata.logical_name}",
                "Automatic character-to-numeric conversion risk for variable "
                f"{name}: assigned {self._preview(value)} to a numeric variable. "
                "SAS would convert it; SASLite preserved the original value for "
                "validation. Use INPUT() explicitly.",
            )
        elif dtype == "character" and isinstance(value, (int, float)):
            self.record_runtime_diagnostic(
                f"conversion:num-to-char:{variable.metadata.logical_name}",
                "Automatic numeric-to-character conversion risk for variable "
                f"{name}: assigned {self._preview(value)} to a character variable. "
                "SAS would convert it; SASLite preserved the original value for "
                "validation. Use PUT() explicitly.",
            )

    @staticmethod
    def _preview(value: Any) -> str:
        preview = repr(value)
        return preview if len(preview) <= 82 else preview[:79] + "..."

    def _record_character_overflow(
        self,
        variable: PDVVariable,
        value: Any,
    ) -> None:
        limit = variable.metadata.length
        if (
            variable.metadata.dtype != "character"
            or limit is None
            or not isinstance(value, str)
        ):
            return
        try:
            actual = len(value.encode(self._character_encoding))
        except (LookupError, UnicodeEncodeError):
            # Without a valid byte representation the truncation boundary is
            # not knowable, so do not emit a potentially false diagnostic.
            return
        if actual <= limit:
            return

        key = variable.metadata.logical_name
        event = self._character_overflows.get(key)
        if event is None:
            preview = self._preview(value)
            self._character_overflows[key] = {
                "name": variable.metadata.name,
                "limit": limit,
                "maximum": actual,
                "count": 1,
                "first_n": self._n,
                "preview": preview,
            }
            return
        event["count"] += 1
        event["maximum"] = max(event["maximum"], actual)
