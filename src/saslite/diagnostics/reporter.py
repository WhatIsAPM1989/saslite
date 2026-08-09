"""Diagnostic reporter for SAS-style logging."""

from __future__ import annotations

import os
import sys
from typing import TextIO


class Reporter:
    """SAS-style diagnostic reporter (NOTE/WARNING/ERROR)."""

    _RESET = "\033[0m"
    _WARNING = "\033[1;33m"
    _ERROR = "\033[1;31m"

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
            return f"{self._ERROR}{line}{self._RESET}"
        if marker.startswith("WARNING:"):
            return f"{self._WARNING}{line}{self._RESET}"
        return line

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
