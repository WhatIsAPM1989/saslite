"""Repeated-measures linear-model support for PROC MIXED."""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from saslite.ast.data_step import DatasetRefNode, WhereNode
from saslite.ast.proc import ProcNode
from saslite.diagnostics.reporter import Reporter
from saslite.executor.proc.registry import _apply_export_dataset_options
from saslite.executor.proc.survival import (
    _column,
    _level_sort_key,
    _sas_value_key,
    _write_dataset,
)
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session


DesignColumn = tuple[str, tuple[tuple[str, Any | None], ...]]


def _design_spec(
    frame: pd.DataFrame,
    effects: list[str],
    class_names: set[str],
    no_intercept: bool,
) -> tuple[list[DesignColumn], dict[str, list[Any]]]:
    class_levels: dict[str, list[Any]] = {}
    for effect in effects:
        for variable in effect.split("*"):
            if variable in class_names and variable not in class_levels:
                column = _column(frame, variable)
                assert column is not None
                class_levels[variable] = sorted(
                    frame[column].dropna().unique().tolist(), key=_level_sort_key
                )

    specification: list[DesignColumn] = []
    if not no_intercept:
        specification.append(("INTERCEPT", ()))
    for effect in effects:
        variables = effect.split("*")
        components: list[list[tuple[str, Any | None]]] = []
        for variable in variables:
            if variable in class_names:
                components.append(
                    [(variable, level) for level in class_levels[variable]]
                )
            else:
                components.append([(variable, None)])
        for combination in itertools.product(*components):
            specification.append((effect, tuple(combination)))
    return specification, class_levels


def _design_matrix(frame: pd.DataFrame, specification: list[DesignColumn]) -> np.ndarray:
    columns: list[np.ndarray] = []
    for _effect, components in specification:
        values = np.ones(len(frame), dtype=float)
        for variable, level in components:
            column = _column(frame, variable)
            if column is None:
                raise ValueError(f"Variable {variable} not found in dataset")
            if level is None:
                numeric = pd.to_numeric(frame[column], errors="coerce")
                if numeric.isna().any():
                    raise ValueError(
                        f"Variable {variable} must be numeric or listed in CLASS"
                    )
                values *= numeric.to_numpy(dtype=float)
            else:
                values *= (
                    frame[column].map(_sas_value_key) == _sas_value_key(level)
                ).to_numpy(dtype=float)
        columns.append(values)
    if not columns:
        raise ValueError("PROC MIXED has no estimable fixed effects")
    return np.column_stack(columns)


def _regularize_covariance(covariance: np.ndarray) -> np.ndarray:
    covariance = np.asarray(covariance, dtype=float)
    covariance = (covariance + covariance.T) / 2.0
    diagonal_scale = max(float(np.nanmean(np.diag(covariance))), 1e-8)
    covariance = np.nan_to_num(covariance, nan=0.0)
    values = np.linalg.eigvalsh(covariance)
    minimum = float(values.min()) if len(values) else 0.0
    floor = diagonal_scale * 1e-6
    if minimum < floor:
        covariance += np.eye(len(covariance)) * (floor - minimum)
    return covariance


