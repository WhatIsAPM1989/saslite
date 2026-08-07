"""DATA step executor — implements the SAS implicit loop and PDV model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandas as pd

from saslite.ast.data_step import (
    DataStepNode, SetNode, AssignNode, IfNode, DoNode,
    OutputNode, DeleteNode, StopNode, RetainNode, WhereNode,
    KeepNode, DropNode, RenameNode, DatasetRefNode,
    FormatNode, FormatResetNode, InformatResetNode, LabelNode, MergeNode,
    ArrayNode, InputNode, InfileNode,
    SubstrAssignNode, PutNode, UpdateDataNode, CallSymputNode,
    CallMissingNode, ArrayAssignNode, SumStatementNode, LengthNode, AttribNode,
)
from saslite.ast.expressions import ArrayRefNode, VariableNode
from saslite.ast.proc import ByNode
from saslite.runtime.pdv import PDV
from saslite.runtime.dataset import Dataset
from saslite.runtime.metadata import make_variable
from saslite.runtime.execution_result import StepResult
from saslite.runtime.types import is_missing, sas_bool
from saslite.executor.expression_eval import ExpressionEvaluator
from saslite.session.session import Session
from saslite.diagnostics.reporter import Reporter
from saslite.functions import build_default_registry


class LagState:
    """Stateful LAG/DIF buffers for DATA step."""

    def __init__(self) -> None:
        self._buffers: dict[int, list] = {}  # key: n, value: [prev1, prev2, ...]

    def lag(self, value: Any, n: int = 1) -> Any:
        """LAGn(value) — return value from n observations ago."""
        buf = self._buffers.setdefault(n, [])
        # Return oldest value in buffer (observation from n rows ago)
        if len(buf) >= n:
            result = buf.pop(0)
        else:
            result = float("nan")
        # Push current value to end of buffer
        buf.append(value)
        return result

    def dif(self, value: Any, n: int = 1) -> Any:
        """DIFn(value) — return value minus value from n observations ago."""
        prev = self.lag(value, n)
        if is_missing(prev) or is_missing(value):
            return float("nan")
        try:
            return value - prev
        except TypeError:
            return float("nan")


_SENTINEL = object()


class DataStepExecutor:
    """Executes a DATA step."""

    def __init__(self, session: Session, reporter: Reporter) -> None:
        self.session = session
        self.reporter = reporter
        self._fn_registry = build_default_registry()

    def run(self, step: DataStepNode) -> StepResult:
        """Execute the DATA step."""
        target_full = step.target.upper()
        if target_full == "_NULL_":
            target_full = ""
            target_libref = "WORK"
            target_name = ""
        elif "." in target_full:
            parts = target_full.split(".", 1)
            target_libref = parts[0]
            target_name = parts[1]
        else:
            target_libref = "WORK"
            target_name = target_full
        target = target_name

        try:
            # Collect input datasets from SET or MERGE statements
            input_datasets: list[Dataset] = []
            input_ds_names: list[str] = []
            merge_nodes = [s for s in step.statements if isinstance(s, MergeNode)]
            set_nodes = [s for s in step.statements if isinstance(s, SetNode)]
            input_nodes = [s for s in step.statements if isinstance(s, InputNode)]
            set_length_warnings: list[str] = []
            in_flag_names: set[str] = set()

            if input_nodes and input_nodes[0].datalines_data:
                # INPUT + DATALINES mode: parse rows into an in-memory dataset and
                # run them through the SAME implicit-loop machinery used by SET, so
                # assignments / subsetting IF / DELETE / OUTPUT / RETAIN / DO execute.
                dl_ds = self._build_datalines_dataset(step, input_nodes[0])
                input_datasets.append(dl_ds)
                input_ds_names.append("WORK.DATALINES")

            if merge_nodes:
                # MERGE mode
                merge_node = merge_nodes[0]
                for ds_ref in merge_node.datasets:
                    ds_name = self._resolve_ds_name(ds_ref)
                    try:
                        ds = self.session.get_dataset(ds_ref.libref, ds_ref.name)
                        ds = self._apply_dataset_options(ds, ds_ref.options)
                        in_flag = self._dataset_in_flag(ds_ref)
                        if in_flag:
                            ds = self._add_in_flag(ds, in_flag)
                            in_flag_names.add(in_flag)
                        input_datasets.append(ds)
                        input_ds_names.append(ds_name)
                    except KeyError:
                        return StepResult(
                            success=False,
                            error=f"Dataset {ds_name} does not exist",
                        )

                # Get BY variables if present
                by_vars: list[str] = []
                for stmt in step.statements:
                    if isinstance(stmt, ByNode):
                        by_vars = [v.upper() for v in stmt.variables]
                        break

                return self._execute_merge(step, input_datasets, by_vars,
                                           target_name, target_libref,
                                           in_flag_names)

            elif set_nodes:
                # Track per-SET-statement dataset groups: one SET statement
                # with N datasets = vertical stacking; multiple SET statements
                # = parallel reading (each statement advances its own pointer).
                set_groups: list[list[Dataset]] = []
                for set_node in set_nodes:
                    group: list[Dataset] = []
                    for ds_ref in set_node.datasets:
                        ds_name = self._resolve_ds_name(ds_ref)
                        try:
                            ds = self.session.get_dataset(ds_ref.libref, ds_ref.name)
                            ds = self._apply_dataset_options(ds, ds_ref.options)
                            in_flag = self._dataset_in_flag(ds_ref)
                            if in_flag:
                                ds = self._add_in_flag(ds, in_flag)
                                in_flag_names.add(in_flag)
                            input_datasets.append(ds)
                            input_ds_names.append(ds_name)
                            group.append(ds)
                        except KeyError:
                            return StepResult(
                                success=False,
                                error=f"Dataset {ds_name} does not exist",
                            )
                    set_groups.append(group)

                set_length_warnings = self._set_length_warnings(set_groups)

            # Build PDV
            pdv = self._build_pdv(step, input_datasets)

            # Detect BY variables for FIRST./LAST. tracking
            by_vars: list[str] = []
            for stmt in step.statements:
                if isinstance(stmt, ByNode):
                    by_vars = [v.upper() for v in stmt.variables]
                    break
            if by_vars:
                pdv.set_by_vars(by_vars)

            # Create LAG/DIF state
            lag_state = LagState()

            # Create evaluator
            eval_ctx = DataStepContext(pdv, self._fn_registry, self.session, lag_state)

            # Check if there's any explicit OUTPUT statement (including nested in DO blocks)
            has_explicit_output = self._has_explicit_output(step.statements)

            # Extract WHERE condition for pre-filtering
            where_condition = None
            for stmt in step.statements:
                if isinstance(stmt, WhereNode):
                    where_condition = stmt.condition
                    break

            # Collect FORMAT/LABEL metadata
            format_items: list[tuple[str, str]] = []
            label_items: list[tuple[str, str]] = []
            for stmt in step.statements:
                if isinstance(stmt, FormatNode):
                    format_items.extend(stmt.items)
                elif isinstance(stmt, LabelNode):
                    label_items.extend(stmt.items)

            if not input_datasets:
                # No SET — execute body once
                pdv.increment_n()
                pdv.reset_for_iteration()
                self._execute_statements(step.statements, eval_ctx)
                if not pdv.delete_flag and not pdv.stop_flag:
                    if not has_explicit_output:
                        # Implicit OUTPUT
                        eval_ctx.output_rows.append(pdv.snapshot_output_row())
            else:
                # Implicit loop over input rows — combine ALL SET datasets:
                # vertical stacking, or BY-interleave when a BY statement is
                # present, or parallel reading for multiple SET statements.
                if set_nodes and len(set_nodes) > 1:
                    combined_df = self._combine_parallel_sets(set_groups, by_vars)
                else:
                    combined_df = self._combine_inputs(input_datasets, by_vars)
                total_rows = len(combined_df)
                for i in range(total_rows):
                    pdv.increment_n()
                    pdv.reset_for_iteration()

                    # Load row from combined input
                    row = combined_df.iloc[i].to_dict()
                    pdv.load_row(row)

                    # Update FIRST./LAST. flags
                    if by_vars:
                        next_row = None
                        if i + 1 < total_rows:
                            next_row = combined_df.iloc[i + 1].to_dict()
                        pdv.update_by_flags(next_row)

                    # Apply WHERE pre-filter
                    if where_condition:
                        try:
                            where_eval = ExpressionEvaluator(var_getter=pdv.get)
                            for name in self._fn_registry.names:
                                fn = self._fn_registry.get(name)
                                if fn:
                                    where_eval.register_function(name, fn)
                            if not sas_bool(where_eval.evaluate(where_condition)):
                                continue
                        except Exception:
                            continue

                    # Execute statements
                    self._execute_statements(step.statements, eval_ctx)

                    if pdv.stop_flag:
                        break
                    if not pdv.delete_flag and not has_explicit_output:
                        # Implicit OUTPUT
                        eval_ctx.output_rows.append(pdv.snapshot_output_row())

            return self._store_declared_outputs(
                step,
                eval_ctx,
                pdv,
                input_datasets,
                in_flag_names,
                [
                    *set_length_warnings,
                    *pdv.character_length_warnings(),
                    *pdv.runtime_warnings(),
                ],
            )

        except Exception as e:
            return StepResult(success=False, error=str(e))

    def _build_pdv(self, step: DataStepNode, inputs: list[Dataset]) -> PDV:
        """Build PDV from input datasets and DATA step statements."""
        pdv = PDV(
            character_encoding=str(self.session.get_option("ENCODING", "utf-8")),
        )

        # Add variables from input datasets
        for ds in inputs:
            for logical_name, var_meta in ds.metadata.variables.items():
                if logical_name not in pdv.variables:
                    pdv.add_variable(logical_name, deepcopy(var_meta))
                pdv.mark_produced(logical_name)

        # Compile declarative statements into the PDV even when the step has
        # no input observations. This is what gives zero-row output data sets
        # their schema and variable attributes.
        for stmt in step.statements:
            if isinstance(stmt, LengthNode):
                for name, length in stmt.items:
                    dtype = (
                        "character"
                        if name.upper() in stmt.character_variables
                        else "numeric"
                    )
                    variable = pdv.ensure_variable(name, dtype=dtype)
                    if length is not None:
                        variable.metadata.length = length
            elif isinstance(stmt, FormatNode):
                for name, format_name in stmt.items:
                    dtype = "character" if str(format_name).startswith("$") else "numeric"
                    variable = pdv.ensure_variable(name, dtype=dtype)
                    variable.metadata.format = format_name
            elif isinstance(stmt, LabelNode):
                for name, label in stmt.items:
                    variable = pdv.ensure_variable(name)
                    variable.metadata.label = label
            elif isinstance(stmt, AttribNode):
                for name, attribute, value in stmt.items:
                    dtype = (
                        "character"
                        if attribute in ("FORMAT", "INFORMAT")
                        and str(value).startswith("$")
                        else "numeric"
                    )
                    variable = pdv.ensure_variable(name, dtype=dtype)
                    if attribute == "FORMAT":
                        variable.metadata.format = value
                    elif attribute == "INFORMAT":
                        variable.metadata.informat = value
                    elif attribute == "LABEL":
                        variable.metadata.label = value
                    elif attribute == "LENGTH":
                        try:
                            variable.metadata.length = int(value)
                        except (TypeError, ValueError):
                            pass
            elif isinstance(stmt, FormatResetNode):
                for variable in pdv.variables.values():
                    variable.metadata.format = None
            elif isinstance(stmt, InformatResetNode):
                for variable in pdv.variables.values():
                    variable.metadata.informat = None

        # SAS decides whether a variable is uninitialized from the compiled
        # DATA step, not from the branch taken by an individual observation.
        # Record every executable source before the implicit loop starts.
        self._mark_produced_variables(step.statements, pdv)

        # Process RETAIN statements
        for stmt in step.statements:
            if isinstance(stmt, RetainNode):
                for name, init_val in stmt.items:
                    key = name.upper()
                    # Ensure variable exists (it may be created later via assignment)
                    if key not in pdv.variables:
                        pdv.ensure_variable(name)
                    pdv.variables[key].retained = True
                    if init_val is not None:
                        val = ExpressionEvaluator(pdv.get).evaluate(init_val)
                        pdv.set(name, val)
                        pdv.mark_produced(name)

        return pdv

    def _mark_produced_variables(self, statements: list[Any], pdv: PDV) -> None:
        """Record variables that an executable statement can initialize."""
        for stmt in statements:
            if isinstance(stmt, (AssignNode, SumStatementNode, SubstrAssignNode)):
                pdv.mark_produced(stmt.target)
            elif isinstance(stmt, DoNode):
                if stmt.var:
                    pdv.mark_produced(stmt.var)
                self._mark_produced_variables(stmt.body, pdv)
            elif isinstance(stmt, IfNode):
                if stmt.then_stmt is not None:
                    self._mark_produced_variables([stmt.then_stmt], pdv)
                if stmt.else_stmt is not None:
                    self._mark_produced_variables([stmt.else_stmt], pdv)
            elif isinstance(stmt, CallMissingNode):
                for variable in stmt.variables:
                    if isinstance(variable, VariableNode):
                        pdv.mark_produced(variable.name)
            elif isinstance(stmt, InputNode):
                for name in stmt.variables:
                    pdv.mark_produced(name)
            elif isinstance(stmt, ArrayNode) and stmt.initial_values:
                for name in stmt.variables[:len(stmt.initial_values)]:
                    pdv.mark_produced(name)

    @staticmethod
    def _set_length_warnings(set_groups: list[list[Dataset]]) -> list[str]:
        """Return SAS-style warnings for conflicting SET variable lengths."""
        lengths_by_variable: dict[str, set[int]] = {}
        display_names: dict[str, str] = {}

        for group in set_groups:
            for ds in group:
                for column in ds.data.columns:
                    var_meta = ds.metadata.get_variable(str(column))
                    if var_meta is None:
                        continue
                    logical_name = var_meta.logical_name
                    if var_meta.length is None:
                        continue
                    lengths_by_variable.setdefault(logical_name, set()).add(var_meta.length)
                    display_names.setdefault(logical_name, var_meta.name)

        return [
            (
                f"Multiple lengths were specified for the variable "
                f"{display_names[logical_name]} by input data set(s). "
                f"Different lengths: {', '.join(str(length) for length in sorted(lengths))}. "
                "This can cause truncation of data."
            )
            for logical_name, lengths in lengths_by_variable.items()
            if len(lengths) > 1
        ]

    def _has_explicit_output(self, statements: list[Any]) -> bool:
        """Recursively check for explicit OUTPUT statements."""
        for stmt in statements:
            if isinstance(stmt, OutputNode):
                return True
            if isinstance(stmt, DoNode):
                if self._has_explicit_output(stmt.body):
                    return True
            if isinstance(stmt, IfNode):
                if stmt.then_stmt and self._has_explicit_output([stmt.then_stmt]):
                    return True
                if stmt.else_stmt and self._has_explicit_output([stmt.else_stmt]):
                    return True
        return False

    def _execute_statements(self, statements: list[Any], ctx: DataStepContext) -> None:
        """Execute all statements in the DATA step body."""
        for stmt in statements:
            if isinstance(stmt, SetNode):
                continue  # Already handled

            if isinstance(stmt, AssignNode):
                val = ctx.evaluator.evaluate(stmt.expr)
                ctx.pdv.set(stmt.target, val)

            elif isinstance(stmt, ArrayAssignNode):
                self._execute_array_assign(stmt, ctx)

            elif isinstance(stmt, SumStatementNode):
                self._execute_sum_stmt(stmt, ctx)

            elif isinstance(stmt, SubstrAssignNode):
                self._execute_substr_assign(stmt, ctx)

            elif isinstance(stmt, IfNode):
                cond = ctx.evaluator.evaluate(stmt.condition)
                if sas_bool(cond):
                    if stmt.then_stmt:
                        self._execute_single(stmt.then_stmt, ctx)
                else:
                    if stmt.else_stmt:
                        self._execute_single(stmt.else_stmt, ctx)
                    elif stmt.then_stmt is None and stmt.else_stmt is None:
                        # Subsetting IF: condition false → delete row
                        ctx.pdv.delete_flag = True

            elif isinstance(stmt, DoNode):
                self._execute_do(stmt, ctx)

            elif isinstance(stmt, OutputNode):
                self._do_output(stmt, ctx)

            elif isinstance(stmt, DeleteNode):
                ctx.pdv.delete_flag = True

            elif isinstance(stmt, StopNode):
                ctx.pdv.stop_flag = True

            elif isinstance(stmt, PutNode):
                self._execute_put(stmt, ctx)

            elif isinstance(stmt, CallSymputNode):
                self._execute_call_symput(stmt, ctx)

            elif isinstance(stmt, CallMissingNode):
                self._execute_call_missing(stmt, ctx)

            elif isinstance(stmt, UpdateDataNode):
                self._execute_data_update(stmt, ctx)

            elif isinstance(stmt, (RetainNode, KeepNode, DropNode, RenameNode, MergeNode, ByNode, InputNode, InfileNode)):
                pass  # Handled in build_pdv, merge, or post-processing

            elif isinstance(stmt, ArrayNode):
                self._register_array(stmt, ctx)

            elif isinstance(stmt, WhereNode):
                # WHERE filters are applied during iteration
                pass

            elif isinstance(stmt, (
                FormatNode, FormatResetNode, InformatResetNode,
                LabelNode, LengthNode, AttribNode,
            )):
                pass  # Metadata-only or applied during build_pdv

    def _execute_single(self, stmt: Any, ctx: DataStepContext) -> None:
        """Execute a single statement."""
        if isinstance(stmt, AssignNode):
            val = ctx.evaluator.evaluate(stmt.expr)
            ctx.pdv.set(stmt.target, val)
        elif isinstance(stmt, ArrayAssignNode):
            self._execute_array_assign(stmt, ctx)
        elif isinstance(stmt, SumStatementNode):
            self._execute_sum_stmt(stmt, ctx)
        elif isinstance(stmt, SubstrAssignNode):
            self._execute_substr_assign(stmt, ctx)
        elif isinstance(stmt, IfNode):
            self._execute_statements([stmt], ctx)
        elif isinstance(stmt, DoNode):
            self._execute_do(stmt, ctx)
        elif isinstance(stmt, OutputNode):
            self._do_output(stmt, ctx)
        elif isinstance(stmt, DeleteNode):
            ctx.pdv.delete_flag = True
        elif isinstance(stmt, StopNode):
            ctx.pdv.stop_flag = True
        elif isinstance(stmt, PutNode):
            self._execute_put(stmt, ctx)
        elif isinstance(stmt, CallSymputNode):
            self._execute_call_symput(stmt, ctx)
        elif isinstance(stmt, CallMissingNode):
            self._execute_call_missing(stmt, ctx)

    def _do_output(self, stmt: OutputNode, ctx: DataStepContext) -> None:
        """Execute OUTPUT [dataset] — route the row to the right target."""
        row = ctx.pdv.snapshot_output_row()
        target = (stmt.target or "").upper()
        if target:
            ctx.target_rows.setdefault(target, []).append(row)
        else:
            ctx.output_rows.append(row)

    def _execute_do(self, stmt: DoNode, ctx: DataStepContext) -> None:
        """Execute a DO block."""
        if stmt.var and stmt.start is not None and stmt.end is not None:
            # Iterative DO loop
            start = int(ctx.evaluator.evaluate(stmt.start))
            end = int(ctx.evaluator.evaluate(stmt.end))
            by = 1
            if stmt.by:
                by = int(ctx.evaluator.evaluate(stmt.by))
            if by == 0:
                by = 1

            i = start
            while (i <= end if by > 0 else i >= end):
                ctx.pdv.set(stmt.var, i)
                self._execute_statements(stmt.body, ctx)
                if ctx.pdv.stop_flag or ctx.pdv.delete_flag:
                    break
                i += by
        elif stmt.while_cond:
            while sas_bool(ctx.evaluator.evaluate(stmt.while_cond)):
                self._execute_statements(stmt.body, ctx)
                if ctx.pdv.stop_flag:
                    break
        elif stmt.until_cond:
            while True:
                self._execute_statements(stmt.body, ctx)
                if ctx.pdv.stop_flag or sas_bool(ctx.evaluator.evaluate(stmt.until_cond)):
                    break
        else:
            # Simple DO block
            self._execute_statements(stmt.body, ctx)

    def _execute_sum_stmt(self, stmt: SumStatementNode, ctx: DataStepContext) -> None:
        """Execute SAS sum statement: var + expr (implicit retain, missing→0)."""
        increment = ctx.evaluator.evaluate(stmt.expr)
        if is_missing(increment):
            increment = 0.0
        current = ctx.pdv.get(stmt.target)
        if is_missing(current):
            current = 0.0
        try:
            ctx.pdv.set(stmt.target, float(current) + float(increment))
        except (TypeError, ValueError):
            ctx.pdv.set(stmt.target, float("nan"))
        # Mark retained so the value persists across iterations
        key = stmt.target.upper()
        if key in ctx.pdv.variables:
            ctx.pdv.variables[key].retained = True

    def _execute_array_assign(self, stmt: ArrayAssignNode, ctx: DataStepContext) -> None:
        """Execute arr[index] = expr — assign to the underlying PDV variable."""
        idx = ctx.evaluator.evaluate(stmt.index)
        val = ctx.evaluator.evaluate(stmt.expr)
        if idx is None or (isinstance(idx, float) and pd.isna(idx)):
            return
        i = int(idx) - 1  # SAS 1-based
        var_names = ctx.arrays.get(stmt.array_name.upper())
        if var_names and 0 <= i < len(var_names):
            ctx.pdv.set(var_names[i], val)
        elif var_names is None:
            # Not a known array — treat as plain variable when index == 1
            if i == 0:
                ctx.pdv.set(stmt.array_name, val)

    def _execute_substr_assign(self, stmt: SubstrAssignNode, ctx: DataStepContext) -> None:
        """Execute SUBSTR(target, start [, length]) = expr."""
        target = stmt.target.upper()
        start = int(ctx.evaluator.evaluate(stmt.start)) - 1  # SAS 1-based
        new_val = str(ctx.evaluator.evaluate(stmt.expr))
        cur_val = ctx.pdv.get(target)
        if is_missing(cur_val) or cur_val == "":
            cur_val = ""
        else:
            cur_val = str(cur_val)
        # Pad if needed
        if start > len(cur_val):
            cur_val = cur_val + " " * (start - len(cur_val))
        if stmt.length is not None:
            length = int(ctx.evaluator.evaluate(stmt.length))
            cur_val = cur_val[:start] + new_val[:length].ljust(length) + cur_val[start + length:]
        else:
            cur_val = cur_val[:start] + new_val + cur_val[start + len(new_val):]
        ctx.pdv.set(target, cur_val)

    def _execute_put(self, stmt: PutNode, ctx: DataStepContext) -> None:
        """Execute PUT statement — write to log."""
        parts = []
        for item in stmt.items:
            if isinstance(item, str):
                # String literal
                parts.append(item.strip('"').strip("'"))
            elif hasattr(item, "name") and hasattr(item, "format_spec"):
                # PutItemNode with format
                val = ctx.pdv.get(item.name)
                if item.format_spec:
                    parts.append(self._apply_put_format(val, item.format_spec))
                else:
                    parts.append(str(val) if val is not None else ".")
            elif hasattr(item, "name"):
                val = ctx.pdv.get(item.name)
                parts.append(str(val) if val is not None else ".")
            else:
                val = ctx.evaluator.evaluate(item)
                parts.append(str(val) if val is not None else ".")
        self.reporter.log(" ".join(parts))

    @staticmethod
    def _apply_put_format(value: Any, fmt: str) -> str:
        """Apply a PUT format to a value."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "."
        fmt_upper = fmt.upper()
        # Common numeric formats
        if fmt_upper.startswith("BEST"):
            try:
                return f"{float(value):g}"
            except (ValueError, TypeError):
                return str(value)
        if fmt_upper.startswith("F") or fmt_upper.startswith("DOLLAR"):
            # Fw.d or DOLLARw.d
            parts = fmt_upper.lstrip("F").lstrip("DOLLAR").split(".")
            if len(parts) == 2:
                dec = int(parts[1])
                try:
                    return f"{float(value):.{dec}f}"
                except (ValueError, TypeError):
                    return str(value)
        if fmt_upper == "COMMA":
            try:
                return f"{float(value):,.0f}"
            except (ValueError, TypeError):
                return str(value)
        if fmt_upper.startswith("Z") or fmt_upper.startswith("ZERO"):
            # Zero-padded numeric
            try:
                return f"{int(value)}"
            except (ValueError, TypeError):
                return str(value)
        return str(value)

    def _execute_call_symput(self, stmt: CallSymputNode, ctx: DataStepContext) -> None:
        """Execute CALL SYMPUT/SYMPUTX('macro_var', value)."""
        var_name = ctx.evaluator.evaluate(stmt.macro_var)
        value = ctx.evaluator.evaluate(stmt.value)
        if var_name is not None:
            str_val = str(value) if value is not None else ""
            if stmt.trim:
                # SYMPUTX strips blanks and formats numerics compactly
                if isinstance(value, float) and not is_missing(value) and value == int(value):
                    str_val = str(int(value))
                str_val = str_val.strip()
            ctx.session.set_macro_var(str(var_name).strip(), str_val)

    def _execute_call_missing(self, stmt: CallMissingNode, ctx: DataStepContext) -> None:
        """Execute CALL MISSING(var1, var2, ...) — set variables to missing."""
        from saslite.ast.expressions import VariableNode
        for arg in stmt.variables:
            if isinstance(arg, VariableNode):
                cur = ctx.pdv.get(arg.name)
                if isinstance(cur, str):
                    ctx.pdv.set(arg.name, "")
                else:
                    ctx.pdv.set(arg.name, float("nan"))

    def _execute_data_update(self, stmt: UpdateDataNode, ctx: DataStepContext) -> None:
        """Execute DATA step UPDATE statement (master dataset update)."""
        if not stmt.datasets:
            return
        ds_ref = stmt.datasets[0]
        try:
            ds = ctx.session.get_dataset(ds_ref.libref, ds_ref.name)
        except KeyError:
            return
        # Match current observation to master by index (simplified)
        row_idx = ctx.pdv._n - 1
        if row_idx < len(ds.data):
            row = ds.data.iloc[row_idx].to_dict()
            ctx.pdv.load_row(row)

    def _register_array(self, stmt: ArrayNode, ctx: DataStepContext) -> None:
        """Register an ARRAY statement — link array name to variable list."""
        if stmt.temporary:
            values = [ctx.evaluator.evaluate(value) for value in stmt.initial_values]
            ctx.evaluator.register_array(stmt.name, values)
            return

        var_names = [v.upper() for v in stmt.variables]
        ctx.arrays[stmt.name.upper()] = var_names
        # Register variable list for DIM() and OF arr[*] expansion
        ctx.evaluator.register_array_vars(stmt.name, var_names)
        # Also register in evaluator for subscript access
        def make_array_accessor(arr_name: str, vnames: list[str], pdv_ref):
            def accessor(idx: int) -> Any:
                i = int(idx) - 1  # SAS 1-based
                if 0 <= i < len(vnames):
                    return pdv_ref.get(vnames[i])
                return float("nan")
            return accessor
        ctx.evaluator.register_function(
            stmt.name.upper(),
            make_array_accessor(stmt.name, var_names, ctx.pdv),
        )

        for variable, initial_value in zip(var_names, stmt.initial_values):
            ctx.pdv.set(variable, ctx.evaluator.evaluate(initial_value))

    def _resolve_ds_name(self, ref: DatasetRefNode) -> str:
        return f"{ref.libref.upper()}.{ref.name.upper()}"

    @staticmethod
    def _split_output_target(target: str) -> tuple[str, str]:
        full = target.upper()
        if "." in full:
            return tuple(full.split(".", 1))  # type: ignore[return-value]
        return "WORK", full

    def _store_declared_outputs(
        self,
        step: DataStepNode,
        ctx: DataStepContext,
        pdv: PDV,
        input_datasets: list[Dataset],
        in_flag_names: set[str],
        warnings: list[str] | None = None,
    ) -> StepResult:
        """Materialize every DATA target using named and broadcast OUTPUT rows."""
        targets = [step.target, *step.extra_targets]
        declared = {
            key
            for target in targets
            if target.upper() != "_NULL_"
            for key in (
                target.upper(),
                self._split_output_target(target)[1],
            )
        }
        unknown = sorted(set(ctx.target_rows) - declared)
        if unknown:
            return StepResult(
                success=False,
                error=f"OUTPUT target(s) not declared in DATA statement: {', '.join(unknown)}",
            )

        notes: list[str] = []
        total_rows = 0
        primary_name = ""
        for target_index, target in enumerate(targets):
            if target.upper() == "_NULL_":
                continue
            libref, member = self._split_output_target(target)
            full_name = f"{libref}.{member}"
            rows = list(ctx.output_rows)
            for key in {target.upper(), member, full_name}:
                rows.extend(ctx.target_rows.get(key, []))
            out_ds = self._build_output_dataset(
                rows,
                member,
                libref,
                step,
                pdv,
                input_datasets,
                in_flag_names,
                step.target_options if target_index == 0 else {},
            )
            self.session.put_dataset(libref, member, out_ds)
            primary_name = primary_name or full_name
            total_rows += out_ds.nrow
            notes.append(
                f"Dataset {full_name} created with {out_ds.nrow} observations "
                f"and {out_ds.ncol} variables."
            )

        return StepResult(
            success=True,
            dataset_name=primary_name or None,
            rows_affected=total_rows,
            notes=notes,
            warnings=warnings or [],
        )

    def _build_output_dataset(
        self,
        rows: list[dict[str, Any]],
        member: str,
        libref: str,
        step: DataStepNode,
        pdv: PDV,
        input_datasets: list[Dataset],
        in_flag_names: set[str],
        output_options: dict[str, Any],
    ) -> Dataset:
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=[
                variable.metadata.name for variable in pdv.variables.values()
            ])
        if in_flag_names:
            df = df.drop(columns=[
                column for column in df.columns
                if str(column).upper() in in_flag_names
            ], errors="ignore")

        out_ds = Dataset.from_dataframe(df, name=member, libref=libref)
        for column in out_ds.data.columns:
            target_meta = out_ds.metadata.get_variable(str(column))
            if target_meta is None:
                continue
            for input_ds in input_datasets:
                source_meta = input_ds.metadata.get_variable(str(column))
                if source_meta is not None:
                    target_meta.length = source_meta.length
                    target_meta.format = source_meta.format
                    target_meta.informat = source_meta.informat
                    target_meta.label = source_meta.label
                    break
            pdv_variable = pdv.variables.get(str(column).upper())
            if pdv_variable is not None:
                source_meta = pdv_variable.metadata
                target_meta.dtype = source_meta.dtype
                target_meta.length = source_meta.length
                target_meta.format = source_meta.format
                target_meta.informat = source_meta.informat
                target_meta.label = source_meta.label

        # KEEP/DROP select the compile-time (pre-RENAME) variable names in
        # SAS, regardless of the textual order of the statements.  RENAME is
        # an output operation and must therefore run after selection.
        if "WHERE" in output_options:
            selected = self._evaluate_where_mask(
                out_ds.data,
                output_options["WHERE"],
            )
            out_ds.data = out_ds.data.loc[selected].reset_index(drop=True)
            out_ds.metadata.row_count = len(out_ds.data)

        for stmt in step.statements:
            if isinstance(stmt, KeepNode):
                keep = {name.upper() for name in stmt.variables}
                out_ds = out_ds.select_columns([
                    column for column in out_ds.data.columns
                    if str(column).upper() in keep
                ])
            elif isinstance(stmt, DropNode):
                drop = {name.upper() for name in stmt.variables}
                out_ds = out_ds.select_columns([
                    column for column in out_ds.data.columns
                    if str(column).upper() not in drop
                ])

        if "KEEP" in output_options:
            keep = {str(name).upper() for name in output_options["KEEP"]}
            out_ds = out_ds.select_columns([
                column for column in out_ds.data.columns
                if str(column).upper() in keep
            ])
        if "DROP" in output_options:
            drop = {str(name).upper() for name in output_options["DROP"]}
            out_ds = out_ds.select_columns([
                column for column in out_ds.data.columns
                if str(column).upper() not in drop
            ])

        for stmt in step.statements:
            if isinstance(stmt, RenameNode):
                out_ds = out_ds.rename_columns(stmt.mapping)
        if "RENAME" in output_options:
            out_ds = out_ds.rename_columns(output_options["RENAME"])

        for stmt in step.statements:
            if isinstance(stmt, FormatNode):
                metadata_items = [(name, "FORMAT", value) for name, value in stmt.items]
            elif isinstance(stmt, LabelNode):
                metadata_items = [(name, "LABEL", value) for name, value in stmt.items]
            elif isinstance(stmt, LengthNode):
                metadata_items = [(name, "LENGTH", value) for name, value in stmt.items]
            elif isinstance(stmt, AttribNode):
                metadata_items = stmt.items
            elif isinstance(stmt, FormatResetNode):
                for variable in out_ds.metadata.variables.values():
                    variable.format = None
                continue
            elif isinstance(stmt, InformatResetNode):
                for variable in out_ds.metadata.variables.values():
                    variable.informat = None
                continue
            else:
                continue
            for name, attribute, value in metadata_items:
                variable = out_ds.metadata.get_variable(name)
                if variable is None or value is None:
                    continue
                if attribute == "FORMAT":
                    variable.format = value
                elif attribute == "LABEL":
                    variable.label = value
                elif attribute == "INFORMAT":
                    variable.informat = value
                elif attribute == "LENGTH":
                    try:
                        variable.length = int(value)
                    except (TypeError, ValueError):
                        pass
        return out_ds

    def _apply_dataset_options(self, ds, options):
        """Apply input data set options before DATA-step iteration."""
        if not options:
            return ds

        firstobs = 1
        obs: int | None = None
        for opt in options:
            if not isinstance(opt, dict):
                continue
            if "FIRSTOBS" in opt:
                firstobs = int(opt["FIRSTOBS"])
            if "OBS" in opt:
                obs = int(opt["OBS"])

        # SAS observation numbers are one-based and OBS= is inclusive. Apply
        # the range once, independently of the textual order of other options.
        ds = ds.copy()
        stop = obs if obs is not None else None
        ds.data = ds.data.iloc[firstobs - 1:stop].reset_index(drop=True)
        ds.metadata.row_count = len(ds.data)

        # WHERE= is evaluated against the source row before KEEP/DROP/RENAME
        # alter its available variables.
        for opt in options:
            if not isinstance(opt, dict) or "WHERE" not in opt:
                continue
            expression = opt["WHERE"]
            selected = self._evaluate_where_mask(ds.data, expression)
            ds.data = ds.data.loc[selected].reset_index(drop=True)
            ds.metadata.row_count = len(ds.data)

        for opt in options:
            if not isinstance(opt, dict):
                continue
            if "RENAME" in opt:
                columns = {str(column).upper(): column for column in ds.data.columns}
                rename = {
                    columns[str(old).upper()]: new
                    for old, new in opt["RENAME"].items()
                    if str(old).upper() in columns
                }
                ds = ds.rename_columns(rename)
            if "KEEP" in opt:
                keep_cols = [c.upper() for c in opt["KEEP"]]
                actual = [c for c in ds.data.columns if c.upper() in keep_cols]
                ds = ds.select_columns(actual)
            if "DROP" in opt:
                drop_cols = [c.upper() for c in opt["DROP"]]
                actual = [c for c in ds.data.columns if c.upper() not in drop_cols]
                ds = ds.select_columns(actual)
        return ds

    def _evaluate_where_mask(
        self,
        frame: pd.DataFrame,
        expression: Any,
    ) -> list[bool]:
        """Evaluate a data-set WHERE= expression against each source row."""
        selected: list[bool] = []
        for row in frame.to_dict(orient="records"):
            values = {str(name).upper(): value for name, value in row.items()}
            evaluator = ExpressionEvaluator(
                var_getter=lambda name, current=values: current.get(name.upper()),
                session=self.session,
            )
            for function_name in self._fn_registry.names:
                function = self._fn_registry.get(function_name)
                if function is not None:
                    evaluator.register_function(function_name, function)
            try:
                selected.append(sas_bool(evaluator.evaluate(expression)))
            except Exception:
                selected.append(False)
        return selected

    @staticmethod
    def _dataset_in_flag(ref: DatasetRefNode) -> str:
        for option in ref.options:
            if isinstance(option, dict) and option.get("IN"):
                return str(option["IN"]).upper()
        return ""

    @staticmethod
    def _add_in_flag(ds: Dataset, flag_name: str) -> Dataset:
        """Return a copy with a temporary numeric IN= contribution flag."""
        flagged = ds.copy()
        flagged.data[flag_name] = 1
        flagged.metadata.variables[flag_name] = make_variable(
            flag_name, dtype="numeric"
        )
        return flagged

    def _execute_merge(self, step: DataStepNode, datasets: list[Dataset],
                       by_vars: list[str], target_name: str,
                       target_libref: str,
                       in_flag_names: set[str] | None = None) -> StepResult:
        """Execute MERGE statement."""
        if not datasets:
            return StepResult(success=False, error="MERGE requires at least one dataset")

        merge_warnings: list[str] = []
        if by_vars and len(datasets) >= 2:
            merge_warnings = self._many_to_many_merge_warnings(datasets, by_vars)
            left_df = self._match_merge_frames(datasets, by_vars)
            for flag_name in in_flag_names or set():
                actual = self._find_col(left_df, flag_name)
                if actual is not None:
                    left_df[actual] = left_df[actual].fillna(0)
        elif len(datasets) >= 2:
            # One-to-one merge (no BY)
            dfs = [ds.data.copy() for ds in datasets]
            min_rows = min(len(df) for df in dfs)
            # Concatenate columns side by side
            trimmed = [df.iloc[:min_rows].reset_index(drop=True) for df in dfs]
            left_df = pd.concat(trimmed, axis=1)
            # Remove duplicate columns
            left_df = left_df.loc[:, ~left_df.columns.duplicated()]
        else:
            left_df = datasets[0].data.copy()

        # Build the PDV from input metadata and declarations so character
        # LENGTH checks also apply to values loaded by MERGE.
        pdv = self._build_pdv(step, datasets)
        for col in left_df.columns:
            pdv.ensure_variable(col)

        lag_state = LagState()
        eval_ctx = DataStepContext(pdv, self._fn_registry, self.session, lag_state)
        has_explicit_output = self._has_explicit_output(step.statements)

        # Extract WHERE
        where_condition = None
        for stmt in step.statements:
            if isinstance(stmt, WhereNode):
                where_condition = stmt.condition
                break

        # Process each row
        for i in range(len(left_df)):
            pdv.increment_n()
            pdv.reset_for_iteration()
            row = left_df.iloc[i].to_dict()
            pdv.load_row(row)

            if where_condition:
                try:
                    where_eval = ExpressionEvaluator(var_getter=pdv.get)
                    for name in self._fn_registry.names:
                        fn = self._fn_registry.get(name)
                        if fn:
                            where_eval.register_function(name, fn)
                    if not sas_bool(where_eval.evaluate(where_condition)):
                        continue
                except Exception:
                    continue

            self._execute_statements(step.statements, eval_ctx)

            if pdv.stop_flag:
                break
            if not pdv.delete_flag and not has_explicit_output:
                eval_ctx.output_rows.append(pdv.snapshot_output_row())

        return self._store_declared_outputs(
            step,
            eval_ctx,
            pdv,
            datasets,
            in_flag_names or set(),
            [
                *merge_warnings,
                *pdv.character_length_warnings(),
                *pdv.runtime_warnings(),
            ],
        )

    @staticmethod
    def _many_to_many_merge_warnings(
        datasets: list[Dataset],
        by_vars: list[str],
    ) -> list[str]:
        """Describe BY groups repeated in two or more MERGE inputs."""
        keys = [name.upper() for name in by_vars]
        repeated: dict[
            tuple[tuple[str, str], ...],
            tuple[tuple[Any, ...], list[tuple[str, int]]],
        ] = {}

        for dataset in datasets:
            column_map = {str(column).upper(): column for column in dataset.data.columns}
            actual_keys = [column_map[name] for name in keys if name in column_map]
            if len(actual_keys) != len(keys):
                continue
            counts = dataset.data.groupby(
                actual_keys,
                sort=False,
                dropna=False,
            ).size()
            dataset_name = (
                f"{dataset.metadata.libref}.{dataset.metadata.member_name}"
            ).upper()
            for raw_key, count in counts.items():
                if int(count) <= 1:
                    continue
                values = raw_key if isinstance(raw_key, tuple) else (raw_key,)
                signature = tuple(
                    ("missing", "")
                    if pd.isna(value)
                    else (type(value).__name__, repr(value))
                    for value in values
                )
                if signature not in repeated:
                    repeated[signature] = (values, [])
                repeated[signature][1].append((dataset_name, int(count)))

        conflicts = [entry for entry in repeated.values() if len(entry[1]) >= 2]
        warnings: list[str] = []
        for values, sources in conflicts[:5]:
            by_value = ", ".join(
                f"{name}={DataStepExecutor._display_merge_key(value)}"
                for name, value in zip(keys, values)
            )
            source_text = ", ".join(
                f"{name} ({count} observations)" for name, count in sources
            )
            warnings.append(
                "Many-to-many MERGE detected: "
                f"BY group {by_value} repeats in {source_text}. "
                "SAS match-merge semantics align observations by position; "
                "this is not a Cartesian join."
            )
        if len(conflicts) > 5:
            warnings.append(
                f"Many-to-many MERGE detected in {len(conflicts) - 5} additional "
                "BY group(s); only the first 5 groups are shown."
            )
        return warnings

    @staticmethod
    def _display_merge_key(value: Any) -> str:
        try:
            if pd.isna(value):
                return "."
        except (TypeError, ValueError):
            pass
        if isinstance(value, str):
            return repr(value)
        return str(value)

    def _match_merge_frames(
        self,
        datasets: list[Dataset],
        by_vars: list[str],
    ) -> pd.DataFrame:
        """SAS-style match merge without pandas suffix columns.

        Rows with the same BY values are aligned by their position within the
        group. Shorter inputs retain their last observation for the remainder
        of that BY group. When inputs share a non-BY variable, the later input
        in the MERGE statement overwrites the PDV value, including with a
        missing value.
        """
        keys = [name.upper() for name in by_vars]
        occurrence = "__SASLITE_MERGE_ROW__"
        prepared: list[pd.DataFrame] = []

        for dataset in datasets:
            frame = dataset.data.copy()
            column_map = {str(column).upper(): column for column in frame.columns}
            missing = [name for name in keys if name not in column_map]
            if missing:
                raise ValueError(
                    f"BY variable(s) {', '.join(missing)} not found in "
                    f"dataset {dataset.name}"
                )
            frame = frame.rename(columns={column_map[name]: name for name in keys})
            frame[occurrence] = frame.groupby(
                keys,
                sort=False,
                dropna=False,
            ).cumcount()
            prepared.append(frame)

        scaffold_parts = [frame[keys + [occurrence]] for frame in prepared]
        scaffold = pd.concat(scaffold_parts, ignore_index=True).drop_duplicates()
        if not scaffold.empty:
            try:
                scaffold = scaffold.sort_values(
                    keys + [occurrence],
                    kind="stable",
                ).reset_index(drop=True)
            except TypeError:
                scaffold = scaffold.reset_index(drop=True)

        result = scaffold.copy()
        output_columns: dict[str, str] = {}
        for dataset_index, frame in enumerate(prepared):
            non_by = [
                column for column in frame.columns
                if column not in keys and column != occurrence
            ]
            temporary = {
                column: f"__SASLITE_{dataset_index}_{position}__"
                for position, column in enumerate(non_by)
            }
            actual_marker = f"__SASLITE_ACTUAL_{dataset_index}__"
            current = frame[keys + [occurrence] + non_by].rename(columns=temporary)
            current[actual_marker] = 1
            expanded = scaffold.merge(
                current,
                on=keys + [occurrence],
                how="left",
                sort=False,
            )

            present_marker = f"__SASLITE_PRESENT_{dataset_index}__"
            present = frame[keys].drop_duplicates().copy()
            present[present_marker] = 1
            expanded = expanded.merge(present, on=keys, how="left", sort=False)
            contributes = expanded[present_marker].eq(1)

            last_columns = {
                column: f"__SASLITE_LAST_{dataset_index}_{position}__"
                for position, column in enumerate(non_by)
            }
            last = (
                frame.groupby(keys, sort=False, dropna=False)
                .tail(1)[keys + non_by]
                .rename(columns=last_columns)
            )
            expanded = expanded.merge(last, on=keys, how="left", sort=False)
            repeat_last = expanded[actual_marker].isna() & contributes

            for column in non_by:
                logical_name = str(column).upper()
                value = expanded[temporary[column]].where(
                    ~repeat_last,
                    expanded[last_columns[column]],
                )
                output_name = output_columns.get(logical_name)
                if output_name is None:
                    output_name = str(column)
                    output_columns[logical_name] = output_name
                    result[output_name] = value
                else:
                    result[output_name] = value.where(
                        contributes,
                        result[output_name],
                    )

        return result.drop(columns=[occurrence])

    def _build_datalines_dataset(self, step: DataStepNode, input_node: InputNode) -> Dataset:
        """Build a dataset from INPUT + DATALINES, to be fed into the implicit loop."""
        rows = self._parse_datalines_rows(step, input_node)

        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=[v.upper() for v in input_node.variables])

        return Dataset.from_dataframe(df, name="DATALINES", libref="WORK")

    def _parse_datalines_rows(self, step: DataStepNode,
                              input_node: InputNode) -> list[dict[str, Any]]:
        """Parse INPUT + DATALINES rows, honoring basic INFILE options."""
        variables = input_node.variables
        raw_data = input_node.datalines_data
        delimiter, dsd, truncover = self._get_infile_datalines_options(step)
        rows: list[dict[str, Any]] = []

        # Column mode: fixed positions like INPUT name $ 1-10 age 12-13;
        if input_node.col_positions:
            for line in raw_data.split("\n"):
                if not line.strip():
                    continue
                row: dict[str, Any] = {}
                for var_name in variables:
                    key = var_name.upper()
                    pos = input_node.col_positions.get(key)
                    if pos:
                        start, end = pos
                        raw_val = line[start - 1:end].strip()
                    else:
                        raw_val = ""
                    row[key] = self._convert_datalines_value(var_name, raw_val, input_node)
                rows.append(row)
            return rows

        if delimiter:
            for line in raw_data.split("\n"):
                line = line.rstrip()
                if not line:
                    continue
                fields = line.split(delimiter)
                rows.append(self._datalines_fields_to_row(
                    fields, variables, input_node, dsd, truncover))
            return rows

        import shlex
        all_tokens: list[str] = []
        for line in raw_data.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                all_tokens.extend(shlex.split(line))
            except ValueError:
                all_tokens.extend(line.split())

        n_vars = len(variables)
        for i in range(0, len(all_tokens), n_vars):
            chunk = all_tokens[i:i + n_vars]
            rows.append(self._datalines_fields_to_row(
                chunk, variables, input_node, dsd=False, truncover=False))
        return rows

    @staticmethod
    def _get_infile_datalines_options(step: DataStepNode) -> tuple[str | None, bool, bool]:
        """Return delimiter, DSD, and TRUNCOVER options from INFILE DATALINES."""
        infile_nodes = [s for s in step.statements if isinstance(s, InfileNode)]
        delimiter = None
        dsd = False
        truncover = False

        if infile_nodes:
            options = infile_nodes[0].options
            if "DLM" in options:
                delimiter = str(options["DLM"]).strip("'\"")
            elif "DELIMITER" in options:
                delimiter = str(options["DELIMITER"]).strip("'\"")
            dsd = "DSD" in options
            truncover = "TRUNCOVER" in options

        return delimiter, dsd, truncover

    def _datalines_fields_to_row(self, fields: list[str], variables: list[str],
                                 input_node: InputNode, dsd: bool,
                                 truncover: bool) -> dict[str, Any]:
        """Convert parsed raw fields to a DATA step input row."""
        row: dict[str, Any] = {}
        for k, var_name in enumerate(variables):
            if k < len(fields):
                raw_val = fields[k] if dsd else fields[k].strip()
                row[var_name.upper()] = self._convert_datalines_value(
                    var_name, raw_val, input_node)
            else:
                if self._input_var_is_character(var_name, input_node):
                    row[var_name.upper()] = "" if truncover else None
                else:
                    row[var_name.upper()] = float("nan") if truncover else None
        return row

    @staticmethod
    def _input_var_is_character(var_name: str, input_node: InputNode) -> bool:
        key = var_name.upper()
        format_spec = input_node.formats.get(key, "")
        return input_node.is_character.get(key, False) or format_spec.startswith("$")

    def _convert_datalines_value(self, var_name: str, raw_val: str,
                                 input_node: InputNode) -> Any:
        _EMPTY_PLACEHOLDER = "\x01"
        if raw_val == _EMPTY_PLACEHOLDER:
            raw_val = ""

        key = var_name.upper()
        format_spec = input_node.formats.get(key, "")

        # Check if variable is character type
        is_char_var = self._input_var_is_character(var_name, input_node)

        # Apply input format if specified
        if format_spec:
            # Character formats ($N. or $CHAR.) should return string directly
            if format_spec.startswith("$"):
                # Extract width from format like $20.
                import re
                match = re.match(r"\$(\d+)", format_spec)
                if match:
                    width = int(match.group(1))
                    return raw_val[:width] if raw_val else ""
                # Other $ formats: return as-is
                return raw_val if raw_val else ""

            # Numeric/date formats: use input_sas
            from saslite.functions.convert_funcs import input_sas
            val = input_sas(raw_val, format_spec)
            # For date formats, convert to string representation
            if not isinstance(val, str) and any(fmt in format_spec.upper() for fmt in ["MMDDYY", "DDMMYY", "DATE", "DATETIME"]):
                from datetime import datetime, timedelta
                import math
                if not math.isnan(val):
                    base = datetime(1960, 1, 1)
                    date = base + timedelta(days=val)
                    return date.strftime("%Y-%m-%d")
            return val

        if is_char_var:
            if raw_val == "." or raw_val == "":
                return ""
            return raw_val

        if raw_val == "." or raw_val == "":
            return float("nan")
        try:
            if "." in raw_val or "e" in raw_val.lower():
                return float(raw_val)
            return int(raw_val)
        except ValueError:
            return float("nan")

    def _combine_parallel_sets(self, set_groups: list[list[Dataset]],
                               by_vars: list[str]) -> pd.DataFrame:
        """Combine multiple SET statements: parallel (side-by-side) reading.

        Each SET statement advances its own pointer; the DATA step stops at
        the SHORTEST input (standard SAS double-SET semantics). Within one
        SET statement multiple datasets still stack vertically. Overlapping
        variables: the later SET statement's value wins.
        """
        group_dfs = []
        for group in set_groups:
            group_dfs.append(self._combine_inputs(group, by_vars))
        group_dfs = [df for df in group_dfs if df is not None]
        if not group_dfs:
            return pd.DataFrame()
        if len(group_dfs) == 1:
            return group_dfs[0]

        n = min(len(df) for df in group_dfs)
        combined = group_dfs[0].iloc[:n].reset_index(drop=True)
        for df in group_dfs[1:]:
            right = df.iloc[:n].reset_index(drop=True)
            for col in right.columns:
                combined[col] = right[col]  # later SET wins on overlap
        return combined

    def _combine_inputs(self, datasets: list[Dataset], by_vars: list[str]) -> pd.DataFrame:
        """Combine multiple input datasets: vertical stacking or BY-interleave."""
        if not datasets:
            return pd.DataFrame()

        if len(datasets) == 1:
            return datasets[0].data.copy()

        # Vertical stacking
        dfs = [ds.data.copy() for ds in datasets]

        if by_vars:
            # BY-interleave: concatenate and sort by BY variables
            combined = pd.concat(dfs, ignore_index=True)
            # Find actual column names (case-insensitive)
            sort_cols = []
            for bv in by_vars:
                for col in combined.columns:
                    if col.upper() == bv.upper():
                        sort_cols.append(col)
                        break
            if sort_cols:
                combined = combined.sort_values(by=sort_cols).reset_index(drop=True)
            return combined
        else:
            # Simple vertical stacking
            return pd.concat(dfs, ignore_index=True)

    @staticmethod
    def _find_col(df: pd.DataFrame, name: str) -> str | None:
        """Find column case-insensitively."""
        if name in df.columns:
            return name
        for col in df.columns:
            if col.upper() == name.upper():
                return col
        return None

    def _execute_input_datalines(self, step: DataStepNode, input_node: InputNode,
                                  target_name: str, target_libref: str) -> StepResult:
        """Execute INPUT + DATALINES: parse raw data and create dataset."""
        variables = input_node.variables
        is_char = input_node.is_character
        formats = input_node.formats
        raw_data = input_node.datalines_data

        # Check for INFILE statement to get delimiter and options
        from saslite.ast.data_step import InfileNode
        infile_nodes = [s for s in step.statements if isinstance(s, InfileNode)]
        delimiter = None
        dsd = False
        truncover = False

        if infile_nodes:
            infile = infile_nodes[0]
            options = infile.options
            # DLM or DELIMITER option
            if 'DLM' in options:
                delimiter = options['DLM'].strip("'\"")
            elif 'DELIMITER' in options:
                delimiter = options['DELIMITER'].strip("'\"")
            # DSD option (delimiter-sensitive data)
            dsd = 'DSD' in options
            # TRUNCOVER option
            truncover = 'TRUNCOVER' in options

        # Parse raw data based on delimiter
        rows: list[dict[str, Any]] = []

        if delimiter:
            # Delimiter-based parsing
            for line in raw_data.split("\n"):
                line = line.rstrip()
                if not line:
                    continue

                # Split by delimiter
                fields = line.split(delimiter)

                row: dict[str, Any] = {}
                for k, var_name in enumerate(variables):
                    if k < len(fields):
                        raw_val = fields[k].strip() if not dsd else fields[k]

                        # Apply format if specified
                        format_spec = formats.get(var_name.upper(), "")

                        if is_char.get(var_name.upper(), False) or format_spec.startswith("$"):
                            # Character variable
                            if raw_val == "." or raw_val == "":
                                row[var_name.upper()] = ""
                            else:
                                row[var_name.upper()] = raw_val
                        else:
                            # Numeric variable
                            if raw_val == "." or raw_val == "":
                                row[var_name.upper()] = float("nan")
                            else:
                                try:
                                    if "." in raw_val:
                                        row[var_name.upper()] = float(raw_val)
                                    else:
                                        row[var_name.upper()] = int(raw_val)
                                except ValueError:
                                    row[var_name.upper()] = float("nan")
                    else:
                        # Missing field
                        if truncover:
                            # TRUNCOVER: missing fields become missing values
                            if is_char.get(var_name.upper(), False):
                                row[var_name.upper()] = ""
                            else:
                                row[var_name.upper()] = float("nan")
                        else:
                            row[var_name.upper()] = None
                rows.append(row)
        else:
            # Space-delimited parsing (original logic)
            import shlex
            _EMPTY_PLACEHOLDER = "\x01"
            all_tokens: list[str] = []
            for line in raw_data.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    all_tokens.extend(shlex.split(line))
                except ValueError:
                    all_tokens.extend(line.split())

            all_tokens = ["" if t == _EMPTY_PLACEHOLDER else t for t in all_tokens]

            n_vars = len(variables)
            for i in range(0, len(all_tokens), n_vars):
                chunk = all_tokens[i:i + n_vars]
                row: dict[str, Any] = {}
                for k, var_name in enumerate(variables):
                    if k < len(chunk):
                        raw_val = chunk[k]
                        if is_char.get(var_name.upper(), False):
                            if raw_val == "." or raw_val == "":
                                row[var_name.upper()] = ""
                            else:
                                row[var_name.upper()] = raw_val
                        else:
                            if raw_val == "." or raw_val == "":
                                row[var_name.upper()] = float("nan")
                            else:
                                try:
                                    if "." in raw_val:
                                        row[var_name.upper()] = float(raw_val)
                                    else:
                                        row[var_name.upper()] = int(raw_val)
                                except ValueError:
                                    row[var_name.upper()] = float("nan")
                    else:
                        row[var_name.upper()] = None
                rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=[v.upper() for v in variables])

        out_ds = Dataset.from_dataframe(df, name=target_name, libref=target_libref)

        # Apply KEEP/DROP/RENAME, FORMAT, LABEL from other statements
        for stmt in step.statements:
            if isinstance(stmt, KeepNode):
                keep_cols = [c.upper() for c in stmt.variables]
                actual = [c for c in df.columns if c.upper() in keep_cols]
                out_ds = out_ds.select_columns(actual)
            elif isinstance(stmt, DropNode):
                drop_cols = [c.upper() for c in stmt.variables]
                actual = [c for c in df.columns if c.upper() not in drop_cols]
                out_ds = out_ds.select_columns(actual)
            elif isinstance(stmt, RenameNode):
                out_ds = out_ds.rename_columns(stmt.mapping)

        # Apply FORMAT/LABEL metadata
        for stmt in step.statements:
            if isinstance(stmt, FormatNode):
                for var_name, fmt in stmt.items:
                    key = var_name.upper()
                    if key in out_ds.metadata.variables:
                        out_ds.metadata.variables[key].format = fmt
            elif isinstance(stmt, LabelNode):
                for var_name, lbl in stmt.items:
                    key = var_name.upper()
                    if key in out_ds.metadata.variables:
                        out_ds.metadata.variables[key].label = lbl

        if target_name:
            self.session.put_dataset(target_libref, target_name, out_ds)
            return StepResult(
                success=True,
                dataset_name=f"{target_libref}.{target_name}",
                rows_affected=out_ds.nrow,
                notes=[f"Dataset {target_libref}.{target_name} created with {out_ds.nrow} observations and {out_ds.ncol} variables."],
            )
        return StepResult(success=True, rows_affected=0)


