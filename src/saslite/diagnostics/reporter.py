"""Diagnostic reporter for SAS-style logging."""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO


class Reporter:
    """SAS-style diagnostic reporter (NOTE/WARNING/ERROR/SUCCESS)."""

    _RESET = "\033[0m"
    _SUCCESS = "\033[1;32m"
    _WARNING = "\033[1;33m"
    _ERROR = "\033[1;31m"
    _VARIABLE = "\033[1;36m"
    _VARIABLE_NAMES_AFTER_LABEL = re.compile(
        r"(?P<label>\bvariable(?:\(s\)|s)?\s+)"
        r"(?P<names>[A-Za-z_][A-Za-z0-9_.]*"
        r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_.]*)*)"
        r"(?=\s+(?:absent|appears|because|by|cannot|does|found|has|is|must|"
        r"not|referenced|was|were)\b|:)",
        re.IGNORECASE,
    )
    _VARIABLE_LIST = re.compile(
        r"(?P<label>\b(?:BY\s+)?(?:variables|variable\(s\)|columns|column\(s\))"
        r"[^:\n]{0,80}:\s*)"
        r"(?P<names>[A-Za-z_][A-Za-z0-9_.]*"
        r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_.]*)*)",
        re.IGNORECASE,
    )
    _VARIABLE_PREFIX = re.compile(
        r"(?P<label>\bvariables?\s+match(?:es)?\s+prefix\s+)"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        color: bool | None = None,
        quiet: bool = False,
        stop_on_error: bool = False,
        stop_on_warning: bool = False,
    ) -> None:
        self._stream = stream or sys.stderr
        if color is None:
            is_tty = getattr(self._stream, "isatty", lambda: False)()
            color = bool(is_tty and "NO_COLOR" not in os.environ)
        self._color = color
        self.quiet = quiet
        self.stop_on_error = stop_on_error
        self.stop_on_warning = stop_on_warning
        self._notes: list[str] = []
        self._warnings: list[str] = []
        self._errors: list[str] = []

    def configure(
        self,
        *,
        color: bool | None = None,
        quiet: bool | None = None,
        stop_on_error: bool | None = None,
        stop_on_warning: bool | None = None,
    ) -> None:
        """Update CLI-oriented presentation and execution policies."""
        if color is not None:
            self._color = color
        if quiet is not None:
            self.quiet = quiet
        if stop_on_error is not None:
            self.stop_on_error = stop_on_error
        if stop_on_warning is not None:
            self.stop_on_warning = stop_on_warning

    def _format_line(self, line: str) -> str:
        if not self._color:
            return line
        marker = line.lstrip().upper()
        if marker.startswith("ERROR:"):
            prefix_at = line.upper().find("ERROR:")
            prefix_end = prefix_at + len("ERROR:")
            formatted = (
                f"{line[:prefix_at]}{self._ERROR}{line[prefix_at:prefix_end]}"
                f"{self._RESET}{line[prefix_end:]}"
            )
            return self._highlight_variable_names(formatted)
        if marker.startswith("WARNING:"):
            prefix_at = line.upper().find("WARNING:")
            prefix_end = prefix_at + len("WARNING:")
            formatted = (
                f"{line[:prefix_at]}{self._WARNING}{line[prefix_at:prefix_end]}"
                f"{self._RESET}{line[prefix_end:]}"
            )
            return self._highlight_variable_names(formatted)
        if marker.startswith("SUCCESS:"):
            prefix_at = line.upper().find("SUCCESS:")
            prefix_end = prefix_at + len("SUCCESS:")
            return (
                f"{line[:prefix_at]}{self._SUCCESS}{line[prefix_at:prefix_end]}"
                f"{self._RESET}{line[prefix_end:]}"
            )
        return line

    def _highlight_variable_names(self, line: str) -> str:
        """Highlight variable names recognized in SAS diagnostic wording."""
        def highlight_name(match: re.Match[str]) -> str:
            name = match.group("name")
            return (
                f"{match.group('label')}{self._VARIABLE}{name}{self._RESET}"
            )

        def highlight_list(match: re.Match[str]) -> str:
            names = match.group("names")

            def wrap(token: re.Match[str]) -> str:
                name = token.group(0)
                return f"{self._VARIABLE}{name}{self._RESET}"

            return match.group("label") + re.sub(
                r"[A-Za-z_][A-Za-z0-9_.]*",
                wrap,
                names,
            )

        line = self._VARIABLE_LIST.sub(highlight_list, line)
        line = self._VARIABLE_PREFIX.sub(highlight_name, line)
        return self._VARIABLE_NAMES_AFTER_LABEL.sub(highlight_list, line)

    def _print_line(self, line: str) -> None:
        print(self._format_line(line), file=self._stream)

    def note(self, message: str) -> None:
        line = f"NOTE: {message}"
        self._notes.append(line)
        if not self.quiet:
            self._print_line(line)

    def warning(self, message: str) -> None:
        line = f"WARNING: {message}"
        self._warnings.append(line)
        self._print_line(line)

    def error(self, message: str) -> None:
        line = f"ERROR: {message}"
        self._errors.append(line)
        self._print_line(line)

    def success(self, message: str) -> None:
        """Print an explicit successful-run marker, including in quiet mode."""
        self._print_line(f"SUCCESS: {message}")

    def log(self, message: str) -> None:
        lines = message.splitlines()
        if self.quiet:
            lines = [
                line for line in lines
                if line.lstrip().upper().startswith(("WARNING:", "ERROR:"))
            ]
        for line in lines:
            self._print_line(line)

    @property
    def has_errors(self) -> bool:
        return len(self._errors) > 0

    @property
    def error_count(self) -> int:
        return len(self._errors)

    @property
    def warning_count(self) -> int:
        return len(self._warnings)

    def summary(self) -> str:
        parts = []
        if self._errors:
            parts.append(f"{len(self._errors)} error(s)")
        if self._warnings:
            parts.append(f"{len(self._warnings)} warning(s)")
        if not parts:
            return "No errors or warnings."
        return ", ".join(parts)
