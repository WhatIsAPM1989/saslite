"""Program parser — uses Lark with combined grammar."""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from lark import Lark

from saslite.ast.program import ProgramNode
from saslite.parser.transformer import SasTransformer

_GRAMMAR_PATH = Path(__file__).parent / "grammar" / "saslite.lark"


class ProgramParser:
    """Parses expanded SAS source into an AST."""

    def __init__(self) -> None:
        grammar_text = _GRAMMAR_PATH.read_text(encoding="utf-8")
        self._parser = Lark(
            grammar_text,
            parser="earley",
            ambiguity="resolve",
            start="start",
            keep_all_tokens=True,
            propagate_positions=True,
        )
        self._transformer = SasTransformer()

    def parse(
        self,
        source: str,
        *,
        source_name: str = "",
        original_source: str | None = None,
    ) -> ProgramNode:
        """Parse source text into a ProgramNode AST."""
        line_map = self._build_line_map(original_source, source)
        file_source = (
            source_name
            if source_name and not source_name.startswith("<")
            else ""
        )
        self._transformer.set_source_context(
            source_name=file_source,
            line_map=line_map,
        )
        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            line = getattr(exc, "line", 0)
            if original_source is not None:
                line = line_map.get(line, 0)
            column = getattr(exc, "column", 1) or 1
            if file_source and line:
                setattr(
                    exc,
                    "saslite_source_location",
                    f"{file_source}:{line}:{column}",
                )
            raise
        result = self._transformer.transform(tree)
        if isinstance(result, ProgramNode):
            return result
        return ProgramNode(steps=[result] if result else [])

    @staticmethod
    def _build_line_map(
        original_source: str | None,
        transformed_source: str,
    ) -> dict[int, int]:
        """Map transformed 1-based lines back to matching original lines."""
        if original_source is None:
            return {}

        original = [line.strip() for line in original_source.splitlines()]
        transformed = [line.strip() for line in transformed_source.splitlines()]
        matcher = SequenceMatcher(None, original, transformed, autojunk=False)
        line_map: dict[int, int] = {}
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                line_map[block.b + offset + 1] = block.a + offset + 1
        return line_map

    def parse_expression(self, text: str) -> object:
        """Parse a single expression."""
        # Wrap in DATA step context for proper parsing
        wrapped = f"DATA _NULL_; x = {text}; RUN;"
        program = self.parse(wrapped)
        if program.steps and hasattr(program.steps[0], "statements"):
            for stmt in program.steps[0].statements:
                if hasattr(stmt, "expr"):
                    return stmt.expr
        return None
