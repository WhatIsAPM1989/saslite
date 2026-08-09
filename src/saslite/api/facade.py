"""SasInterpreter — the main programming API for SASLite."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from saslite.macro.expander import MacroExpander
from saslite.parser.program_parser import ProgramParser
from saslite.session.session import Session
from saslite.storage.path_resolver import StorageRouter
from saslite.executor.dispatcher import Dispatcher
from saslite.executor.proc.registry import (
    handle_proc_print, handle_proc_sgrender, handle_proc_sort, handle_proc_contents,
    handle_proc_means, handle_proc_freq, handle_proc_import, handle_proc_export,
    handle_proc_append, handle_proc_datasets,
)
from saslite.executor.proc.extras import (
    handle_proc_transpose, handle_proc_univariate, handle_proc_compare,
    handle_proc_copy, handle_proc_format, handle_proc_tabulate,
    handle_proc_report,
)
from saslite.executor.proc.stats import handle_proc_reg, handle_proc_logistic, handle_proc_corr, handle_proc_ttest
from saslite.executor.proc.survival import (
    handle_ods,
    handle_proc_lifetest,
    handle_proc_phreg,
)
from saslite.executor.proc.generalized import handle_proc_genmod
from saslite.runtime.execution_result import RunSummary
from saslite.diagnostics.reporter import Reporter
from saslite.profiles import CompatibilityProfile, create_profile, load_profile_file


class SasInterpreter:
    """Main API for executing SAS code.

    Args:
        work_dir: Directory for persistent dataset storage (optional)
        sas_format: Storage format for datasets - 'sas7bdat' (default) or 'xpt'
        profile: Optional environment compatibility profile name or instance
        profile_file: Trusted external Python profile kept outside the package
        profile_root: Explicit project root for the selected profile

    Example:
        >>> # Use default sas7bdat format
        >>> sas = SasInterpreter()
        >>>
        >>> # Use legacy XPT format
        >>> sas = SasInterpreter(sas_format='xpt')
        >>>
        >>> # With persistent storage
        >>> sas = SasInterpreter(work_dir='./work', sas_format='sas7bdat')
    """

    def __init__(
        self,
        work_dir: str | None = None,
        sas_format: str = "sas7bdat",
        profile: str | CompatibilityProfile | None = None,
        profile_file: str | Path | None = None,
        profile_root: str | None = None,
    ) -> None:
        self._parser = ProgramParser()
        self._session = Session(StorageRouter(work_dir, sas_format=sas_format))
        # Macro functions such as OPEN/VARNUM inspect datasets in this same
        # session.  Keep one expander for the interpreter lifetime so dataset
        # handles remain valid across separately executed source chunks.
        self._macro = MacroExpander(self._session)
        self._reporter = Reporter()
        if profile is not None and profile_file is not None:
            raise ValueError("Pass either profile or profile_file, not both")
        if profile_file is not None:
            self._profile = load_profile_file(
                profile_file,
                project_root=profile_root,
            )
        elif isinstance(profile, str):
            self._profile = create_profile(profile, project_root=profile_root)
        else:
            self._profile = profile

    @property
    def session(self) -> Session:
        return self._session

    @property
    def reporter(self) -> Reporter:
        return self._reporter

    def execute(
        self,
        source: str,
        source_name: str = "<input>",
        *,
        include_encoding: str = "utf-8",
        include_errors: str = "strict",
    ) -> RunSummary:
        """Execute SAS source code."""
        try:
            if self._profile is not None:
                source = self._profile.prepare_source(
                    source,
                    source_name=source_name,
                )
            # Step 0: Expand %INCLUDE before DATALINES extraction so included
            # files can contain their own inline data blocks.
            source = self._expand_includes(
                source,
                source_name=source_name,
                encoding=include_encoding,
                errors=include_errors,
            )
        except Exception as e:
            summary = RunSummary(success=False, error=str(e))
            self._reporter.error(str(e))
            return summary

        # PROC SQL INTO creates macro variables while the program is running.
        # Expand later RUN/QUIT-delimited steps only after the producing SQL
        # step has executed, so consumers see the newly assigned values.
        if self._has_later_runtime_macro_reference(source):
            chunks = self._split_into_step_chunks(source)
            return self._execute_chunks(chunks)

        summary = self._execute_expanded(source)

        # Retry in chunked mode when a macro variable could not be resolved:
        # CALL SYMPUT / SELECT INTO create macro vars mid-run, so later steps
        # must be macro-expanded only after earlier steps executed.
        if (not summary.success and summary.error
                and "No terminal matches '&'" in str(summary.error)):
            chunks = self._split_into_step_chunks(source)
            if len(chunks) > 1:
                return self._execute_chunks(chunks)

        return summary

    def _execute_chunks(self, chunks: list[str]) -> RunSummary:
        """Execute source chunks sequentially, syncing runtime macro values."""
        combined = RunSummary(success=True)
        for chunk in chunks:
            if not chunk.strip():
                continue
            # A macro definition and its invocation stay in one raw chunk so
            # RUN/QUIT inside the definition is not split. If that expanded
            # body creates and later consumes an SQL INTO variable, expose its
            # generated step boundaries before executing it.
            if (
                re.search(r"%\s*MACRO\b", chunk, re.IGNORECASE)
                and self._has_later_runtime_macro_reference(chunk)
            ):
                self._sync_runtime_macro_values()
                expanded_chunk = self._macro.expand(chunk)
                for line in self._macro.put_output:
                    self._reporter.log(line)
                self._macro.put_output.clear()
                part = self._execute_staged_macro_source(expanded_chunk)
            else:
                part = self._execute_expanded(chunk)
            for step in part.steps:
                combined.add_step(step)
            if not part.success:
                combined.success = False
                combined.error = part.error
                break
        return combined

    def _execute_staged_macro_source(self, source: str) -> RunSummary:
        """Execute an expanded macro body while preserving runtime flow.

        A macro can create a value in one SAS step and consume it in a later
        macro statement.  Keep unexpanded macro-control groups on a queue,
        expanding only the next group after earlier executable steps have
        populated the session macro table.
        """
        combined = RunSummary(success=True)
        queue = self._split_into_step_chunks(source)
        while queue:
            chunk = queue.pop(0)
            if not chunk.strip():
                continue
            self._sync_runtime_macro_values()
            try:
                expanded = self._macro.expand_macro_fragment(chunk)
                for line in self._macro.put_output:
                    self._reporter.log(line)
                self._macro.put_output.clear()
            except Exception as exc:
                self._reporter.error(str(exc))
                combined.success = False
                combined.error = str(exc)
                break

            nested = self._split_into_step_chunks(expanded)
            if len(nested) > 1:
                queue[0:0] = nested
                continue

            part = self._execute_expanded(expanded, macro_fragment=True)
            for step in part.steps:
                combined.add_step(step)
            if not part.success:
                combined.success = False
                combined.error = part.error
                break
        return combined

    def _sync_runtime_macro_values(self) -> None:
        """Copy values produced by executable steps into the expander."""
        for scope in self._session._macro_stack:
            for key, value in scope.variables.items():
                if key in self._macro._local_vars:
                    self._macro._local_vars[key] = value
                else:
                    self._macro._global_vars[key] = value

    @staticmethod
    def _has_later_sql_into_reference(source: str) -> bool:
        """Return whether an INTO target is referenced later in the source."""
        into_clause = re.compile(
            r"\bINTO\b(?P<targets>.*?)\bFROM\b",
            flags=re.IGNORECASE | re.DOTALL,
        )
        target_name = re.compile(r":\s*([A-Za-z_]\w*)")
        for match in into_clause.finditer(source):
            remainder = source[match.end():]
            for name in target_name.findall(match.group("targets")):
                if re.search(rf"&{re.escape(name)}(?:\.|\b)", remainder, re.IGNORECASE):
                    return True
        return False

    @classmethod
    def _has_later_runtime_macro_reference(cls, source: str) -> bool:
        """Return whether a runtime-assigned macro variable is used later."""
        if cls._has_later_sql_into_reference(source):
            return True

        symput = re.compile(
            r"\bCALL\s+SYMPUTX?\s*\(\s*(['\"])([A-Za-z_]\w*)\1\s*,",
            flags=re.IGNORECASE,
        )
        for match in symput.finditer(source):
            name = match.group(2)
            if re.search(
                rf"&{re.escape(name)}(?:\.|\b)",
                source[match.end():],
                flags=re.IGNORECASE,
            ):
                return True
        return False

    def _execute_expanded(
        self,
        source: str,
        *,
        macro_fragment: bool = False,
    ) -> RunSummary:
        """Run the preprocess → macro-expand → parse → dispatch pipeline."""
        try:
            # Step 0.5: Preprocess DATALINES blocks
            source, datalines_list = self._preprocess_datalines(source)

            # Step 1: Macro expansion (sync CALL SYMPUT vars from session first)
            self._sync_runtime_macro_values()
            if macro_fragment:
                expanded = self._macro.expand_macro_fragment(source)
            else:
                expanded = self._macro.expand(source)

            # Report %PUT output
            for line in self._macro.put_output:
                self._reporter.log(line)
            self._macro.put_output.clear()

            if not expanded.strip():
                return RunSummary(success=True)

            # Step 2: Parse
            program = self._parser.parse(expanded)

            # Step 2.5: Inject DATALINES data into InputNodes
            self._inject_datalines(program, datalines_list)

            # Step 3: Dispatch and execute
            dispatcher = Dispatcher(self._session, self._reporter)

            # Register PROC handlers
            session = self._session
            reporter = self._reporter
            dispatcher.register_proc("PRINT", lambda p: handle_proc_print(p, session, reporter))
            dispatcher.register_proc("SGRENDER", lambda p: handle_proc_sgrender(p, session, reporter))
            dispatcher.register_proc("SORT", lambda p: handle_proc_sort(p, session, reporter))
            dispatcher.register_proc("CONTENTS", lambda p: handle_proc_contents(p, session, reporter))
            dispatcher.register_proc("MEANS", lambda p: handle_proc_means(p, session, reporter))
            dispatcher.register_proc("SUMMARY", lambda p: handle_proc_means(p, session, reporter))
            dispatcher.register_proc("FREQ", lambda p: handle_proc_freq(p, session, reporter))
            dispatcher.register_proc("IMPORT", lambda p: handle_proc_import(p, session, reporter))
            dispatcher.register_proc("EXPORT", lambda p: handle_proc_export(p, session, reporter))
            dispatcher.register_proc("APPEND", lambda p: handle_proc_append(p, session, reporter))
            dispatcher.register_proc("DATASETS", lambda p: handle_proc_datasets(p, session, reporter))
            dispatcher.register_proc("TRANSPOSE", lambda p: handle_proc_transpose(p, session, reporter))
            dispatcher.register_proc("UNIVARIATE", lambda p: handle_proc_univariate(p, session, reporter))
            dispatcher.register_proc("COMPARE", lambda p: handle_proc_compare(p, session, reporter))
            dispatcher.register_proc("COPY", lambda p: handle_proc_copy(p, session, reporter))
            dispatcher.register_proc("FORMAT", lambda p: handle_proc_format(p, session, reporter))
            dispatcher.register_proc("TABULATE", lambda p: handle_proc_tabulate(p, session, reporter))
            dispatcher.register_proc("REPORT", lambda p: handle_proc_report(p, session, reporter))
            dispatcher.register_proc("REG", lambda p: handle_proc_reg(p, session, reporter))
            dispatcher.register_proc("LOGISTIC", lambda p: handle_proc_logistic(p, session, reporter))
            dispatcher.register_proc("CORR", lambda p: handle_proc_corr(p, session, reporter))
            dispatcher.register_proc("TTEST", lambda p: handle_proc_ttest(p, session, reporter))
            dispatcher.register_proc("ODS", lambda p: handle_ods(p, session, reporter))
            dispatcher.register_proc("LIFETEST", lambda p: handle_proc_lifetest(p, session, reporter))
            dispatcher.register_proc("PHREG", lambda p: handle_proc_phreg(p, session, reporter))
            dispatcher.register_proc("GENMOD", lambda p: handle_proc_genmod(p, session, reporter))

            return dispatcher.run(program)

        except Exception as e:
            summary = RunSummary(success=False, error=str(e))
            self._reporter.error(str(e))
            return summary

    @staticmethod
    def _split_into_step_chunks(source: str) -> list[str]:
        """Split source into chunks at top-level RUN;/QUIT; boundaries.

        Respects DATALINES blocks, quoted strings, and %MACRO...%MEND
        definitions so a macro body is never split.
        """
        import re as _re
        chunks: list[str] = []
        lines = source.split("\n")
        current: list[str] = []
        datalines_terminator: str | None = None
        macro_depth = 0
        macro_control_depth = 0
        in_block_comment = False

        def structural_text(line: str) -> str:
            """Return code outside /* ... */ while preserving comment state."""
            nonlocal in_block_comment
            visible: list[str] = []
            position = 0
            while position < len(line):
                if in_block_comment:
                    end = line.find("*/", position)
                    if end < 0:
                        return "".join(visible)
                    in_block_comment = False
                    position = end + 2
                    continue
                start = line.find("/*", position)
                if start < 0:
                    visible.append(line[position:])
                    break
                visible.append(line[position:start])
                in_block_comment = True
                position = start + 2
            return "".join(visible)

        for line in lines:
            current.append(line)

            if datalines_terminator is not None:
                if line.strip() == datalines_terminator:
                    datalines_terminator = None
                continue

            active_line = structural_text(line)
            stripped = active_line.strip().upper()
            if not stripped:
                continue

            datalines_match = _re.match(
                r"^(DATALINES4|CARDS4|LINES4|DATALINES|CARDS)\s*;\s*$",
                stripped,
            )
            if datalines_match:
                datalines_terminator = (
                    ";;;;" if datalines_match.group(1).endswith("4") else ";"
                )
                continue

            macro_depth += len(_re.findall(r"%\s*MACRO\b", active_line, flags=_re.IGNORECASE))
            macro_depth -= len(_re.findall(r"%\s*MEND\b", active_line, flags=_re.IGNORECASE))
            if macro_depth < 0:
                macro_depth = 0

            if macro_depth == 0:
                macro_control_depth += len(
                    _re.findall(r"%\s*DO\b", active_line, flags=_re.IGNORECASE)
                )
                macro_control_depth -= len(
                    _re.findall(r"%\s*END\b", active_line, flags=_re.IGNORECASE)
                )
                if macro_control_depth < 0:
                    macro_control_depth = 0

            if (
                macro_depth == 0
                and macro_control_depth == 0
                and _re.search(r"\b(RUN|QUIT)\s*;\s*$", stripped)
            ):
                chunks.append("\n".join(current))
                current = []

        if current:
            chunks.append("\n".join(current))
        return chunks

    def execute_file(
        self,
        path: str | Path,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> RunSummary:
        """Execute a SAS script file."""
        path = Path(path)
        source = path.read_text(encoding=encoding, errors=errors)
        return self.execute(
            source,
            source_name=str(path),
            include_encoding=encoding,
            include_errors=errors,
        )

    def create_dataset(self, name: str, df: pd.DataFrame, libref: str = "WORK") -> None:
        """Create a dataset from a pandas DataFrame."""
        from saslite.runtime.dataset import Dataset
        ds = Dataset.from_dataframe(df, name=name, libref=libref)
        self._session.put_dataset(libref, name, ds)

    def get_dataset(self, libref: str, name: str) -> pd.DataFrame:
        """Get a dataset as a pandas DataFrame."""
        ds = self._session.get_dataset(libref, name)
        return ds.data

    def import_csv(self, filepath: str, dataset_name: str, libref: str = "WORK") -> None:
        """Import a CSV file as a dataset."""
        df = pd.read_csv(filepath)
        self.create_dataset(dataset_name, df, libref)

    def export_csv(self, dataset_name: str, filepath: str, libref: str = "WORK") -> None:
        """Export a dataset to CSV."""
        from saslite.runtime.formatting import csv_dataframe

        ds = self._session.get_dataset(libref, dataset_name)
        csv_dataframe(ds).to_csv(filepath, index=False)

    @classmethod
    def _expand_includes(
        cls,
        source: str,
        source_name: str = "<input>",
        encoding: str = "utf-8",
        errors: str = "strict",
        _stack: list[Path] | None = None,
    ) -> str:
        """Expand local `%INCLUDE` statements into the source text.

        Supported forms:
          %include "path/to/file.sas";
          %include 'path/to/file.sas';
          %include relative/path.sas;

        Relative include paths are resolved from the containing SAS file. Nested
        includes are supported, and include cycles are rejected.
        """
        stack = _stack or []
        base_dir = cls._include_base_dir(source_name)
        parts: list[str] = []
        cursor = 0

        for start, end, payload in cls._iter_include_statements(source):
            parts.append(source[cursor:start])
            targets = cls._parse_include_targets(payload)
            if not targets:
                raise ValueError("%INCLUDE requires a file path")

            included_chunks = []
            for target in targets:
                include_path = Path(target).expanduser()
                if not include_path.is_absolute():
                    include_path = base_dir / include_path
                include_path = include_path.resolve()

                if include_path in stack:
                    chain = " -> ".join(str(p) for p in [*stack, include_path])
                    raise ValueError(f"%INCLUDE cycle detected: {chain}")
                if not include_path.exists():
                    raise FileNotFoundError(f"%INCLUDE file not found: {include_path}")
                if not include_path.is_file():
                    raise ValueError(f"%INCLUDE target is not a file: {include_path}")

                include_source = include_path.read_text(
                    encoding=encoding,
                    errors=errors,
                )
                included_chunks.append(
                    cls._expand_includes(
                        include_source,
                        source_name=str(include_path),
                        encoding=encoding,
                        errors=errors,
                        _stack=[*stack, include_path],
                    )
                )

            parts.append("\n".join(included_chunks))
            cursor = end

        parts.append(source[cursor:])
        return "".join(parts)

    @staticmethod
    def _include_base_dir(source_name: str) -> Path:
        """Return the base directory for resolving relative includes."""
        if source_name.startswith("<") and source_name.endswith(">"):
            return Path.cwd()
        path = Path(source_name)
        if path.parent and str(path.parent) not in ("", "."):
            return path.parent.resolve()
        return Path.cwd()

    @staticmethod
    def _datalines_raw_ranges(source: str) -> list[tuple[int, int]]:
        """Return source ranges occupied by raw multiline DATALINES content."""
        ranges: list[tuple[int, int]] = []
        pos = 0
        raw_start: int | None = None
        terminator = ";"
        for line in source.splitlines(keepends=True):
            stripped = line.strip().upper()
            if raw_start is None:
                if stripped in (
                    "DATALINES;", "CARDS;", "DATALINES4;", "CARDS4;", "LINES4;",
                ):
                    raw_start = pos + len(line)
                    terminator = ";;;;" if stripped.rstrip(";").endswith("4") else ";"
            elif line.strip() == terminator:
                ranges.append((raw_start, pos + len(line)))
                raw_start = None
            pos += len(line)
        if raw_start is not None:
            ranges.append((raw_start, len(source)))
        return ranges

    @staticmethod
    def _iter_include_statements(source: str) -> list[tuple[int, int, str]]:
        """Find `%INCLUDE ...;` statements outside quotes and block comments."""
        statements: list[tuple[int, int, str]] = []
        datalines_ranges = SasInterpreter._datalines_raw_ranges(source)
        datalines_idx = 0
        i = 0
        n = len(source)
        in_single = False
        in_double = False
        in_comment = False

        while i < n:
            while (
                datalines_idx < len(datalines_ranges)
                and i >= datalines_ranges[datalines_idx][1]
            ):
                datalines_idx += 1
            if (
                datalines_idx < len(datalines_ranges)
                and datalines_ranges[datalines_idx][0] <= i < datalines_ranges[datalines_idx][1]
            ):
                i = datalines_ranges[datalines_idx][1]
                continue

            ch = source[i]
            nxt = source[i + 1] if i + 1 < n else ""

            if in_comment:
                if ch == "*" and nxt == "/":
                    in_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if not in_single and not in_double and ch == "/" and nxt == "*":
                in_comment = True
                i += 2
                continue

            if not in_double and ch == "'":
                in_single = not in_single
                i += 1
                continue
            if not in_single and ch == '"':
                in_double = not in_double
                i += 1
                continue

            if not in_single and not in_double and ch == "%":
                match = re.match(r"%\s*INCLUDE\b", source[i:], flags=re.IGNORECASE)
                if match:
                    payload_start = i + match.end()
                    j = payload_start
                    p_single = False
                    p_double = False
                    p_comment = False
                    while j < n:
                        pj = source[j]
                        pn = source[j + 1] if j + 1 < n else ""
                        if p_comment:
                            if pj == "*" and pn == "/":
                                p_comment = False
                                j += 2
                                continue
                            j += 1
                            continue
                        if not p_single and not p_double and pj == "/" and pn == "*":
                            p_comment = True
                            j += 2
                            continue
                        if not p_double and pj == "'":
                            p_single = not p_single
                        elif not p_single and pj == '"':
                            p_double = not p_double
                        elif not p_single and not p_double and pj == ";":
                            statements.append((i, j + 1, source[payload_start:j]))
                            i = j + 1
                            break
                        j += 1
                    else:
                        raise ValueError("%INCLUDE statement is missing a semicolon")
                    continue

            i += 1

        return statements

    @staticmethod
    def _parse_include_targets(payload: str) -> list[str]:
        """Extract include file paths from a `%INCLUDE` payload."""
        payload = payload.strip()
        if not payload:
            return []

        quoted = [
            match.group(2)
            for match in re.finditer(r"(['\"])(.*?)\1", payload, flags=re.DOTALL)
        ]
        if quoted:
            return [item for item in quoted if item]

        before_options = re.split(r"\s+/\s+", payload, maxsplit=1)[0].strip()
        if not before_options:
            return []
        return [before_options.split()[0]]

    @staticmethod
    def _preprocess_datalines(source: str) -> tuple[str, list[str]]:
        """Extract DATALINES/CARDS blocks and replace with assignment markers.

        Returns (modified_source, list_of_raw_data_strings).
        """
        datalines_list: list[str] = []

        # Pass 1: Handle inline DATALINES (same line as keyword)
        # Pattern: DATALINES; non_semicolon_data ;
        def _replace_inline(m: re.Match) -> str:
            data = m.group(1)
            idx = len(datalines_list)
            datalines_list.append(data)
            # Keep raw input outside the generated SAS source. Embedding it in
            # a quoted assignment breaks as soon as a data record itself
            # contains quotes (for example a normal DSD/CSV record).
            return f"__DATALINES_{idx}__ = {idx};"

        source = re.sub(
            r"(?i)(?:DATALINES|CARDS)\s*;\s*([^;]+?)\s*;",
            _replace_inline,
            source,
        )

        # Pass 2: Handle multi-line DATALINES (keyword on own line)
        lines = source.split("\n")
        result_lines: list[str] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip().upper()
            if stripped in (
                "DATALINES;", "CARDS;", "DATALINES4;", "CARDS4;", "LINES4;",
            ):
                data_lines: list[str] = []
                terminator = ";;;;" if stripped.rstrip(";").endswith("4") else ";"
                i += 1
                while i < len(lines):
                    if lines[i].strip() == terminator:
                        break
                    data_lines.append(lines[i])
                    i += 1
                idx = len(datalines_list)
                datalines_data = "\n".join(data_lines)
                datalines_list.append(datalines_data)
                result_lines.append(f"  __DATALINES_{idx}__ = {idx};")
                i += 1
            else:
                result_lines.append(lines[i])
                i += 1

        return "\n".join(result_lines), datalines_list

    @staticmethod
    def _inject_datalines(program: Any, datalines_list: list[str]) -> None:
        """Inject DATALINES data into DataStepNodes that have InputNodes."""
        from saslite.ast.data_step import DataStepNode, InputNode, AssignNode
        from saslite.ast.expressions import LiteralNode

        for step in program.steps:
            if not isinstance(step, DataStepNode):
                continue

            input_node = None
            placeholder_idx = None

            for j, stmt in enumerate(step.statements):
                if isinstance(stmt, InputNode):
                    input_node = stmt
                elif (isinstance(stmt, AssignNode)
                      and stmt.target.startswith("__DATALINES_")
                      and isinstance(stmt.expr, LiteralNode)):
                    placeholder_idx = j

            if input_node is not None and placeholder_idx is not None:
                placeholder = step.statements[placeholder_idx]
                match = re.fullmatch(r"__DATALINES_(\d+)__", placeholder.target)
                if match:
                    raw_index = int(match.group(1))
                    if raw_index < len(datalines_list):
                        input_node.datalines_data = datalines_list[raw_index]
                # Remove the placeholder statement
                step.statements.pop(placeholder_idx)