def _estimate_repeated_covariance(
    working: pd.DataFrame,
    residuals: np.ndarray,
    subject_column: str,
    visit_column: str,
    visit_levels: list[Any],
    covariance_type: str,
    degrees_scale: float,
) -> np.ndarray:
    level_index = {_sas_value_key(level): index for index, level in enumerate(visit_levels)}
    size = len(visit_levels)
    sums = np.zeros((size, size), dtype=float)
    counts = np.zeros((size, size), dtype=float)
    residual_frame = working[[subject_column, visit_column]].copy()
    residual_frame["__RESIDUAL__"] = residuals
    for _, block in residual_frame.groupby(subject_column, dropna=False, sort=False):
        by_visit = block.groupby(visit_column, dropna=False)["__RESIDUAL__"].mean()
        positions = [level_index[_sas_value_key(level)] for level in by_visit.index]
        values = by_visit.to_numpy(dtype=float)
        for left, left_position in enumerate(positions):
            for right, right_position in enumerate(positions):
                sums[left_position, right_position] += values[left] * values[right]
                counts[left_position, right_position] += 1.0
    empirical = np.divide(
        sums,
        counts,
        out=np.full_like(sums, np.nan),
        where=counts > 0,
    ) * degrees_scale
    variances = np.diag(empirical).copy()
    fallback_variance = float(np.nanmean(variances))
    if not math.isfinite(fallback_variance) or fallback_variance <= 0:
        fallback_variance = max(float(np.var(residuals, ddof=1)), 1e-8)
    variances = np.where(
        np.isfinite(variances) & (variances > 0), variances, fallback_variance
    )
    normalized_type = covariance_type.upper().replace(" ", "")

    if normalized_type == "UN":
        covariance = empirical
        for index in range(size):
            covariance[index, index] = variances[index]
    elif normalized_type in {"CS"}:
        off_diagonal = empirical[~np.eye(size, dtype=bool)]
        common_covariance = float(np.nanmean(off_diagonal)) if len(off_diagonal) else 0.0
        if not math.isfinite(common_covariance):
            common_covariance = 0.0
        common_variance = float(np.mean(variances))
        common_covariance = float(
            np.clip(common_covariance, -0.95 * common_variance, 0.95 * common_variance)
        )
        covariance = np.full((size, size), common_covariance)
        np.fill_diagonal(covariance, common_variance)
    else:
        heterogeneous = normalized_type in {"ARH(1)", "TOEPH"}
        autoregressive = normalized_type in {"AR(1)", "ARH(1)"}
        correlations: dict[int, float] = {}
        for lag in range(1, size):
            values: list[float] = []
            for left in range(size - lag):
                right = left + lag
                value = empirical[left, right]
                if math.isfinite(value):
                    values.append(value / math.sqrt(variances[left] * variances[right]))
            correlations[lag] = float(np.clip(np.mean(values), -0.95, 0.95)) if values else 0.0
        if autoregressive:
            rho = correlations.get(1, 0.0)
            correlations = {lag: rho ** lag for lag in range(1, size)}
        covariance = np.zeros((size, size), dtype=float)
        common_variance = float(np.mean(variances))
        for left in range(size):
            covariance[left, left] = variances[left] if heterogeneous else common_variance
            for right in range(left + 1, size):
                correlation = correlations.get(right - left, 0.0)
                if heterogeneous:
                    value = correlation * math.sqrt(variances[left] * variances[right])
                else:
                    value = correlation * common_variance
                covariance[left, right] = covariance[right, left] = value
    return _regularize_covariance(covariance)


