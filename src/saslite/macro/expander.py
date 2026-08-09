"""Macro preprocessor: expands %LET, &var, %MACRO/%MEND, and handles comments."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime as _datetime
from typing import Any


@dataclass
class MacroDef:
    """Definition of a SAS macro."""
    name: str
    params: list[str] = field(default_factory=list)
    body: str = ""
    defaults: dict[str, str] = field(default_factory=dict)


class MacroExpander:
    """Macro expander for %LET, &var, %MACRO/%MEND, and macro invocation."""

    _OPEN_CODE_MACRO_ERROR = "Macro code is not allowed in open code."
    _QUOTED_AMPERSAND = "\ue000"
    _QUOTED_PERCENT = "\ue001"
    _MACRO_SCOPE_KEYWORDS = (
        # Modern SAS accepts %IF and %DO control flow in open code.  Only the
        # following statements inherently require a macro-local scope or
        # return target.
        "GOTO", "RETURN", "LOCAL", "MEND",
    )

    def __init__(self, session: Any | None = None) -> None:
        self._global_vars: dict[str, str] = {}
        self._local_vars: dict[str, str] = {}
        self._macro_scopes: list[dict[str, str | None]] = []
        self._macros: dict[str, MacroDef] = {}
        self._put_output: list[str] = []
        self._session = session
        self._dataset_handles: dict[int, Any] = {}
        self._next_dataset_handle = 1
        self._init_automatic_vars()

    def _init_automatic_vars(self) -> None:
        """Populate SAS automatic macro variables (computed once per session)."""
        now = _datetime.now()
        self._global_vars["SYSDATE"] = now.strftime("%d%b%y").upper()
        self._global_vars["SYSDATE9"] = now.strftime("%d%b%Y").upper()
        self._global_vars["SYSTIME"] = now.strftime("%H:%M")
        self._global_vars["SYSDAY"] = now.strftime("%A")
        self._global_vars["SYSVER"] = "9.4"
        self._global_vars["SYSERR"] = "0"
        if sys.platform.startswith("win"):
            self._global_vars["SYSSCP"] = "WIN"
        elif sys.platform == "darwin":
            self._global_vars["SYSSCP"] = "MAC"
        else:
            self._global_vars["SYSSCP"] = "LIN X64"

    def set_var(self, name: str, value: str) -> None:
        key = name.upper()
        if self._macro_scopes:
            self._macro_scopes[-1][key] = value
        else:
            self._local_vars[key] = value
            if self._session is not None:
                self._session.set_macro_var(key, value)

    def get_var(self, name: str) -> str | None:
        key = name.upper()
        for scope in reversed(self._macro_scopes):
            if key in scope:
                return scope[key]
        if key in self._local_vars:
            return self._local_vars[key]
        if key in self._global_vars:
            return self._global_vars[key]
        return None

    def _log_symbolgen(self, var_name: str, value: str) -> None:
        """Log SYMBOLGEN output if enabled."""
        if self._session and self._session.get_option("SYMBOLGEN", False):
            msg = f"SYMBOLGEN:  Macro variable {var_name.upper()} resolves to {value}"
            self._session.add_debug_output(msg)

    def _log_mprint(self, text: str) -> None:
        """Log MPRINT output if enabled."""
        if self._session and self._session.get_option("MPRINT", False):
            msg = f"MPRINT:  {text.strip()}"
            self._session.add_debug_output(msg)

    def _log_mlogic(self, message: str) -> None:
        """Log MLOGIC output if enabled."""
        if self._session and self._session.get_option("MLOGIC", False):
            msg = f"MLOGIC:  {message}"
            self._session.add_debug_output(msg)

    @property
    def put_output(self) -> list[str]:
        """Collected %PUT output lines."""
        return self._put_output

    def expand(self, source: str) -> str:
        """Expand macro variables and process %LET / %MACRO statements.

        This is the main entry point. It:
        1. Removes block comments /* ... */
        2. Converts SAS format/informat literals (e.g. e8601da.) to quoted strings
        3. Processes %MACRO/%MEND definitions
        4. Processes %LET statements (must be before conditionals)
        5. Processes %DO %TO %BY iterative loops
        6. Substitutes &var references
        7. Processes %IF/%THEN/%ELSE conditionals
        8. Expands macro invocations (%name)
        9. Final &var substitution pass
        """
        # Step 1: Remove block comments
        source = self._remove_comments(source)

        # Step 1.5: Convert format/informat literals to quoted strings
        source = self._quote_format_literals(source)

        # Step 2: Process %MACRO/%MEND definitions
        source = self._process_macro_definitions(source)
        source = self._process_global_declarations(source)

        # Macro control statements are valid only inside a macro definition.
        # Definitions have been removed from the open-code stream above, while
        # their bodies will be processed later when the macro is invoked.
        self._reject_open_code_macro_statements(source)

        # Step 2.5: Process macro character functions and %SYSFUNC
        source = self._process_macro_functions(source)

        # Step 3: Process %DO %TO %BY iterative loops
        source = self._process_do_loops(source)

        # Step 4: Process %EVAL/%SYSEVALF expressions
        source = self._process_eval(source)

        # Step 5: Process %LET statements (after eval so values resolve)
        source = self._process_let_statements(source)

        # Step 5.5: Macro functions may now resolve with %LET values
        source = self._process_macro_functions(source)

        # Step 6: Process %IF/%THEN/%ELSE conditionals.  Conditions resolve
        # their own variables in source order; substituting the entire tail
        # here would freeze references before a selected branch can %LET them.
        source = self._process_conditionals(source)

        # Step 8: Process %PUT statements
        source = self._process_put_statements(source)

        # Step 9: Expand macro invocations
        source = self._expand_macro_invocations(source)

        # Step 9.5: The expanded macro bodies may contain %DO/%EVAL/%LET/
        # %IF/%PUT and macro functions — process them now.
        source = self._process_macro_functions(source)
        source = self._process_do_loops(source)
        source = self._process_eval(source)
        source = self._process_let_statements(source)
        source = self._process_conditionals(source)
        source = self._process_put_statements(source)

        # Step 10: Final &var substitution pass
        source = self._substitute_vars(source)

        return self._unquote_macro_value(source)

    def _remove_comments(self, source: str) -> str:
        """Remove /* ... */ block comments, %* ... ; macro comments, and
        SAS statement comments (``* ... ;``).

        A statement comment can start at the beginning of the source or at
        any subsequent statement boundary.  In particular, it may span
        lines and commonly uses several leading/trailing asterisks.  Remove
        these before interpreting macro text so a ``%LET`` or ``&name`` in a
        comment cannot affect expansion.
        """
        # Use a scanner instead of repeatedly applying a DOTALL regex.  A
        # staged source chunk can end inside a block comment; the former
        # ``while '/*'`` loop made no progress in that case and ran forever.
        uncommented: list[str] = []
        position = 0
        while position < len(source):
            start = source.find("/*", position)
            if start < 0:
                uncommented.append(source[position:])
                break
            uncommented.append(source[position:start])
            end = source.find("*/", start + 2)
            if end < 0:
                # SAS treats the rest of the submitted source as commented.
                position = len(source)
                break
            position = end + 2
        source = "".join(uncommented)
        source = re.sub(r"%\*[^;]*;", "", source)
        # A leading star denotes a comment only where a new statement may
        # begin.  This deliberately does not match multiplication or SQL's
        # SELECT * wildcard.
        source = re.sub(
            r"(?:\A|(?<=;))(?P<space>[ \t\r\n]*)\*[^;]*;",
            lambda match: match.group("space"),
            source,
        )
        return source

    def _quote_format_literals(self, source: str) -> str:
        """Convert unquoted SAS format/informat literals to quoted strings.

        SAS format/informat names always end with a dot (e.g. e8601da., date9., best32.).
        They appear as the second argument to INPUT() and PUT() functions.
        Convert:  input(x, e8601da.)  ->  input(x, 'e8601da.')
                  put(x, e8601da.)    ->  put(x, 'e8601da.')
        """
        # Use a character-level scanner to find INPUT/PUT calls and quote format args
        result = []
        i = 0
        upper = source.upper()
        n = len(source)
        while i < n:
            # Look for INPUT( or PUT(
            if (upper[i:i+5] == 'INPUT' or upper[i:i+3] == 'PUT') and i > 0 and (source[i-1].isalnum() or source[i-1] == '_'):
                result.append(source[i])
                i += 1
                continue
            if upper[i:i+5] == 'INPUT' and i + 5 < n and not source[i+5].isalnum() and source[i+5] != '_':
                func_end = i + 5
                result.append(source[i:func_end])
                i = func_end
            elif upper[i:i+3] == 'PUT' and i + 3 < n and not source[i+3].isalnum() and source[i+3] != '_':
                func_end = i + 3
                result.append(source[i:func_end])
                i = func_end
            else:
                result.append(source[i])
                i += 1
                continue
            # Skip whitespace to find (
            while i < n and source[i] in ' \t\n':
                result.append(source[i])
                i += 1
            if i >= n or source[i] != '(':
                continue
            # Found opening paren — find matching closing paren
            result.append(source[i])
            i += 1
            depth = 1
            inner_start = i
            while i < n and depth > 0:
                if source[i] == '(':
                    depth += 1
                elif source[i] == ')':
                    depth -= 1
                i += 1
            inner = source[inner_start:i-1]  # content between parens
            closing = source[i-1]  # )
            # Split inner by comma at depth 0
            parts = self._split_func_args(inner)
            if len(parts) >= 2:
                last_arg = parts[-1].strip()
                # Check if it's an unquoted format literal
                if re.match(r'^[A-Za-z_]\w*\.(\d+\.?(\d+)?)?$', last_arg) or \
                   re.match(r'^\d+\.\d*$', last_arg):
                    parts[-1] = f"'{last_arg}'"
                    result.append(','.join(parts))
                    result.append(closing)
                    continue
            # No quoting needed — output as-is
            result.append(inner)
            result.append(closing)
        return ''.join(result)

    def _split_func_args(self, inner: str) -> list[str]:
        """Split function arguments by comma, respecting parentheses depth."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in inner:
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    def _process_macro_definitions(self, source: str) -> str:
        """Extract top-level macro definitions with balanced nesting.

        A non-greedy regular expression pairs an outer ``%MACRO`` with the
        first ``%MEND`` it sees.  That truncates an outer definition when its
        body declares a helper macro.  Scan macro tokens and pair them by
        depth instead; nested definitions remain in the outer body until the
        outer macro is invoked.
        """
        masked = self._mask_quoted_text(source)
        macro_head = re.compile(r"%\s*MACRO\s+(\w+)", re.IGNORECASE)
        macro_token = re.compile(r"%\s*(MACRO|MEND)\b", re.IGNORECASE)
        chunks: list[str] = []
        cursor = 0
        search_at = 0

        while True:
            head = macro_head.search(masked, search_at)
            if head is None:
                chunks.append(source[cursor:])
                break

            name = head.group(1).upper()
            header_end, params_str = self._parse_macro_header(
                source,
                masked,
                head.end(),
                name,
            )

            depth = 1
            token_at = header_end
            closing_start: int | None = None
            closing_end: int | None = None
            while depth:
                token = macro_token.search(masked, token_at)
                if token is None:
                    raise SyntaxError(f"Unclosed %MACRO {name} definition")
                token_kind = token.group(1).upper()
                if token_kind == "MACRO":
                    depth += 1
                    token_at = token.end()
                    continue

                depth -= 1
                if depth:
                    token_at = token.end()
                    continue

                closing_start = token.start()
                closing_end = self._parse_mend_end(masked, token.end(), name)

            assert closing_start is not None and closing_end is not None
            self._register_macro(
                name,
                params_str,
                source[header_end:closing_start],
            )
            chunks.append(source[cursor:head.start()])
            cursor = closing_end
            search_at = closing_end

        return "".join(chunks)

    @staticmethod
    def _mask_quoted_text(source: str) -> str:
        """Replace quoted text with spaces while preserving string offsets."""
        masked = list(source)
        quote: str | None = None
        i = 0
        while i < len(source):
            ch = source[i]
            if quote is None:
                if ch in ("'", '"'):
                    quote = ch
                    masked[i] = " "
                i += 1
                continue

            masked[i] = " "
            if ch == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    masked[i + 1] = " "
                    i += 2
                    continue
                quote = None
            i += 1
        return "".join(masked)

    @staticmethod
    def _parse_macro_header(
        source: str,
        masked: str,
        position: int,
        name: str,
    ) -> tuple[int, str]:
        """Return the body start and raw parameter list for a definition."""
        while position < len(masked) and masked[position].isspace():
            position += 1

        params_str = ""
        if position < len(masked) and masked[position] == "(":
            params_start = position + 1
            depth = 1
            position += 1
            while position < len(masked) and depth:
                if masked[position] == "(":
                    depth += 1
                elif masked[position] == ")":
                    depth -= 1
                position += 1
            if depth:
                raise SyntaxError(f"Unclosed parameter list for %MACRO {name}")
            params_str = source[params_start:position - 1]
            while position < len(masked) and masked[position].isspace():
                position += 1

        # SAS permits definition options after the parameter list, for example
        # ``%macro report(...) / minoperator;``.  They affect macro-expression
        # semantics, but the header itself remains valid even when no option
        # needs special handling by the expander.
        if position < len(masked) and masked[position] == "/":
            semicolon = masked.find(";", position + 1)
            if semicolon < 0:
                raise SyntaxError(f"Expected ';' after %MACRO {name}")
            position = semicolon

        if position >= len(masked) or masked[position] != ";":
            raise SyntaxError(f"Expected ';' after %MACRO {name}")
        return position + 1, params_str

    @staticmethod
    def _parse_mend_end(masked: str, position: int, macro_name: str) -> int:
        """Consume optional name and the semicolon in ``%MEND [name];``."""
        while position < len(masked) and masked[position].isspace():
            position += 1
        named = re.match(r"\w+", masked[position:])
        if named is not None:
            closing_name = named.group(0)
            position += named.end()
            if closing_name.upper() != macro_name:
                raise SyntaxError(
                    f"%MEND {closing_name} does not match %MACRO {macro_name}"
                )
            while position < len(masked) and masked[position].isspace():
                position += 1
        if position >= len(masked) or masked[position] != ";":
            raise SyntaxError(f"Expected ';' after %MEND for {macro_name}")
        return position + 1

    def _register_macro(self, name: str, params_str: str, body: str) -> None:
        params: list[str] = []
        defaults: dict[str, str] = {}
        for parameter in self._split_args_depth0(params_str):
            parameter = parameter.strip()
            if not parameter:
                continue
            if "=" in parameter:
                param_name, default = parameter.split("=", 1)
                param_name = param_name.strip().upper()
                params.append(param_name)
                defaults[param_name] = default.strip()
            else:
                params.append(parameter.upper())
        self._macros[name] = MacroDef(
            name=name,
            params=params,
            body=body,
            defaults=defaults,
        )

    def _reject_open_code_macro_statements(self, source: str) -> None:
        """Reject macro control statements outside %MACRO/%MEND definitions."""
        # Do not interpret percent-prefixed text inside quoted SAS strings as
        # macro statements. SAS escapes a quote inside a string by doubling it.
        unquoted: list[str] = []
        quote: str | None = None
        i = 0
        while i < len(source):
            ch = source[i]
            if quote is None:
                if ch in ("'", '"'):
                    quote = ch
                    unquoted.append(" ")
                else:
                    unquoted.append(ch)
                i += 1
                continue

            unquoted.append(" ")
            if ch == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    unquoted.append(" ")
                    i += 2
                    continue
                quote = None
            i += 1

        keywords = "|".join(self._MACRO_SCOPE_KEYWORDS)
        if re.search(rf"%\s*(?:{keywords})\b", "".join(unquoted), re.IGNORECASE):
            raise SyntaxError(self._OPEN_CODE_MACRO_ERROR)

    def _process_conditionals(self, source: str) -> str:
        """Process %IF ... %THEN ... %ELSE ... %DO ... %END; conditionals."""
        max_iterations = 100
        for _ in range(max_iterations):
            # Execute source-order %LET statements that precede the next
            # conditional, but leave assignments inside its branches alone
            # until that branch has actually been selected.
            new_source = self._process_let_statements(source)
            new_source = self._process_conditionals_once(new_source)
            if new_source == source:
                break
            source = new_source
        return source

    def _process_conditionals_once(self, source: str) -> str:
        """Evaluate the first conditional using balanced macro DO/END pairs."""
        masked = self._mask_quoted_text(source)
        if_match = re.search(r"%\s*IF\b", masked, flags=re.IGNORECASE)
        if if_match is None:
            return source
        then_match = re.search(
            r"%\s*THEN\b",
            masked[if_match.end():],
            flags=re.IGNORECASE,
        )
        if then_match is None:
            return source
        then_start = if_match.end() + then_match.start()
        then_end = if_match.end() + then_match.end()
        condition = source[if_match.end():then_start].strip()

        then_body, branch_end = self._parse_macro_conditional_branch(
            source,
            masked,
            then_end,
        )
        else_body = ""
        conditional_end = branch_end
        else_at = self._skip_whitespace(masked, branch_end)
        else_match = re.match(r"%\s*ELSE\b", masked[else_at:], re.IGNORECASE)
        if else_match is not None:
            else_branch_at = self._skip_whitespace(
                masked, else_at + else_match.end()
            )
            if re.match(r"%\s*IF\b", masked[else_branch_at:], re.IGNORECASE):
                conditional_end = self._macro_conditional_end(
                    source, masked, else_branch_at
                )
                else_body = source[else_branch_at:conditional_end]
            else:
                else_body, conditional_end = self._parse_macro_conditional_branch(
                    source,
                    masked,
                    else_branch_at,
                )

        condition_result = self._eval_macro_condition(condition)
        if condition_result is None:
            # A macro variable populated by a preceding executable step (for
            # example SELECT INTO or CALL SYMPUTX) is not available yet.  Keep
            # the complete conditional intact so staged execution can retry
            # it after that step has run.
            return source
        chosen = then_body if condition_result else else_body
        chosen = self._process_conditionals(chosen)
        return source[:if_match.start()] + chosen + source[conditional_end:]

    def _macro_conditional_end(
        self,
        source: str,
        masked: str,
        if_start: int,
    ) -> int:
        """Return the extent of a nested ``%IF ... %ELSE %IF ...`` chain."""
        if_match = re.match(r"%\s*IF\b", masked[if_start:], re.IGNORECASE)
        if if_match is None:
            return if_start
        condition_start = if_start + if_match.end()
        then_match = re.search(
            r"%\s*THEN\b", masked[condition_start:], re.IGNORECASE
        )
        if then_match is None:
            return if_start
        then_end = condition_start + then_match.end()
        _body, branch_end = self._parse_macro_conditional_branch(
            source, masked, then_end
        )
        else_at = self._skip_whitespace(masked, branch_end)
        else_match = re.match(r"%\s*ELSE\b", masked[else_at:], re.IGNORECASE)
        if else_match is None:
            return branch_end
        else_branch_at = self._skip_whitespace(
            masked, else_at + else_match.end()
        )
        if re.match(r"%\s*IF\b", masked[else_branch_at:], re.IGNORECASE):
            return self._macro_conditional_end(source, masked, else_branch_at)
        _else_body, conditional_end = self._parse_macro_conditional_branch(
            source, masked, else_branch_at
        )
        return conditional_end

    @staticmethod
    def _skip_whitespace(source: str, position: int) -> int:
        while position < len(source) and source[position].isspace():
            position += 1
        return position

    def _parse_macro_conditional_branch(
        self,
        source: str,
        masked: str,
        position: int,
    ) -> tuple[str, int]:
        """Return branch text and end offset for block or single statement."""
        branch_start = self._skip_whitespace(masked, position)
        do_match = re.match(r"%\s*DO\b[^;]*;", masked[branch_start:], re.IGNORECASE)
        if do_match is not None:
            content_start = branch_start + do_match.end()
            end_start, end_after = self._find_matching_macro_end(
                masked,
                content_start,
            )
            return source[content_start:end_start], end_after

        semicolon = masked.find(";", branch_start)
        if semicolon < 0:
            raise SyntaxError("Macro %IF branch is missing a semicolon")
        return source[branch_start:semicolon + 1], semicolon + 1

    @staticmethod
    def _find_matching_macro_end(masked: str, position: int) -> tuple[int, int]:
        """Pair a macro %DO block with its depth-matched %END statement."""
        token_re = re.compile(r"%\s*(DO|END)\b", re.IGNORECASE)
        depth = 1
        search_at = position
        while True:
            token = token_re.search(masked, search_at)
            if token is None:
                raise SyntaxError("Macro %DO block has no matching %END")
            if token.group(1).upper() == "DO":
                depth += 1
                search_at = token.end()
                continue
            depth -= 1
            if depth:
                search_at = token.end()
                continue
            end_after = token.end()
            end_after = MacroExpander._skip_whitespace(masked, end_after)
            if end_after >= len(masked) or masked[end_after] != ";":
                raise SyntaxError("Expected ';' after macro %END")
            return token.start(), end_after + 1

    def _eval_conditional(self, match: re.Match) -> str:
        """Evaluate a %IF/%THEN/%DO conditional and return the chosen branch."""
        condition = match.group(1).strip()
        then_body = match.group(2)
        else_body = match.group(3) if match.group(3) else ""
        if self._eval_macro_condition(condition):
            return then_body
        return else_body

    def _eval_conditional_single(self, match: re.Match) -> str:
        """Evaluate a %IF/%THEN single-statement conditional."""
        condition = match.group(1).strip()
        then_body = match.group(2)
        else_body = match.group(3) if match.group(3) else ""
        if self._eval_macro_condition(condition):
            return then_body
        return else_body

    def _eval_macro_condition(self, condition: str) -> bool | None:
        """Evaluate a macro-level condition like 'X = 1' or 'X NE Y'."""
        # Substitute any remaining &vars
        condition = self._substitute_vars(condition)

        # Runtime-created macro variables deliberately remain unresolved
        # during the first expansion pass.  Likewise, a macro function whose
        # arguments are not ready is retained for a later staged pass.
        if re.search(r"&[A-Za-z_]\w*", condition) or re.search(
            r"%\s*(?:SYSEVALF|EVAL|SYSFUNC)\s*\(",
            condition,
            flags=re.IGNORECASE,
        ):
            return None

        # Boolean macro expressions do not necessarily arrive through
        # %EVAL/%SYSEVALF.  Split only top-level words so quoted labels and
        # function arguments containing AND/OR stay intact.  OR has the lower
        # precedence and is therefore handled first.
        or_parts = self._split_macro_boolean(condition, "OR")
        if len(or_parts) > 1:
            results = [self._eval_macro_condition(part) for part in or_parts]
            if any(result is True for result in results):
                return True
            return None if any(result is None for result in results) else False
        and_parts = self._split_macro_boolean(condition, "AND")
        if len(and_parts) > 1:
            results = [self._eval_macro_condition(part) for part in and_parts]
            if any(result is False for result in results):
                return False
            return None if any(result is None for result in results) else True

        # Handle comparison operators
        for op in ("<>", " NE ", " GE ", " LE ", " GT ", " LT ", ">=", "<=", "=", ">", "<"):
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    left = parts[0].strip().strip("'\"")
                    right = parts[1].strip().strip("'\"")
                    try:
                        left_n = float(left)
                        right_n = float(right)
                        left, right = left_n, right_n
                    except ValueError:
                        pass
                    if op.strip() in ("=", ""):
                        return left == right
                    if op.strip() in ("NE", "<>"):
                        return left != right
                    if op.strip() == ">":
                        return left > right
                    if op.strip() == ">=" or op.strip() == "GE":
                        return left >= right
                    if op.strip() == "<":
                        return left < right
                    if op.strip() == "<=" or op.strip() == "LE":
                        return left <= right
                    if op.strip() == "GT":
                        return left > right
                    if op.strip() == "LT":
                        return left < right
        # If no operator, check if non-empty / non-zero
        condition = condition.strip()
        not_match = re.match(r"^NOT\b(.*)$", condition, flags=re.IGNORECASE | re.DOTALL)
        if not_match is not None:
            inner = self._eval_macro_condition(not_match.group(1).strip())
            return None if inner is None else not inner
        val = condition.strip("'\"")
        return val not in ("", "0", ".", "FALSE")

    @staticmethod
    def _split_macro_boolean(condition: str, operator: str) -> list[str]:
        """Split a top-level macro boolean operator outside quotes/parens."""
        pieces: list[str] = []
        start = 0
        depth = 0
        quote: str | None = None
        index = 0
        while index < len(condition):
            character = condition[index]
            if quote is not None:
                if character == quote:
                    if index + 1 < len(condition) and condition[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                index += 1
                continue
            if character in ("'", '"'):
                quote = character
                index += 1
                continue
            if character == "(":
                depth += 1
                index += 1
                continue
            if character == ")":
                depth = max(0, depth - 1)
                index += 1
                continue
            end = index + len(operator)
            if (
                depth == 0
                and condition[index:end].upper() == operator
                and (index == 0 or not condition[index - 1].isalnum())
                and (end == len(condition) or not condition[end].isalnum())
            ):
                pieces.append(condition[start:index].strip())
                start = end
                index = end
                continue
            index += 1
        pieces.append(condition[start:].strip())
        return pieces

    def _expand_macro_invocations(self, source: str) -> str:
        """Expand %macro_name and %macro_name(args) invocations."""
        max_iterations = 20  # Prevent infinite loops
        for _ in range(max_iterations):
            expanded = self._expand_once(source)
            # Invoking an outer macro can emit a helper definition from its
            # body. Register that helper before the next expansion pass, while
            # leaving its body (including macro conditionals) unevaluated
            # until the helper itself is invoked.
            expanded = self._process_macro_definitions(expanded)
            if expanded == source:
                break
            source = expanded
        return source

    @staticmethod
    def _apply_return_goto(body: str) -> str:
        """Apply %RETURN and %GOTO/%label semantics to an expanded macro body.

        %RETURN; truncates the rest of the body. %GOTO name; skips forward
        to the matching %name: label (backward jumps are ignored to avoid
        infinite loops). Remaining label markers are removed.
        """
        # %RETURN — truncate
        m = re.search(r"%\s*RETURN\s*;", body, flags=re.IGNORECASE)
        if m:
            body = body[:m.start()]

        # %GOTO label — forward jump only
        for _ in range(20):
            g = re.search(r"%\s*GOTO\s+(\w+)\s*;", body, flags=re.IGNORECASE)
            if g is None:
                break
            label = g.group(1)
            lbl = re.compile(rf"%\s*{re.escape(label)}\s*:", flags=re.IGNORECASE)
            target = lbl.search(body, g.end())
            if target:
                body = body[:g.start()] + body[target.end():]
            else:
                # Label not found ahead — drop the %GOTO and continue
                body = body[:g.start()] + body[g.end():]

        # Strip leftover label markers
        body = re.sub(r"%\s*\w+\s*:", "", body)
        return body

    def _expand_once(self, source: str) -> str:
        """Single pass of macro expansion."""
        # %name without arguments: %name;
        pattern_no_args = r"%(\w+)\s*;"

        skip_keywords = {"LET", "MACRO", "MEND", "IF", "THEN", "ELSE", "DO", "END",
                         "PUT", "INCLUDE", "GOTO", "RETURN", "EVAL", "SYSEVALF",
                         "UPCASE", "LOWCASE", "SCAN", "SUBSTR", "LENGTH", "INDEX",
                         "STR", "NRSTR", "SUPERQ", "SYSFUNC", "TO", "BY"}

        def expand_with_args(macro_name: str, args_str: str) -> str:
            macro = self._macros[macro_name]
            args = [a.strip() for a in self._split_args_depth0(args_str)]
            # Build local variable scope: defaults first, then positional
            # and keyword (name=value) arguments
            local_vars: dict[str, str] = dict(macro.defaults)
            pos_idx = 0
            for arg in args:
                if not arg:
                    pos_idx += 1
                    continue
                kw = re.match(r"^(\w+)\s*=\s*(.*)$", arg, flags=re.DOTALL)
                if kw and kw.group(1).upper() in macro.params:
                    local_vars[kw.group(1).upper()] = self._strip_matching_quotes(
                        kw.group(2)
                    )
                else:
                    if pos_idx < len(macro.params):
                        local_vars[macro.params[pos_idx]] = self._strip_matching_quotes(arg)
                    pos_idx += 1
            # Expand body with local vars
            return self._expand_invoked_macro(macro, local_vars)

        # Expand calls with a balanced scanner.  Macro arguments routinely
        # contain nested calls such as %SCAN(...); a ``[^)]*`` regex truncates
        # the outer invocation at the first inner closing parenthesis.
        head_re = re.compile(r"%(\w+)\s*\(", flags=re.IGNORECASE)
        expanded_parts: list[str] = []
        copy_from = 0
        search_at = 0
        while True:
            match = head_re.search(source, search_at)
            if match is None:
                expanded_parts.append(source[copy_from:])
                break
            macro_name = match.group(1).upper()
            if macro_name in skip_keywords or macro_name not in self._macros:
                search_at = match.end()
                continue

            depth = 1
            quote: str | None = None
            position = match.end()
            while position < len(source) and depth:
                char = source[position]
                if quote is not None:
                    if char == quote:
                        if position + 1 < len(source) and source[position + 1] == quote:
                            position += 2
                            continue
                        quote = None
                    position += 1
                    continue
                if char in ("'", '"'):
                    quote = char
                elif char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                position += 1

            if depth:
                expanded_parts.append(source[copy_from:])
                break

            args_str = source[match.end():position - 1]
            call_end = position
            while call_end < len(source) and source[call_end] in " \t\r":
                call_end += 1
            if call_end < len(source) and source[call_end] == ";":
                call_end += 1

            expanded_parts.append(source[copy_from:match.start()])
            expanded_parts.append(expand_with_args(macro_name, args_str))
            copy_from = call_end
            search_at = call_end

        source = "".join(expanded_parts)

        # Then expand %name; (no args)
        def replacer_no_args(match: re.Match) -> str:
            macro_name = match.group(1).upper()
            if macro_name in skip_keywords:
                return match.group(0)
            if macro_name not in self._macros:
                return match.group(0)
            macro = self._macros[macro_name]
            return self._expand_invoked_macro(macro, dict(macro.defaults))

        source = re.sub(pattern_no_args, replacer_no_args, source, flags=re.IGNORECASE)
        return source

    @staticmethod
    def _strip_matching_quotes(value: str) -> str:
        text = value.strip()
        if (
            len(text) >= 2
            and text[0] in ("'", '"')
            and text[-1] == text[0]
        ):
            return text[1:-1]
        return text

    def _expand_invoked_macro(
        self,
        macro: MacroDef,
        parameter_values: dict[str, str],
    ) -> str:
        """Expand one macro invocation inside an isolated local scope."""
        scope = {name.upper(): value for name, value in parameter_values.items()}
        self._macro_scopes.append(scope)
        try:
            body = self._process_local_declarations(macro.body, scope)
            # Capture parameter values textually, including references inside
            # a nested helper definition. Other locals must remain unresolved
            # until their %LET statements have executed below.
            for name, value in parameter_values.items():
                body = re.sub(
                    rf"&{re.escape(name)}\b\.?",
                    value,
                    body,
                    flags=re.IGNORECASE,
                )
            # Extract nested helper definitions before processing %IF/%PUT in
            # the outer body; their control statements execute only when the
            # helper itself is invoked.
            body = self._process_macro_definitions(body)
            body = self._process_macro_functions(body)
            body = self._process_eval(body)
            body = self._process_global_declarations(body)
            body = self._process_let_statements(body)
            body = self._process_conditionals(body)
            # Expand iterative %DO only after false conditional branches have
            # been discarded; otherwise their %END tokens can be consumed as
            # if they closed the surrounding %IF block.
            body = self._process_do_loops(body)
            body = self._process_macro_functions(body)
            body = self._process_eval(body)
            body = self._process_let_statements(body)
            body = self._process_conditionals(body)
            body = self._substitute_vars(body)
            body = self._process_put_statements(body)
            body = self._expand_macro_invocations(body)
            return self._apply_return_goto(body)
        finally:
            self._macro_scopes.pop()

    @staticmethod
    def _process_local_declarations(
        body: str,
        scope: dict[str, str | None],
    ) -> str:
        """Declare blank macro locals and remove their %LOCAL statements."""
        def declare(match: re.Match) -> str:
            for name in re.findall(r"[A-Za-z_]\w*", match.group(1)):
                # Macro parameters are already local and retain their values.
                # None means declared but not assigned.  It must shadow a
                # same-named outer/global value without resolving ``&name``
                # to an empty string: an executable step may assign it later.
                scope.setdefault(name.upper(), None)
            return ""

        return re.sub(
            r"%\s*LOCAL\s+([^;]*);",
            declare,
            body,
            flags=re.IGNORECASE,
        )

    def _process_let_statements(self, source: str) -> str:
        """Find and process %LET statements, return source without them."""
        def replacer(match: re.Match) -> str:
            var_name = match.group(1).upper()
            value = self._resolve_let_value(match.group(2).strip())
            sync_to_session = not self._macro_scopes
            sync_to_global_session_scope = False
            # Remove surrounding quotes if present
            if (value.startswith("'") and value.endswith("'")) or (
                value.startswith('"') and value.endswith('"')
            ):
                value = value[1:-1]
            if self._macro_scopes:
                target_scope = next(
                    (
                        scope
                        for scope in reversed(self._macro_scopes)
                        if var_name in scope
                    ),
                    None,
                )
                if target_scope is not None:
                    target_scope[var_name] = value
                elif var_name in self._global_vars:
                    self._global_vars[var_name] = value
                    sync_to_session = True
                    sync_to_global_session_scope = True
                else:
                    self._macro_scopes[-1][var_name] = value
            else:
                self._local_vars[var_name] = value
            if sync_to_session and self._session is not None:
                if sync_to_global_session_scope:
                    self._session.global_scope.define_var(var_name, value)
                else:
                    self._session.set_macro_var(var_name, value)
            self._log_symbolgen(var_name, value)
            return ""  # Remove the %LET statement

        # Macro execution is ordered.  In particular, a %LET in the false
        # branch of a later %IF must not run while scanning the surrounding
        # body.  Process only the portion before the next conditional; the
        # conditional engine removes the unselected branch and then calls us
        # again on the remaining source.
        masked = self._mask_quoted_text(source)
        conditional = re.search(r"%\s*IF\b", masked, flags=re.IGNORECASE)
        boundary = conditional.start() if conditional is not None else len(source)
        prefix = re.sub(
            r"%\s*LET\s+(\w+)\s*=\s*(.*?);",
            replacer,
            source[:boundary],
            flags=re.IGNORECASE,
        )
        return prefix + source[boundary:]

    def _resolve_let_value(self, value: str) -> str:
        """Resolve macro triggers on a %LET right-hand side in source order.

        Later %LET statements in the same macro can depend on values assigned
        by earlier statements, including a chain of %SYSFUNC calls.  Re-scan
        until stable, as the SAS macro processor does after each resolution.
        """
        for _ in range(30):
            resolved = self._process_macro_functions(value)
            resolved = self._process_eval(resolved)
            resolved = self._substitute_vars(resolved)
            if resolved == value:
                return resolved
            value = resolved
        return value

    def _process_global_declarations(self, source: str) -> str:
        """Declare persistent macro variables and remove %GLOBAL statements."""
        def declare(match: re.Match) -> str:
            for name in re.findall(r"[A-Za-z_]\w*", match.group(1)):
                self._global_vars.setdefault(name.upper(), "")
            return ""

        return re.sub(
            r"%\s*GLOBAL\s+([^;]*);",
            declare,
            source,
            flags=re.IGNORECASE,
        )

    def _substitute_vars(self, source: str) -> str:
        """Substitute &var references with their values.

        SAS semantics: a trailing dot after a macro variable reference is a
        delimiter and is consumed (`&lib..member` → `value.member`).
        """
        # Handle &&var (indirect reference) — resolve one level
        def _indirect(m: re.Match) -> str:
            val = self.get_var(m.group(1))
            if val is None:
                return m.group(0)
            self._log_symbolgen(m.group(1), val)
            return val + (m.group(2) or "")

        source = re.sub(r"&&(\w+)(\.)?", _indirect, source)

        # Handle &var with optional trailing-dot delimiter
        def _direct(m: re.Match) -> str:
            val = self.get_var(m.group(1))
            if val is None:
                return m.group(0)  # keep unresolved reference (incl. dot)
            self._log_symbolgen(m.group(1), val)
            return val

        source = re.sub(r"&(\w+)\.?", _direct, source)
        return source

    def _process_put_statements(self, source: str) -> str:
        """Process %PUT statements — write text to output log."""
        def replacer(match: re.Match) -> str:
            content = match.group(1).strip()
            # Handle special %PUT keywords
            if content.upper() == "_ALL_":
                # Output all macro variables
                lines = []
                for name, value in sorted(self._global_vars.items()):
                    lines.append(f"{name}={value}")
                for name, value in sorted(self._local_vars.items()):
                    lines.append(f"{name}={value}")
                output = "\n".join(lines)
            elif content.upper() == "_AUTOMATIC_":
                # Output automatic macro variables
                lines = []
                auto_vars = ["SYSDATE", "SYSDATE9", "SYSTIME", "SYSDAY", "SYSVER", "SYSERR", "SYSSCP"]
                for name in auto_vars:
                    if name in self._global_vars:
                        lines.append(f"{name}={self._global_vars[name]}")
                output = "\n".join(lines)
            elif content.upper() == "_USER_":
                # Output user-defined macro variables
                lines = []
                for name, value in sorted(self._local_vars.items()):
                    lines.append(f"{name}={value}")
                output = "\n".join(lines)
            else:
                # Substitute variables in the content
                output = self._substitute_vars(content)
                # Evaluate any %EVAL expressions
                output = self._process_eval(output)

            output = self._unquote_macro_value(output)
            self._put_output.append(output)
            if self._session:
                self._session.add_debug_output(f"PUT: {output}")
            return ""

        source = re.sub(
            r"%\s*PUT\s+(.*?);",
            replacer,
            source,
            flags=re.IGNORECASE,
        )
        return source

    def _process_do_loops(self, source: str) -> str:
        """Process %DO %var = %eval(start) %TO %eval(end) %BY step; ... %END; loops."""
        max_iterations = 50
        for _ in range(max_iterations):
            new_source = self._process_do_loops_once(source)
            if new_source == source:
                break
            source = new_source
        return source

    def _process_do_loops_once(self, source: str) -> str:
        """Expand the first iterative %DO using a balanced %DO/%END pair."""
        masked = self._mask_quoted_text(source)
        head = re.search(
            r"%\s*DO\s+(\w+)\s*=",
            masked,
            flags=re.IGNORECASE,
        )
        if head is None:
            return source

        header_end = masked.find(";", head.end())
        if header_end < 0:
            return source
        bounds = source[head.end():header_end]
        bounds_match = re.match(
            r"\s*(.*?)\s+%\s*TO\b(.*?)(?:\s+%\s*BY\b(.*))?\s*$",
            bounds,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if bounds_match is None:
            return source

        body_start = header_end + 1
        try:
            body_end, loop_end = self._find_matching_macro_end(masked, body_start)
        except SyntaxError:
            return source

        start_str = self._process_eval(
            self._substitute_vars(bounds_match.group(1).strip())
        )
        end_str = self._process_eval(
            self._substitute_vars(bounds_match.group(2).strip())
        )
        try:
            start = int(float(start_str))
            end = int(float(end_str))
        except (ValueError, TypeError):
            return source

        by = 1
        by_str = bounds_match.group(3)
        if by_str:
            by_str = self._process_eval(self._substitute_vars(by_str.strip()))
            try:
                by = int(float(by_str))
            except (ValueError, TypeError):
                by = 1
        if by == 0:
            by = 1

        body = source[body_start:body_end]
        result_parts: list[str] = []
        value = start
        while value <= end if by > 0 else value >= end:
            expanded_body = re.sub(
                rf"&{re.escape(head.group(1))}\b\.?",
                str(value),
                body,
                flags=re.IGNORECASE,
            )
            result_parts.append(expanded_body)
            value += by

        return source[:head.start()] + "".join(result_parts) + source[loop_end:]

    def expand_macro_fragment(self, source: str) -> str:
        """Expand a continuation known to originate inside an invoked macro.

        This differs from :meth:`expand` only in allowing macro control
        statements at the fragment boundary.  It is intentionally used by
        the interpreter's staged runtime, never for user open code.
        """
        # A previous invocation may have left a same-named value in the
        # session.  Within this fragment, an explicit runtime assignment must
        # happen before its later references resolve, so temporarily hide the
        # stale value while the fragment is structurally expanded.
        runtime_names = self._runtime_assigned_macro_names(source)
        missing = object()
        saved_local = {
            name: self._local_vars.pop(name, missing) for name in runtime_names
        }
        saved_global = {
            name: self._global_vars.pop(name, missing) for name in runtime_names
        }
        try:
            source = self._remove_comments(source)
            source = self._quote_format_literals(source)
            source = self._process_macro_definitions(source)
            source = self._process_macro_functions(source)
            source = self._process_do_loops(source)
            source = self._process_eval(source)
            source = self._process_global_declarations(source)
            source = self._process_let_statements(source)
            source = self._process_macro_functions(source)
            source = self._process_conditionals(source)
            source = self._process_put_statements(source)
            source = self._expand_macro_invocations(source)
            source = self._process_macro_functions(source)
            source = self._process_do_loops(source)
            source = self._process_eval(source)
            source = self._process_let_statements(source)
            source = self._process_conditionals(source)
            source = self._process_put_statements(source)
            source = self._substitute_vars(source)
            return self._unquote_macro_value(source)
        finally:
            for name, value in saved_local.items():
                if value is not missing and name not in self._local_vars:
                    self._local_vars[name] = value
            for name, value in saved_global.items():
                if value is not missing and name not in self._global_vars:
                    self._global_vars[name] = value

    @staticmethod
    def _runtime_assigned_macro_names(source: str) -> set[str]:
        """Collect runtime targets assigned before their first reference."""
        assignments: dict[str, int] = {}
        for match in re.finditer(
            r"\bCALL\s+SYMPUTX?\s*\(\s*(['\"])([A-Za-z_]\w*)\1\s*,",
            source,
            flags=re.IGNORECASE,
        ):
            name = match.group(2).upper()
            assignments[name] = min(assignments.get(name, match.start()), match.start())
        for into in re.finditer(
            r"\bINTO\b(.*?)\bFROM\b",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            for name in re.findall(r":\s*([A-Za-z_]\w*)", into.group(1)):
                key = name.upper()
                assignments[key] = min(
                    assignments.get(key, into.start()),
                    into.start(),
                )

        deferred: set[str] = set()
        for name, assignment_at in assignments.items():
            reference = re.search(
                rf"&{re.escape(name)}(?:\.|\b)",
                source,
                flags=re.IGNORECASE,
            )
            if reference is not None and assignment_at < reference.start():
                deferred.add(name)
        return deferred

    # ── Macro character functions & %SYSFUNC ──────────

    _MACRO_FUNC_NAMES = (
        "UPCASE", "LOWCASE", "SCAN", "SUBSTR", "LENGTH", "INDEX",
        "STR", "NRSTR", "SUPERQ", "SYMEXIST", "SYSFUNC",
    )

    def _process_macro_functions(self, source: str) -> str:
        """Expand %UPCASE/%LOWCASE/%SCAN/%SUBSTR/%LENGTH/%INDEX/%SYSFUNC.

        Uses a left-to-right scanner with balanced-paren matching. Calls whose
        arguments still contain a nested macro-function call are skipped in
        the current pass (the inner call is expanded first); the pass repeats
        until the source is stable.
        """
        names = "|".join(self._MACRO_FUNC_NAMES)
        head_re = re.compile(rf"%\s*({names})\s*\(", flags=re.IGNORECASE)

        for _ in range(30):
            new_source = self._expand_macro_functions_once(source, head_re)
            if new_source == source:
                break
            source = new_source
        return source

    def _expand_macro_functions_once(self, source: str, head_re: re.Pattern) -> str:
        result: list[str] = []
        pos = 0
        n = len(source)
        while pos < n:
            m = head_re.search(source, pos)
            if m is None:
                result.append(source[pos:])
                break
            func = m.group(1).upper()
            # Find the balanced closing paren
            depth = 1
            i = m.end()
            while i < n and depth > 0:
                if source[i] == "(":
                    depth += 1
                elif source[i] == ")":
                    depth -= 1
                i += 1
            if depth != 0:
                # Unbalanced — leave the rest untouched
                result.append(source[pos:])
                break
            raw_args = source[m.end():i - 1]
            if head_re.search(raw_args):
                # Nested macro function inside — expand inner first.
                # Emit up to (and including) the function head, then continue
                # scanning inside the args.
                result.append(source[pos:m.end()])
                pos = m.end()
                continue
            result.append(source[pos:m.start()])
            expanded = self._eval_macro_function(func, raw_args)
            if expanded is None:
                # Arguments not yet resolvable (unresolved &var) — keep as-is
                result.append(source[m.start():i])
            else:
                result.append(expanded)
            pos = i
        return "".join(result)

    def _eval_macro_function(self, func: str, raw_args: str) -> str | None:
        """Evaluate one macro character function call.

        Returns None when the arguments still contain unresolved &var
        references, so expansion can be retried after %LET processing.
        """
        if func == "SUPERQ":
            # SUPERQ takes a variable *name*, not an &reference, and masks
            # macro triggers in the returned value from further rescanning.
            name = raw_args.strip()
            value = self.get_var(name)
            if value is None:
                return ""
            return self._quote_macro_value(value)

        if func in ("STR", "NRSTR"):
            return (
                self._quote_macro_value(raw_args)
                if func == "NRSTR"
                else raw_args
            )

        if func == "SYMEXIST":
            return "1" if self.get_var(raw_args.strip()) is not None else "0"

        raw_args = self._substitute_vars(raw_args)
        if "&" in raw_args:
            return None

        if func == "SYSFUNC":
            return self._eval_sysfunc(raw_args)

        args = [a.strip() for a in raw_args.split(",")]
        text = args[0] if args else ""

        if func == "UPCASE":
            return text.upper()
        if func == "LOWCASE":
            return text.lower()
        if func == "LENGTH":
            return str(len(text))
        if func == "INDEX":
            target = args[1] if len(args) > 1 else ""
            return str(text.find(target) + 1)
        if func == "SCAN":
            n = 1
            if len(args) > 1:
                try:
                    n = int(float(args[1]))
                except ValueError:
                    n = 1
            delims = args[2] if len(args) > 2 and args[2] else " \t\n\r.-/,;:!?()[]{}"
            words = [w for w in re.split(f"[{re.escape(delims)}]+", text) if w]
            if n < 0:
                n = len(words) + n + 1
            if 1 <= n <= len(words):
                return words[n - 1]
            return ""
        if func == "SUBSTR":
            try:
                start = int(float(args[1])) if len(args) > 1 else 1
            except ValueError:
                start = 1
            length = None
            if len(args) > 2 and args[2]:
                try:
                    length = int(float(args[2]))
                except ValueError:
                    length = None
            start_idx = max(start - 1, 0)
            if length is None:
                return text[start_idx:]
            return text[start_idx:start_idx + length]
        return ""

    @classmethod
    def _quote_macro_value(cls, value: str) -> str:
        return str(value).replace("&", cls._QUOTED_AMPERSAND).replace(
            "%",
            cls._QUOTED_PERCENT,
        )

    @classmethod
    def _unquote_macro_value(cls, value: str) -> str:
        return str(value).replace(cls._QUOTED_AMPERSAND, "&").replace(
            cls._QUOTED_PERCENT,
            "%",
        )

    _sysfunc_registry = None

    def _eval_sysfunc(self, raw_args: str) -> str:
        """Evaluate %SYSFUNC(func(args) [, format])."""
        m = re.match(r"\s*(\w+)\s*\((.*)\)\s*(?:,\s*[\w.$]+\s*)?$", raw_args, flags=re.DOTALL)
        if m is None:
            # Function with no parens: %SYSFUNC(today())  handled above;
            # %SYSFUNC(today) style:
            m2 = re.match(r"\s*(\w+)\s*$", raw_args)
            if m2 is None:
                return ""
            fn_name, inner = m2.group(1), ""
        else:
            fn_name, inner = m.group(1), m.group(2)

        if MacroExpander._sysfunc_registry is None:
            from saslite.functions import build_default_registry
            MacroExpander._sysfunc_registry = build_default_registry()
        reg = MacroExpander._sysfunc_registry

        args: list[Any] = []
        if inner.strip():
            for part in self._split_args_depth0(inner):
                part = part.strip()
                if (len(part) >= 2 and part[0] in ("'", '"') and part[-1] == part[0]):
                    args.append(part[1:-1])
                    continue
                try:
                    num = float(part)
                    args.append(int(num) if num.is_integer() else num)
                except ValueError:
                    args.append(part)

        try:
            metadata_fn = getattr(
                self,
                f"_sysfunc_{fn_name.lower()}",
                None,
            )
            if metadata_fn is not None:
                result = metadata_fn(*args)
            else:
                result = reg.call(fn_name, args)
        except NameError:
            raise
        except Exception:
            return ""
        if result is None:
            return ""
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        return str(result)

    # ── Dataset metadata functions ────────────────────

    def _sysfunc_exist(self, dataset_name: Any, member_type: Any = "DATA") -> int:
        """Return one when a session dataset exists, otherwise zero."""
        if self._session is None:
            return 0
        requested_type = str(member_type).strip().strip("'\"").upper()
        if requested_type not in {"", "DATA", "ANY"}:
            # SASLite does not currently model catalog entries or views.
            return 0
        reference = self._split_dataset_reference(dataset_name)
        if reference is None:
            return 0
        libref, member = reference
        try:
            return int(self._session.dataset_exists(libref, member))
        except (KeyError, OSError, ValueError):
            return 0

    def _sysfunc_open(self, dataset_name: Any, mode: Any = "I") -> int:
        """OPEN a session dataset and return a stable, positive handle.

        SAS accepts a one-level member name as WORK.member and a two-level
        name as libref.member.  Access modes are currently read-only from the
        macro system's perspective, but are accepted for source compatibility.
        """
        del mode
        if self._session is None:
            return 0

        reference = self._split_dataset_reference(dataset_name)
        if reference is None:
            return 0
        libref, member = reference
        try:
            dataset = self._session.get_dataset(libref, member)
        except (KeyError, OSError, ValueError):
            return 0

        handle = self._next_dataset_handle
        self._next_dataset_handle += 1
        self._dataset_handles[handle] = dataset
        return handle

    @staticmethod
    def _split_dataset_reference(dataset_name: Any) -> tuple[str, str] | None:
        reference = str(dataset_name).strip().strip("'\"")
        # Metadata functions address the member itself when dataset options
        # such as WHERE= or KEEP= are present.
        reference = reference.split("(", 1)[0].strip()
        if not reference:
            return None
        if "." in reference:
            libref, member = reference.split(".", 1)
        else:
            libref, member = "WORK", reference
        if not libref.strip() or not member.strip():
            return None
        return libref.strip(), member.strip()

    def _sysfunc_close(self, handle: Any) -> int:
        """CLOSE a dataset handle; zero denotes success as in SAS."""
        handle_number = self._coerce_handle(handle)
        if handle_number is None or handle_number not in self._dataset_handles:
            return 1
        del self._dataset_handles[handle_number]
        return 0

    def _sysfunc_varnum(self, handle: Any, variable_name: Any) -> int:
        dataset = self._dataset_for_handle(handle)
        if dataset is None:
            return 0
        wanted = str(variable_name).strip().strip("'\"").upper()
        for number, column_name in enumerate(dataset.columns, start=1):
            if str(column_name).upper() == wanted:
                return number
        return 0

    def _sysfunc_varname(self, handle: Any, variable_number: Any) -> str:
        dataset = self._dataset_for_handle(handle)
        number = self._coerce_positive_int(variable_number)
        if dataset is None or number is None or number > len(dataset.columns):
            return ""
        return str(dataset.columns[number - 1])

    def _sysfunc_vartype(self, handle: Any, variable_number: Any) -> str:
        dataset = self._dataset_for_handle(handle)
        variable = self._variable_for_number(dataset, variable_number)
        if variable is None:
            return ""
        return "C" if variable.dtype == "character" else "N"

    def _sysfunc_varlabel(self, handle: Any, variable_number: Any) -> str:
        dataset = self._dataset_for_handle(handle)
        variable = self._variable_for_number(dataset, variable_number)
        if variable is None:
            return ""
        return variable.label or ""

    def _sysfunc_attrn(self, handle: Any, attribute_name: Any) -> int | str:
        dataset = self._dataset_for_handle(handle)
        if dataset is None:
            return ""
        attribute = str(attribute_name).strip().strip("'\"").upper()
        if attribute in {"NOBS", "NLOBS", "NLOBSF"}:
            return dataset.nrow
        if attribute == "NVARS":
            return dataset.ncol
        return ""

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _coerce_handle(self, value: Any) -> int | None:
        return self._coerce_positive_int(value)

    def _dataset_for_handle(self, handle: Any) -> Any | None:
        handle_number = self._coerce_handle(handle)
        if handle_number is None:
            return None
        return self._dataset_handles.get(handle_number)

    @staticmethod
    def _variable_for_number(dataset: Any | None, variable_number: Any) -> Any | None:
        if dataset is None:
            return None
        try:
            number = int(float(variable_number))
        except (TypeError, ValueError):
            return None
        if number < 1 or number > len(dataset.columns):
            return None
        column_name = str(dataset.columns[number - 1])
        variable = dataset.metadata.get_variable(column_name)
        if variable is not None:
            return variable
        # A backend may not retain complete metadata.  Preserve useful SAS
        # behavior by inferring type for that individual column.
        from saslite.runtime.metadata import make_variable
        from saslite.runtime.dataset import _infer_sas_dtype
        return make_variable(
            column_name,
            dtype=_infer_sas_dtype(dataset.data[column_name]),
        )

    @staticmethod
    def _split_args_depth0(inner: str) -> list[str]:
        """Split a comma-separated arg string at parenthesis depth 0."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in inner:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current))
        return parts

    def _process_eval(self, source: str) -> str:
        """Process %EVAL() and %SYSEVALF() expressions."""
        def eval_replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            expr = self._substitute_vars(expr)
            return str(self._eval_macro_expr(expr))

        # %SYSEVALF(expr) — floating-point arithmetic
        def sysevalf_replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            expr = self._substitute_vars(expr)
            return str(self._eval_macro_expr(expr, floating=True))

        source = re.sub(
            r"%\s*EVAL\s*\(([^)]+)\)",
            eval_replacer,
            source,
            flags=re.IGNORECASE,
        )
        source = re.sub(
            r"%\s*SYSEVALF\s*\(([^)]+)\)",
            sysevalf_replacer,
            source,
            flags=re.IGNORECASE,
        )
        return source

    @staticmethod
    def _eval_macro_expr(expr: str, floating: bool = False) -> int | float:
        """Evaluate a macro-level arithmetic/comparison expression."""
        expr = expr.strip()
        # Try direct number
        try:
            return float(expr) if floating else int(float(expr))
        except (ValueError, TypeError):
            pass

        # Comparison operators (lowest precedence) — return 1/0
        comp_ops: list[tuple[str, Any]] = [
            (">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b),
            ("=", lambda a, b: a == b), (">", lambda a, b: a > b),
            ("<", lambda a, b: a < b),
        ]
        mnemonic_ops: list[tuple[str, Any]] = [
            ("NE", lambda a, b: a != b), ("GE", lambda a, b: a >= b),
            ("LE", lambda a, b: a <= b), ("GT", lambda a, b: a > b),
            ("LT", lambda a, b: a < b), ("EQ", lambda a, b: a == b),
        ]

        def _operand(s: str) -> Any:
            s = s.strip()
            try:
                val = MacroExpander._eval_macro_expr(s, floating=True)
                # _eval_macro_expr returns 0 for unknown text — but for
                # comparisons we want string semantics there. Distinguish:
                # if s parses as expr containing digits/operators, trust it.
                if re.search(r"\d", s) or any(op in s for op in "+-*/()"):
                    return val
            except Exception:
                pass
            return s.strip("'\"")

        # Mnemonic operators need word boundaries
        for op_word, op_fn in mnemonic_ops:
            m = re.search(rf"\b{op_word}\b", expr, flags=re.IGNORECASE)
            if m:
                left = _operand(expr[:m.start()])
                right = _operand(expr[m.end():])
                try:
                    return 1 if op_fn(float(left), float(right)) else 0
                except (TypeError, ValueError):
                    return 1 if op_fn(str(left), str(right)) else 0

        # Symbolic comparison operators at depth 0
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif depth == 0:
                for op_sym, op_fn in comp_ops:
                    if expr[i:i + len(op_sym)] == op_sym:
                        # Skip ** which is not comparison; = is unambiguous
                        left = _operand(expr[:i])
                        right = _operand(expr[i + len(op_sym):])
                        try:
                            return 1 if op_fn(float(left), float(right)) else 0
                        except (TypeError, ValueError):
                            return 1 if op_fn(str(left), str(right)) else 0

        # Handle common arithmetic operators
        ops = [("+", lambda a, b: a + b), ("-", lambda a, b: a - b),
               ("*", lambda a, b: a * b), ("/", lambda a, b: a / b if b != 0 else 0)]

        for op_sym, op_fn in ops:
            # Find the operator (respecting parentheses depth)
            depth = 0
            split_pos = -1
            for i, ch in enumerate(expr):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif depth == 0 and ch == op_sym and i > 0:
                    split_pos = i
                    break  # Take the first occurrence at depth 0
            if split_pos > 0:
                left = MacroExpander._eval_macro_expr(expr[:split_pos], floating)
                right = MacroExpander._eval_macro_expr(expr[split_pos + 1:], floating)
                return op_fn(left, right)

        # Handle parentheses
        if expr.startswith("(") and expr.endswith(")"):
            return MacroExpander._eval_macro_expr(expr[1:-1], floating)

        # Unknown expression — return 0
        return 0
