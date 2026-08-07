"""Helpers for finding schema-dependent variable references."""

from __future__ import annotations

from typing import Any

from saslite.ast.expressions import (
    ArrayRefNode,
    BetweenNode,
    BinaryOpNode,
    CalculatedNode,
    CaseNode,
    ExistsNode,
    FunctionCallNode,
    InListNode,
    LikeNode,
    LiteralNode,
    ScalarSubqueryNode,
    SubqueryNode,
    UnaryOpNode,
    VariableNode,
    WindowFuncNode,
)


def referenced_variables(expression: Any) -> set[str]:
    """Return source-variable names referenced by an expression AST.

    Subqueries and CALCULATED references belong to a different schema scope,
    so callers validate those while executing that scope instead.
    """
    if expression is None or isinstance(expression, LiteralNode):
        return set()
    if isinstance(expression, VariableNode):
        name = expression.name
        if name == "*" or name.endswith(".*") or name.startswith("__"):
            return set()
        return {name}
    if isinstance(expression, (CalculatedNode, ExistsNode, ScalarSubqueryNode, SubqueryNode)):
        return set()
    if isinstance(expression, BinaryOpNode):
        return referenced_variables(expression.left) | referenced_variables(expression.right)
    if isinstance(expression, UnaryOpNode):
        return referenced_variables(expression.operand)
    if isinstance(expression, FunctionCallNode):
        return set().union(*(referenced_variables(arg) for arg in expression.args))
    if isinstance(expression, InListNode):
        return referenced_variables(expression.expr) | set().union(
            *(referenced_variables(value) for value in expression.values)
        )
    if isinstance(expression, BetweenNode):
        return (
            referenced_variables(expression.expr)
            | referenced_variables(expression.low)
            | referenced_variables(expression.high)
        )
    if isinstance(expression, LikeNode):
        return referenced_variables(expression.expr) | referenced_variables(expression.pattern)
    if isinstance(expression, CaseNode):
        expressions = [
            *expression.conditions,
            *expression.results,
            expression.else_result,
        ]
        return set().union(*(referenced_variables(item) for item in expressions))
    if isinstance(expression, ArrayRefNode):
        return referenced_variables(expression.index)
    if isinstance(expression, WindowFuncNode):
        names = set().union(*(referenced_variables(arg) for arg in expression.args))
        names.update(str(name) for name in expression.partition_by)
        names.update(str(name) for name, _ascending in expression.order_by)
        return names
    return set()