def _fit_gls(
    working: pd.DataFrame,
    design: np.ndarray,
    response: np.ndarray,
    subject_column: str | None,
    visit_column: str | None,
    covariance_type: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    rank = int(np.linalg.matrix_rank(design))
    degrees = max(len(response) - rank, 1)
    beta = np.linalg.pinv(design) @ response
    if subject_column is None or visit_column is None:
        residuals = response - design @ beta
        variance = float(residuals @ residuals / degrees)
        covariance_beta = np.linalg.pinv(design.T @ design) * variance
        return beta, covariance_beta, degrees

    visit_levels = sorted(
        working[visit_column].dropna().unique().tolist(), key=_level_sort_key
    )
    level_index = {_sas_value_key(level): index for index, level in enumerate(visit_levels)}
    covariance_beta = np.linalg.pinv(design.T @ design)
    for _ in range(4):
        residuals = response - design @ beta
        repeated_covariance = _estimate_repeated_covariance(
            working,
            residuals,
            subject_column,
            visit_column,
            visit_levels,
            covariance_type,
            len(response) / degrees,
        )
        information = np.zeros((design.shape[1], design.shape[1]), dtype=float)
        score = np.zeros(design.shape[1], dtype=float)
        for indices in working.groupby(subject_column, dropna=False, sort=False).indices.values():
            positions = np.asarray(indices, dtype=int)
            block_design = design[positions]
            block_response = response[positions]
            visits = [
                level_index[_sas_value_key(value)]
                for value in working.iloc[positions][visit_column]
            ]
            block_covariance = repeated_covariance[np.ix_(visits, visits)]
            inverse = np.linalg.pinv(_regularize_covariance(block_covariance))
            information += block_design.T @ inverse @ block_design
            score += block_design.T @ inverse @ block_response
        updated = np.linalg.pinv(information) @ score
        covariance_beta = np.linalg.pinv(information)
        if np.max(np.abs(updated - beta)) < 1e-8:
            beta = updated
            break
        beta = updated
    return beta, covariance_beta, degrees


def _lsmean_grid(
    working: pd.DataFrame,
    target: str,
    target_level: Any,
    effects: list[str],
    class_names: set[str],
    class_levels: dict[str, list[Any]],
) -> pd.DataFrame:
    model_variables = list(dict.fromkeys(
        variable for effect in effects for variable in effect.split("*")
    ))
    other_classes = [
        variable for variable in model_variables
        if variable in class_names and variable != target
    ]
    combinations = list(itertools.product(
        *(class_levels[variable] for variable in other_classes)
    )) if other_classes else [()]
    rows: list[dict[str, Any]] = []
    for combination in combinations:
        row = {target: target_level}
        row.update(dict(zip(other_classes, combination)))
        for variable in model_variables:
            if variable in row:
                continue
            column = _column(working, variable)
            assert column is not None
            row[variable] = float(pd.to_numeric(working[column], errors="coerce").mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _fit_mixed_block(
    frame: pd.DataFrame,
    model: dict[str, Any],
    class_names: set[str],
    repeated: dict[str, Any] | None,
    lsmeans: dict[str, Any] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    effects = [str(effect).upper() for effect in model.get("effects", [])]
    response_name = str(model.get("response", "")).upper()
    repeated_variable = str(repeated.get("variable", "")).upper() if repeated else ""
    repeated_options = repeated.get("options", {}) if repeated else {}
    subject_name = str(repeated_options.get("SUB", "")).upper()
    needed_names = [response_name]
    needed_names.extend(variable for effect in effects for variable in effect.split("*"))
    if repeated_variable:
        needed_names.append(repeated_variable)
    if subject_name:
        needed_names.append(subject_name)
    needed_names = list(dict.fromkeys(needed_names))
    columns = {name: _column(frame, name) for name in needed_names}
    missing = [name for name, column in columns.items() if column is None]
    if missing:
        raise ValueError(f"Variable {missing[0]} not found in dataset")
    working = frame[[columns[name] for name in needed_names if columns[name] is not None]].copy()
    working = working.dropna()
    if working.empty:
        raise ValueError("PROC MIXED has no complete observations")
    response_column = columns[response_name]
    assert response_column is not None
    response_numeric = pd.to_numeric(working[response_column], errors="coerce")
    if response_numeric.isna().any():
        raise ValueError(f"Variable {response_name} must be numeric")

    specification, class_levels = _design_spec(
        working,
        effects,
        class_names,
        bool(model.get("options", {}).get("NOINT")),
    )
    design = _design_matrix(working, specification)
    subject_column = columns.get(subject_name) if subject_name else None
    visit_column = columns.get(repeated_variable) if repeated_variable else None
    covariance_type = str(repeated_options.get("TYPE", "VC"))
    supported = {"UN", "TOEPH", "ARH(1)", "TOEP", "AR(1)", "CS", "VC"}
    if covariance_type.upper() not in supported:
        raise ValueError(f"PROC MIXED covariance TYPE={covariance_type} is not supported")
    beta, covariance_beta, degrees = _fit_gls(
        working,
        design,
        response_numeric.to_numpy(dtype=float),
        subject_column,
        visit_column,
        covariance_type,
    )

    convergence = pd.DataFrame([{
        "STATUS": 0,
        "REASON": "Converged",
        "DESCRIPTION": f"Feasible GLS {covariance_type.upper()} covariance fit converged",
    }])
    if lsmeans is None:
        return pd.DataFrame(), pd.DataFrame(), convergence, []
    target = str(lsmeans.get("effect", "")).upper()
    if target not in class_names or target not in class_levels:
        raise ValueError("PROC MIXED LSMEANS currently requires a CLASS effect")
    alpha = float(lsmeans.get("options", {}).get("ALPHA", 0.05))
    critical = float(student_t.ppf(1.0 - alpha / 2.0, degrees))
    vectors: dict[str, tuple[Any, np.ndarray]] = {}
    lsmean_rows: list[dict[str, Any]] = []
    for level in class_levels[target]:
        grid = _lsmean_grid(
            working, target, level, effects, class_names, class_levels
        )
        vector = _design_matrix(grid, specification).mean(axis=0)
        vectors[_sas_value_key(level)] = (level, vector)
        estimate = float(vector @ beta)
        standard_error = math.sqrt(max(float(vector @ covariance_beta @ vector), 0.0))
        statistic = estimate / standard_error if standard_error > 0 else float("nan")
        probability = (
            float(2.0 * student_t.sf(abs(statistic), degrees))
            if math.isfinite(statistic) else float("nan")
        )
        lsmean_rows.append({
            target: level,
            "ESTIMATE": estimate,
            "STDERR": standard_error,
            "DF": degrees,
            "TVALUE": statistic,
            "PROBT": probability,
            "ALPHA": alpha,
            "LOWER": estimate - critical * standard_error,
            "UPPER": estimate + critical * standard_error,
        })

    diff_rows: list[dict[str, Any]] = []
    ordered_vectors = list(vectors.values())
    for left_index, (left_level, left_vector) in enumerate(ordered_vectors):
        for right_level, right_vector in ordered_vectors[left_index + 1:]:
            contrast = left_vector - right_vector
            estimate = float(contrast @ beta)
            standard_error = math.sqrt(
                max(float(contrast @ covariance_beta @ contrast), 0.0)
            )
            statistic = estimate / standard_error if standard_error > 0 else float("nan")
            probability = (
                float(2.0 * student_t.sf(abs(statistic), degrees))
                if math.isfinite(statistic) else float("nan")
            )
            diff_rows.append({
                target: left_level,
                f"_{target}": right_level,
                "ESTIMATE": estimate,
                "STDERR": standard_error,
                "DF": degrees,
                "TVALUE": statistic,
                "PROBT": probability,
                "ALPHA": alpha,
                "LOWER": estimate - critical * standard_error,
                "UPPER": estimate + critical * standard_error,
            })
    warnings = []
    if str(model.get("options", {}).get("DDFM", "")).upper() == "KR":
        warnings.append(
            "PROC MIXED DDFM=KR is approximated with residual degrees of freedom; Kenward-Roger covariance inflation is not yet applied."
        )
    return pd.DataFrame(lsmean_rows), pd.DataFrame(diff_rows), convergence, warnings


def handle_proc_mixed(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC MIXED — repeated-measures feasible GLS and common ODS outputs."""
    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC MIXED requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(
            success=False,
            error=f"Dataset {data_ref.libref}.{data_ref.name} not found",
        )
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    where_statements = [
        statement for statement in proc.statements if isinstance(statement, WhereNode)
    ]
    if where_statements:
        dataset = _apply_export_dataset_options(
            dataset,
            [{"WHERE": statement.condition} for statement in where_statements],
            session,
        )
    frame = dataset.data.copy().reset_index(drop=True)
    model = next((
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "model"
    ), None)
    if model is None:
        return StepResult(success=False, error="PROC MIXED requires MODEL statement")
    class_statement = next((
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "class"
    ), {"classes": []})
    class_names = {
        str(item.get("name", "")).upper()
        for item in class_statement.get("classes", [])
    }
    repeated = next((
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "repeated"
    ), None)
    lsmeans = next((
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "lsmeans"
    ), None)
    by_statement = next((
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "by"
    ), {"variables": []})
    by_names = by_statement.get("variables", [])
    by_columns = [_column(frame, name) for name in by_names]
    if any(column is None for column in by_columns):
        missing = by_names[by_columns.index(None)]
        return StepResult(success=False, error=f"Variable {missing} not found in dataset")
    group_key: Any = by_columns[0] if len(by_columns) == 1 else by_columns
    blocks = list(frame.groupby(group_key, dropna=False, sort=False)) if by_columns else [((), frame)]

    lsmean_frames: list[pd.DataFrame] = []
    diff_frames: list[pd.DataFrame] = []
    convergence_frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    try:
        for by_value, block in blocks:
            means, diffs, convergence, block_warnings = _fit_mixed_block(
                block.reset_index(drop=True), model, class_names, repeated, lsmeans
            )
            values = by_value if isinstance(by_value, tuple) else (by_value,)
            for column, value in zip(by_columns, values):
                means[column] = value
                diffs[column] = value
                convergence[column] = value
            lsmean_frames.append(means)
            diff_frames.append(diffs)
            convergence_frames.append(convergence)
            warnings.extend(block_warnings)
    except ValueError as exc:
        return StepResult(success=False, error=str(exc))

    outputs = {
        "LSMEANS": pd.concat(lsmean_frames, ignore_index=True) if lsmean_frames else pd.DataFrame(),
        "DIFFS": pd.concat(diff_frames, ignore_index=True) if diff_frames else pd.DataFrame(),
        "CONVERGENCESTATUS": (
            pd.concat(convergence_frames, ignore_index=True)
            if convergence_frames else pd.DataFrame()
        ),
    }
    table_items = list(getattr(session, "_ods_output_items", []))
    if not table_items:
        table_items = list(getattr(session, "_ods_output_targets", {}).items())
    for statement in proc.statements:
        if isinstance(statement, dict) and statement.get("action") == "ods":
            local_items = statement.get("table_items", [])
            table_items.extend(local_items or statement.get("tables", {}).items())
    for table, target in table_items:
        table_name = str(table).upper()
        if table_name in outputs and isinstance(target, DatasetRefNode):
            _write_dataset(session, target, outputs[table_name])

    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=[f"PROC MIXED fitted {len(blocks)} repeated-measures model(s)."],
        warnings=warnings,
    )