class DataStepContext:
    """Context for DATA step execution."""

    def __init__(self, pdv: PDV, fn_registry: Any, session: Session,
                 lag_state: LagState | None = None) -> None:
        self.pdv = pdv
        self.session = session
        self.output_rows: list[dict[str, Any]] = []
        # OUTPUT <dataset>; rows keyed by upper-cased target name
        self.target_rows: dict[str, list[dict[str, Any]]] = {}
        self.lag_state = lag_state
        self.evaluator = ExpressionEvaluator(
            var_getter=pdv.get,
            session=session,
            variable_metadata_getter=lambda name: (
                pdv.variables.get(name.upper()).metadata
                if pdv.variables.get(name.upper()) is not None
                else None
            ),
            diagnostic_callback=pdv.record_runtime_diagnostic,
        )
        self.arrays: dict[str, list[str]] = {}  # array_name → [var_names]
        # Register functions
        for name in fn_registry.names:
            fn = fn_registry.get(name)
            if fn:
                self.evaluator.register_function(name, fn)
        # Wrap PUT/PUTN to honor PROC FORMAT custom formats
        self._wrap_put_with_custom_formats(fn_registry)
        self._register_session_functions()
        # Register LAG/DIF stateful functions
        if lag_state:
            self._register_lag_dif(lag_state)

    def _register_session_functions(self) -> None:
        """Register DATA-step functions whose result depends on the session."""
        session = self.session

        def dataset_exists(dataset_name: Any, member_type: Any = "DATA") -> int:
            requested_type = str(member_type).strip().strip("'\"").upper()
            if requested_type not in {"", "DATA", "ANY"}:
                return 0
            reference = str(dataset_name).strip().strip("'\"")
            reference = reference.split("(", 1)[0].strip()
            if not reference:
                return 0
            if "." in reference:
                libref, member = reference.split(".", 1)
            else:
                libref, member = "WORK", reference
            try:
                return int(session.dataset_exists(libref, member))
            except (KeyError, OSError, ValueError):
                return 0

        self.evaluator.register_function("EXIST", dataset_exists)

    def _wrap_put_with_custom_formats(self, fn_registry: Any) -> None:
        """Make PUT()/PUTN() check session-defined custom formats first."""
        from saslite.executor.proc.extras import apply_custom_format
        base_put = fn_registry.get("PUT")
        base_putn = fn_registry.get("PUTN")
        session = self.session

        def put_with_formats(value, fmt, _base=base_put):
            label = apply_custom_format(session, str(fmt), value)
            if label is not None:
                return label
            return _base(value, fmt)

        def putn_with_formats(value, fmt, _base=base_putn):
            label = apply_custom_format(session, str(fmt), value)
            if label is not None:
                return label
            return _base(value, fmt)

        self.evaluator.register_function("PUT", put_with_formats)
        if base_putn:
            self.evaluator.register_function("PUTN", putn_with_formats)

    def _register_lag_dif(self, lag_state: LagState) -> None:
        """Register LAG/DIF functions with state."""
        def make_lag(n):
            def lag_fn(val):
                return lag_state.lag(val, n)
            return lag_fn
        def make_dif(n):
            def dif_fn(val):
                return lag_state.dif(val, n)
            return dif_fn
        # Register LAG, LAG2..LAG9
        self.evaluator.register_function("LAG", make_lag(1))
        for i in range(2, 10):
            self.evaluator.register_function(f"LAG{i}", make_lag(i))
        # Register DIF, DIF2..DIF9
        self.evaluator.register_function("DIF", make_dif(1))
        for i in range(2, 10):
            self.evaluator.register_function(f"DIF{i}", make_dif(i))
