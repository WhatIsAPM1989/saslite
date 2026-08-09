"""Generalized linear-model PROC handlers."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize
from scipy.special import expit
from scipy.stats import chi2, norm

from saslite.ast.data_step import DatasetRefNode, WhereNode
from saslite.ast.proc import ProcNode
from saslite.diagnostics.reporter import Reporter
from saslite.executor.proc.registry import _apply_export_dataset_options
from saslite.executor.proc.survival import (
    _column,
    _level_sort_key,
    _resolve_reference,
    _safe_exp,
    _sas_value_key,
    _write_dataset,
)
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session


def _logistic_objective(
    design: np.ndarray,
    response: np.ndarray,
) -> tuple[Callable[[np.ndarray], float], Callable[[np.ndarray], np.ndarray]]:
    def objective(beta: np.ndarray) -> float:
        eta = design @ np.asarray(beta, dtype=float)
        return float(np.sum(np.logaddexp(0.0, eta) - response * eta))

    def gradient(beta: np.ndarray) -> np.ndarray:
        eta = design @ np.asarray(beta, dtype=float)
        return design.T @ (expit(eta) - response)

    return objective, gradient


def _profile_interval(
    estimate: np.ndarray,
    covariance: np.ndarray,
    objective: Callable[[np.ndarray], float],
    index: int,
    alpha: float,
) -> tuple[float, float]:
    """Profile-likelihood interval for one component of a fitted vector."""
    estimate = np.asarray(estimate, dtype=float)
    optimum = float(objective(estimate))
    target = float(chi2.ppf(1.0 - alpha, 1))
    standard_error = math.sqrt(max(float(covariance[index, index]), 0.0))
    nuisance = np.array([item for item in range(len(estimate)) if item != index])

    def profiled(value: float) -> float:
        if len(nuisance) == 0:
            candidate = np.array([value], dtype=float)
            return float(objective(candidate))

        def reduced(values: np.ndarray) -> float:
            candidate = estimate.copy()
            candidate[index] = value
            candidate[nuisance] = values
            return float(objective(candidate))

        result = minimize(
            reduced,
            estimate[nuisance],
            method="BFGS",
            options={"gtol": 1e-9, "maxiter": 300},
        )
        return float(result.fun)

    def equation(value: float) -> float:
        return 2.0 * (profiled(value) - optimum) - target

    initial_step = max(standard_error, 0.25)

    def boundary(direction: float) -> float:
        inner = float(estimate[index])
        outer = inner + direction * initial_step
        for _ in range(30):
            value = equation(outer)
            if math.isfinite(value) and value >= 0:
                low, high = sorted((inner, outer))
                return float(brentq(equation, low, high, maxiter=200))
            outer = float(estimate[index]) + 2.0 * (outer - float(estimate[index]))
        return float("nan")

    return boundary(-1.0), boundary(1.0)


def _fit_genmod_block(
    frame: pd.DataFrame,
    model: dict[str, Any],
    classes: dict[str, dict[str, Any]],
    estimates: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    options = model.get("options", {})
    distribution = str(options.get("DIST", "BINOMIAL")).upper()
    link = str(options.get("LINK", "LOGIT")).upper()
    if distribution not in {"BIN", "BINOMIAL"} or link != "LOGIT":
        raise ValueError(
            "PROC GENMOD currently supports only DIST=BINOMIAL LINK=LOGIT"
        )

    response_name = str(model.get("response", "")).upper()
    response_column = _column(frame, response_name)
    if response_column is None:
        raise ValueError(f"Variable {response_name} not found in dataset")
    predictor_names = [str(name).upper() for name in model.get("predictors", [])]
    predictor_columns = {name: _column(frame, name) for name in predictor_names}
    missing = [name for name, column in predictor_columns.items() if column is None]
    if missing:
        raise ValueError(f"Variable {missing[0]} not found in dataset")

    needed = [response_column]
    needed.extend(column for column in predictor_columns.values() if column is not None)
    working = frame[needed].copy().dropna()
    if working.empty:
        raise ValueError("PROC GENMOD has no complete observations")
    response_levels = sorted(
        working[response_column].unique().tolist(), key=_level_sort_key
    )
    if len(response_levels) != 2:
        raise ValueError(
            "PROC GENMOD binomial response must have exactly 2 observed levels"
        )
    requested_event = model.get("event")
    event_level = (
        _resolve_reference(response_levels, requested_event)
        if requested_event is not None
        else response_levels[0]
    )
    if requested_event is not None and not any(
        _sas_value_key(level).upper()
        == str(requested_event).strip().strip("'\"").upper()
        for level in response_levels
    ):
        raise ValueError(
            f"PROC GENMOD EVENT='{requested_event}' is not a response level"
        )
    response = (
        working[response_column].map(_sas_value_key) == _sas_value_key(event_level)
    ).to_numpy(dtype=float)

    design_columns: list[np.ndarray] = [np.ones(len(working), dtype=float)]
    coefficient_info: list[dict[str, Any]] = [
        {"variable": "INTERCEPT", "level": None, "reference": None}
    ]
    class_levels: dict[str, list[Any]] = {}
    for predictor in predictor_names:
        column = predictor_columns[predictor]
        assert column is not None
        class_definition = classes.get(predictor)
        if class_definition is not None:
            levels = sorted(working[column].unique().tolist(), key=_level_sort_key)
            class_levels[predictor] = levels
            if len(levels) < 2:
                continue
            reference = _resolve_reference(levels, class_definition.get("REF", "LAST"))
            for level in levels:
                if _sas_value_key(level) == _sas_value_key(reference):
                    continue
                design_columns.append(
                    (
                        working[column].map(_sas_value_key)
                        == _sas_value_key(level)
                    ).to_numpy(dtype=float)
                )
                coefficient_info.append(
                    {"variable": predictor, "level": level, "reference": reference}
                )
        else:
            numeric = pd.to_numeric(working[column], errors="coerce")
            if numeric.isna().any():
                raise ValueError(
                    f"Variable {predictor} must be numeric or listed in CLASS"
                )
            design_columns.append(numeric.to_numpy(dtype=float))
            coefficient_info.append(
                {"variable": predictor, "level": None, "reference": None}
            )

    design = np.column_stack(design_columns)
    objective, gradient = _logistic_objective(design, response)
    result = minimize(
        objective,
        np.zeros(design.shape[1], dtype=float),
        jac=gradient,
        method="BFGS",
        options={"gtol": 1e-9, "maxiter": 500},
    )
    beta = np.asarray(result.x, dtype=float)
    if not np.all(np.isfinite(beta)):
        raise ValueError("PROC GENMOD failed to estimate finite coefficients")
    if not result.success and np.linalg.norm(gradient(beta), ord=np.inf) > 1e-5:
        warnings.append(f"PROC GENMOD convergence warning: {result.message}")

    fitted = expit(design @ beta)
    weights = fitted * (1.0 - fitted)
    information = design.T @ (design * weights[:, None])
    rank = int(np.linalg.matrix_rank(information))
    if rank < design.shape[1]:
        warnings.append(
            "PROC GENMOD information matrix is singular; generalized-inverse standard errors were used."
        )
    covariance = np.linalg.pinv(information)
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    alpha = float(options.get("ALPHA", 0.05))
    z_value = float(norm.ppf(1.0 - alpha / 2.0))
    wants_profile = bool(options.get("LRCI"))

    parameter_rows: list[dict[str, Any]] = []
    for index, info in enumerate(coefficient_info):
        value = float(beta[index])
        standard_error = float(standard_errors[index])
        statistic = (
            (value / standard_error) ** 2
            if standard_error > 0
            else float("nan")
        )
        lower_wald = value - z_value * standard_error
        upper_wald = value + z_value * standard_error
        lower_lr, upper_lr = lower_wald, upper_wald
        if wants_profile:
            lower_lr, upper_lr = _profile_interval(
                beta, covariance, objective, index, alpha
            )
        parameter_rows.append(
            {
                "PARAMETER": (
                    "Intercept" if info["variable"] == "INTERCEPT" else info["variable"]
                ),
                "LEVEL1": "" if info["level"] is None else str(info["level"]),
                "CLASSVAL0": "" if info["level"] is None else str(info["level"]),
                "DF": 1,
                "ESTIMATE": value,
                "STDERR": standard_error,
                "WALDCHISQ": statistic,
                "CHISQ": statistic,
                "PROBCHISQ": (
                    float(chi2.sf(statistic, 1))
                    if math.isfinite(statistic)
                    else float("nan")
                ),
                "LOWERWALDCL": lower_wald,
                "UPPERWALDCL": upper_wald,
                "LOWERLRCL": lower_lr,
                "UPPERLRCL": upper_lr,
            }
        )

    model_anova_rows: list[dict[str, Any]] = []
    full_negative_log_likelihood = float(objective(beta))
    for predictor in predictor_names:
        effect_indices = [
            index
            for index, info in enumerate(coefficient_info)
            if info["variable"] == predictor
        ]
        if not effect_indices:
            continue
        keep_indices = [
            index for index in range(design.shape[1]) if index not in effect_indices
        ]
        reduced_design = design[:, keep_indices]
        reduced_objective, reduced_gradient = _logistic_objective(
            reduced_design, response
        )
        reduced_result = minimize(
            reduced_objective,
            beta[keep_indices],
            jac=reduced_gradient,
            method="BFGS",
            options={"gtol": 1e-9, "maxiter": 500},
        )
        statistic = max(
            0.0,
            2.0 * (
                float(reduced_result.fun) - full_negative_log_likelihood
            ),
        )
        degrees = len(effect_indices)
        model_anova_rows.append(
            {
                "SOURCE": predictor,
                "DF": degrees,
                "CHISQ": statistic,
                "LRCHISQ": statistic,
                "PROBCHISQ": float(chi2.sf(statistic, degrees)),
            }
        )

    estimate_rows: list[dict[str, Any]] = []
    for request in estimates:
        variable = str(request.get("variable", "")).upper()
        coefficients = [float(value) for value in request.get("coefficients", [])]
        contrast = np.zeros(len(beta), dtype=float)
        matching = [
            (index, info)
            for index, info in enumerate(coefficient_info)
            if info["variable"] == variable
        ]
        if variable in class_levels:
            levels = class_levels[variable]
            if len(coefficients) == len(levels):
                coefficient_by_level = {
                    _sas_value_key(level): coefficient
                    for level, coefficient in zip(levels, coefficients)
                }
                for index, info in matching:
                    contrast[index] = coefficient_by_level[_sas_value_key(info["level"])]
            elif len(coefficients) == len(matching):
                for (index, _), coefficient in zip(matching, coefficients):
                    contrast[index] = coefficient
            else:
                raise ValueError(
                    f"PROC GENMOD ESTIMATE for {variable} has {len(coefficients)} coefficients; expected {len(levels)}"
                )
        elif len(matching) == 1 and len(coefficients) == 1:
            contrast[matching[0][0]] = coefficients[0]
        else:
            raise ValueError(
                f"PROC GENMOD ESTIMATE effect {variable} is not estimable"
            )

        value = float(contrast @ beta)
        variance = float(contrast @ covariance @ contrast)
        standard_error = math.sqrt(max(variance, 0.0))
        statistic = (
            (value / standard_error) ** 2
            if standard_error > 0
            else float("nan")
        )
        request_alpha = float(request.get("options", {}).get("ALPHA", alpha))
        request_z = float(norm.ppf(1.0 - request_alpha / 2.0))
        lower = value - request_z * standard_error
        upper = value + request_z * standard_error
        nonzero = np.flatnonzero(np.abs(contrast) > 1e-12)
        if wants_profile and len(nonzero) == 1:
            index = int(nonzero[0])
            component_lower, component_upper = _profile_interval(
                beta, covariance, objective, index, request_alpha
            )
            scale = float(contrast[index])
            limits = sorted((scale * component_lower, scale * component_upper))
            lower, upper = limits[0], limits[1]
        estimate_rows.append(
            {
                "LABEL": request.get("label", variable),
                "DF": 1,
                "LBETAESTIMATE": value,
                "LBETALOWERCL": lower,
                "LBETAUPPERCL": upper,
                "STDERR": standard_error,
                "WALDCHISQ": statistic,
                "PROBCHISQ": (
                    float(chi2.sf(statistic, 1))
                    if math.isfinite(statistic)
                    else float("nan")
                ),
                "EXPESTIMATE": _safe_exp(value),
                "LOWEREXP": _safe_exp(lower),
                "UPPEREXP": _safe_exp(upper),
            }
        )

    return (
        pd.DataFrame(estimate_rows),
        pd.DataFrame(parameter_rows),
        pd.DataFrame(model_anova_rows),
        warnings,
    )


def handle_proc_genmod(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC GENMOD — binomial generalized linear models with a logit link."""
    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC GENMOD requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(
            success=False,
            error=f"Dataset {data_ref.libref}.{data_ref.name} not found",
        )
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    where_statements = [
        statement
        for statement in proc.statements
        if isinstance(statement, WhereNode)
    ]
    if where_statements:
        dataset = _apply_export_dataset_options(
            dataset,
            [{"WHERE": statement.condition} for statement in where_statements],
            session,
        )
    frame = dataset.data.copy()

    model = next(
        (
            statement
            for statement in proc.statements
            if isinstance(statement, dict) and statement.get("action") == "model"
        ),
        None,
    )
    if model is None:
        return StepResult(success=False, error="PROC GENMOD requires MODEL statement")
    class_statement = next(
        (
            statement
            for statement in proc.statements
            if isinstance(statement, dict) and statement.get("action") == "class"
        ),
        {"classes": []},
    )
    classes = {
        item["name"]: item.get("options", {})
        for item in class_statement.get("classes", [])
    }
    estimate_requests = [
        statement
        for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "estimate"
    ]
    by_statement = next(
        (
            statement
            for statement in proc.statements
            if isinstance(statement, dict) and statement.get("action") == "by"
        ),
        {"variables": []},
    )
    by_names = by_statement.get("variables", [])
    by_columns = [_column(frame, name) for name in by_names]
    if any(column is None for column in by_columns):
        missing = by_names[by_columns.index(None)]
        return StepResult(success=False, error=f"Variable {missing} not found in dataset")
    if by_columns:
        group_key: Any = by_columns[0] if len(by_columns) == 1 else by_columns
        blocks = list(frame.groupby(group_key, dropna=False, sort=False))
    else:
        blocks = [((), frame)]

    estimate_frames: list[pd.DataFrame] = []
    parameter_frames: list[pd.DataFrame] = []
    model_anova_frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    try:
        for by_value, block in blocks:
            (
                estimate_frame,
                parameter_frame,
                model_anova_frame,
                block_warnings,
            ) = _fit_genmod_block(block, model, classes, estimate_requests)
            values = by_value if isinstance(by_value, tuple) else (by_value,)
            for column, value in zip(by_columns, values):
                estimate_frame[column] = value
                parameter_frame[column] = value
                model_anova_frame[column] = value
            estimate_frames.append(estimate_frame)
            parameter_frames.append(parameter_frame)
            model_anova_frames.append(model_anova_frame)
            warnings.extend(block_warnings)
    except ValueError as exc:
        return StepResult(success=False, error=str(exc))

    estimate_output = (
        pd.concat(estimate_frames, ignore_index=True)
        if estimate_frames
        else pd.DataFrame()
    )
    parameter_output = (
        pd.concat(parameter_frames, ignore_index=True)
        if parameter_frames
        else pd.DataFrame()
    )
    model_anova_output = (
        pd.concat(model_anova_frames, ignore_index=True)
        if model_anova_frames
        else pd.DataFrame()
    )
    ods_targets = dict(getattr(session, "_ods_output_targets", {}))
    for statement in proc.statements:
        if isinstance(statement, dict) and statement.get("action") == "ods":
            ods_targets.update(statement.get("tables", {}))
    if isinstance(ods_targets.get("ESTIMATES"), DatasetRefNode):
        _write_dataset(session, ods_targets["ESTIMATES"], estimate_output)
    if isinstance(ods_targets.get("PARAMETERESTIMATES"), DatasetRefNode):
        _write_dataset(
            session, ods_targets["PARAMETERESTIMATES"], parameter_output
        )
    if isinstance(ods_targets.get("MODELANOVA"), DatasetRefNode):
        _write_dataset(session, ods_targets["MODELANOVA"], model_anova_output)

    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=[
            f"PROC GENMOD fitted {len(blocks)} binomial model(s) with a logit link."
        ],
        warnings=warnings,
    )
