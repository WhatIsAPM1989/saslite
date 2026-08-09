"""Interval-censored proportional-hazards support."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import chi2, norm

from saslite.ast.data_step import DatasetRefNode, WhereNode
from saslite.ast.proc import ProcNode
from saslite.diagnostics.reporter import Reporter
from saslite.executor.proc.registry import _apply_export_dataset_options
from saslite.executor.proc.survival import (
    _column,
    _crossing_time,
    _level_sort_key,
    _resolve_reference,
    _safe_exp,
    _sas_value_key,
    _write_dataset,
    handle_proc_phreg,
)
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session


def _piecewise_exposure(time: float, boundaries: np.ndarray) -> np.ndarray:
    widths = np.diff(boundaries)
    return np.minimum(np.maximum(time - boundaries[:-1], 0.0), widths)


def _piecewise_segment(time: float, boundaries: np.ndarray) -> int:
    return min(max(int(np.searchsorted(boundaries[1:], time, side="left")), 0), len(boundaries) - 2)


def _interval_negative_log_likelihood(
    parameters: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    design: np.ndarray,
    strata: np.ndarray,
    boundaries: np.ndarray,
    stratum_count: int,
) -> float:
    interval_count = len(boundaries) - 1
    log_hazards = parameters[: stratum_count * interval_count].reshape(
        stratum_count, interval_count
    )
    hazards = np.exp(np.clip(log_hazards, -30.0, 30.0))
    beta = parameters[stratum_count * interval_count:]
    relative_risk = np.exp(np.clip(design @ beta, -30.0, 30.0))
    total = 0.0
    for index in range(len(left)):
        baseline = hazards[strata[index]]
        left_hazard = float(_piecewise_exposure(left[index], boundaries) @ baseline)
        risk = float(relative_risk[index])
        if not math.isfinite(right[index]):
            total += risk * left_hazard
            continue
        right_hazard = float(_piecewise_exposure(right[index], boundaries) @ baseline)
        if abs(right[index] - left[index]) <= 1e-12:
            segment = _piecewise_segment(right[index], boundaries)
            total += (
                risk * right_hazard
                - math.log(max(risk, 1e-300))
                - math.log(max(float(baseline[segment]), 1e-300))
            )
            continue
        difference = risk * max(right_hazard - left_hazard, 0.0)
        if difference <= 1e-14:
            return float("inf")
        log_probability = -risk * left_hazard + math.log1p(-math.exp(-difference))
        if not math.isfinite(log_probability):
            return float("inf")
        total -= log_probability
    return float(total)


def _fit_interval_block(
    frame: pd.DataFrame,
    model: dict[str, Any],
    classes: dict[str, dict[str, Any]],
    strata_names: list[str],
    hazard_requests: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    left_name = str(model.get("left", "")).upper()
    right_name = str(model.get("right", "")).upper()
    left_column = _column(frame, left_name)
    right_column = _column(frame, right_name)
    if left_column is None or right_column is None:
        missing = left_name if left_column is None else right_name
        raise ValueError(f"Variable {missing} not found in dataset")
    predictor_names = [str(name).upper() for name in model.get("predictors", [])]
    predictor_columns = {name: _column(frame, name) for name in predictor_names}
    missing_predictors = [name for name, column in predictor_columns.items() if column is None]
    if missing_predictors:
        raise ValueError(f"Variable {missing_predictors[0]} not found in dataset")
    strata_columns = [_column(frame, name) for name in strata_names]
    if any(column is None for column in strata_columns):
        missing = strata_names[strata_columns.index(None)]
        raise ValueError(f"Variable {missing} not found in dataset")

    required = [column for column in predictor_columns.values() if column is not None]
    required.extend(column for column in strata_columns if column is not None)
    working = frame[[left_column, right_column, *required]].copy()
    working = working.dropna(subset=required)
    working[left_column] = pd.to_numeric(working[left_column], errors="coerce")
    working[right_column] = pd.to_numeric(working[right_column], errors="coerce")
    working = working[~(working[left_column].isna() & working[right_column].isna())]
    if working.empty:
        raise ValueError("PROC ICPHREG has no usable observations")
    left = working[left_column].fillna(0.0).to_numpy(dtype=float)
    right = working[right_column].fillna(float("inf")).to_numpy(dtype=float)
    if np.any(left < 0) or np.any(np.isfinite(right) & (right < left)):
        raise ValueError("PROC ICPHREG requires 0 <= LTIME <= RTIME")
    if not np.any(np.isfinite(right)):
        raise ValueError("PROC ICPHREG has no observed or interval-censored events")

    design_columns: list[np.ndarray] = []
    coefficient_info: list[dict[str, Any]] = []
    for predictor in predictor_names:
        column = predictor_columns[predictor]
        assert column is not None
        class_definition = classes.get(predictor)
        if class_definition is not None:
            levels = sorted(working[column].dropna().unique().tolist(), key=_level_sort_key)
            if len(levels) < 2:
                continue
            reference = _resolve_reference(levels, class_definition.get("REF", "LAST"))
            for level in levels:
                if _sas_value_key(level) == _sas_value_key(reference):
                    continue
                design_columns.append(
                    (working[column].map(_sas_value_key) == _sas_value_key(level)).to_numpy(dtype=float)
                )
                coefficient_info.append({
                    "variable": predictor,
                    "level": level,
                    "reference": reference,
                })
        else:
            numeric = pd.to_numeric(working[column], errors="coerce")
            if numeric.isna().any():
                raise ValueError(f"Variable {predictor} must be numeric or listed in CLASS")
            design_columns.append(numeric.to_numpy(dtype=float))
            coefficient_info.append({"variable": predictor, "level": None, "reference": None})
    if not design_columns:
        raise ValueError("PROC ICPHREG has no estimable model effects")
    design = np.column_stack(design_columns)

    if strata_columns:
        strata = pd.MultiIndex.from_frame(working[strata_columns]).factorize()[0]
    else:
        strata = np.zeros(len(working), dtype=int)
    stratum_count = int(strata.max()) + 1
    base_option = model.get("options", {}).get("BASE", {})
    interval_count = max(1, int(base_option.get("NINTERVAL", 1)))
    finite_times = np.concatenate((left[np.isfinite(left)], right[np.isfinite(right)]))
    maximum = float(np.max(finite_times))
    if maximum <= 0:
        raise ValueError("PROC ICPHREG requires at least one positive analysis time")
    boundaries = np.linspace(0.0, maximum, interval_count + 1)
    observed_events = int(np.isfinite(right).sum())
    total_time = max(float(np.sum(left)), maximum)
    starting_hazard = max(observed_events / total_time, 1e-4)
    baseline_count = stratum_count * interval_count
    initial = np.concatenate((
        np.full(baseline_count, math.log(starting_hazard)),
        np.zeros(design.shape[1]),
    ))
    objective = lambda values: _interval_negative_log_likelihood(
        np.asarray(values, dtype=float), left, right, design, strata,
        boundaries, stratum_count,
    )
    result = minimize(objective, initial, method="BFGS", options={"maxiter": 1000, "gtol": 1e-7})
    if not np.all(np.isfinite(result.x)):
        raise ValueError("PROC ICPHREG failed to estimate finite coefficients")
    beta = np.asarray(result.x[baseline_count:], dtype=float)
    covariance = np.atleast_2d(np.asarray(result.hess_inv, dtype=float))
    beta_covariance = covariance[baseline_count:, baseline_count:]
    standard_errors = np.sqrt(np.maximum(np.diag(beta_covariance), 0.0))
    warnings: list[str] = []
    if not result.success:
        warnings.append(f"PROC ICPHREG convergence warning: {result.message}")

    parameter_rows: list[dict[str, Any]] = []
    for index, info in enumerate(coefficient_info):
        estimate = float(beta[index])
        standard_error = float(standard_errors[index])
        statistic = (estimate / standard_error) ** 2 if standard_error > 0 else float("nan")
        parameter_rows.append({
            "PARAMETER": info["variable"],
            "CLASSVAL0": "" if info["level"] is None else str(info["level"]),
            "ESTIMATE": estimate,
            "STDERR": standard_error,
            "CHISQ": statistic,
            "PROBCHISQ": float(chi2.sf(statistic, 1)) if math.isfinite(statistic) else float("nan"),
        })

    if not hazard_requests:
        hazard_requests = [{"variable": info["variable"], "label": "", "options": {}}
                           for info in coefficient_info]
    hazard_rows: list[dict[str, Any]] = []
    for request in hazard_requests:
        variable = str(request.get("variable", "")).upper()
        alpha = float(request.get("options", {}).get("ALPHA", 0.05))
        critical = float(norm.ppf(1.0 - alpha / 2.0))
        for index, info in enumerate(coefficient_info):
            if info["variable"] != variable:
                continue
            estimate = float(beta[index])
            standard_error = float(standard_errors[index])
            lower = estimate - critical * standard_error
            upper = estimate + critical * standard_error
            description = request.get("label") or variable
            if info["level"] is not None:
                description = f"{description} {info['level']} vs {info['reference']}"
            hazard_rows.append({
                "DESCRIPTION": description,
                variable: info["level"],
                "HAZARDRATIO": _safe_exp(estimate),
                "WALDLOWER": _safe_exp(lower),
                "WALDUPPER": _safe_exp(upper),
                "PLLOWER": _safe_exp(lower),
                "PLUPPER": _safe_exp(upper),
                "HRLOWERCL": _safe_exp(lower),
                "HRUPPERCL": _safe_exp(upper),
            })
    return pd.DataFrame(hazard_rows), pd.DataFrame(parameter_rows), warnings


def handle_proc_icphreg(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC ICPHREG with a piecewise-exponential baseline hazard."""
    model = next((statement for statement in proc.statements
                  if isinstance(statement, dict) and statement.get("action") == "model"), None)
    if model is None:
        return StepResult(success=False, error="PROC ICPHREG requires MODEL statement")
    if model.get("model_type") == "right_censored":
        equivalent = ProcNode(
            proc_name="PHREG",
            options=proc.options,
            statements=proc.statements,
        )
        return handle_proc_phreg(equivalent, session, reporter)

    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC ICPHREG requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_ref.libref}.{data_ref.name} not found")
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    where_statements = [statement for statement in proc.statements if isinstance(statement, WhereNode)]
    if where_statements:
        dataset = _apply_export_dataset_options(
            dataset,
            [{"WHERE": statement.condition} for statement in where_statements],
            session,
        )
    frame = dataset.data.copy()
    class_statement = next((statement for statement in proc.statements
                            if isinstance(statement, dict) and statement.get("action") == "class"),
                           {"classes": []})
    classes = {item["name"]: item.get("options", {})
               for item in class_statement.get("classes", [])}
    strata_statement = next((statement for statement in proc.statements
                             if isinstance(statement, dict) and statement.get("action") == "strata"),
                            {"variables": []})
    hazard_requests = [statement for statement in proc.statements
                       if isinstance(statement, dict) and statement.get("action") == "hazardratio"]
    try:
        hazards, parameters, warnings = _fit_interval_block(
            frame, model, classes, strata_statement.get("variables", []), hazard_requests
        )
    except ValueError as exc:
        return StepResult(success=False, error=str(exc))

    outputs = {"HAZARDRATIOS": hazards, "PARAMETERESTIMATES": parameters}
    table_items = list(getattr(session, "_ods_output_items", []))
    if not table_items:
        table_items = list(getattr(session, "_ods_output_targets", {}).items())
    for statement in proc.statements:
        if isinstance(statement, dict) and statement.get("action") == "ods":
            table_items.extend(statement.get("table_items", []) or statement.get("tables", {}).items())
    for table, target in table_items:
        table_name = str(table).upper()
        if table_name in outputs and isinstance(target, DatasetRefNode):
            _write_dataset(session, target, outputs[table_name])
    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=["PROC ICPHREG fitted a piecewise-exponential proportional-hazards model."],
        warnings=warnings,
    )


def _turnbull_group(
    frame: pd.DataFrame,
    left_column: str,
    right_column: str,
    alpha: float,
) -> tuple[pd.DataFrame, list[dict[str, float]]]:
    left_series = pd.to_numeric(frame[left_column], errors="coerce")
    right_series = pd.to_numeric(frame[right_column], errors="coerce")
    usable = ~(left_series.isna() & right_series.isna())
    left = left_series[usable].fillna(0.0).to_numpy(dtype=float)
    right = right_series[usable].fillna(float("inf")).to_numpy(dtype=float)
    if len(left) == 0:
        raise ValueError("PROC ICLIFETEST has no usable observations")
    if np.any(left < 0) or np.any(np.isfinite(right) & (right < left)):
        raise ValueError("PROC ICLIFETEST requires 0 <= LTIME <= RTIME")
    finite_support = sorted(set(float(value) for value in right if math.isfinite(value)))
    if not finite_support:
        raise ValueError("PROC ICLIFETEST has no finite interval endpoints")
    support = np.asarray([*finite_support, float("inf")], dtype=float)
    compatibility = np.zeros((len(left), len(support)), dtype=bool)
    for index, (lower, upper) in enumerate(zip(left, right)):
        if not math.isfinite(upper):
            compatibility[index] = support > lower
        elif abs(upper - lower) <= 1e-12:
            compatibility[index] = np.isclose(support, upper)
        else:
            compatibility[index] = (support > lower) & (support <= upper)
        if not compatibility[index].any():
            nearest = int(np.argmin(np.abs(support[:-1] - upper)))
            compatibility[index, nearest] = True

    probabilities = np.full(len(support), 1.0 / len(support), dtype=float)
    for _ in range(10000):
        expected = np.zeros(len(support), dtype=float)
        for compatible in compatibility:
            denominator = float(probabilities[compatible].sum())
            expected[compatible] += probabilities[compatible] / max(denominator, 1e-300)
        updated = expected / len(left)
        if np.max(np.abs(updated - probabilities)) < 1e-10:
            probabilities = updated
            break
        probabilities = updated

    critical = float(norm.ppf(1.0 - alpha / 2.0))
    rows: list[dict[str, float]] = [{
        "TIME": 0.0,
        "SURVIVAL": 1.0,
        "SDF_LCL": 1.0,
        "SDF_UCL": 1.0,
    }]
    for time in finite_support:
        survival = float(probabilities[support > time].sum())
        standard_error = math.sqrt(max(survival * (1.0 - survival) / len(left), 0.0))
        rows.append({
            "TIME": time,
            "SURVIVAL": survival,
            "SDF_LCL": max(0.0, survival - critical * standard_error),
            "SDF_UCL": min(1.0, survival + critical * standard_error),
        })
    curve = pd.DataFrame(rows)
    event_curve = curve[curve["TIME"] > 0]
    times = event_curve["TIME"].tolist()
    values = event_curve["SURVIVAL"].tolist()
    lower_values = event_curve["SDF_LCL"].tolist()
    upper_values = event_curve["SDF_UCL"].tolist()
    quartiles: list[dict[str, float]] = []
    for percent in (25.0, 50.0, 75.0):
        threshold = 1.0 - percent / 100.0
        quartiles.append({
            "PERCENT": percent,
            "ESTIMATE": _crossing_time(times, values, threshold),
            "LOWERLIMIT": _crossing_time(times, lower_values, threshold),
            "UPPERLIMIT": _crossing_time(times, upper_values, threshold),
        })
    return curve, quartiles


def handle_proc_iclifetest(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC ICLIFETEST — Turnbull EM estimates for interval-censored data."""
    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC ICLIFETEST requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_ref.libref}.{data_ref.name} not found")
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    where_statements = [statement for statement in proc.statements if isinstance(statement, WhereNode)]
    if where_statements:
        dataset = _apply_export_dataset_options(
            dataset,
            [{"WHERE": statement.condition} for statement in where_statements],
            session,
        )
    frame = dataset.data.copy()
    time_statement = next((statement for statement in proc.statements
                           if isinstance(statement, dict) and statement.get("action") == "time"), None)
    if time_statement is None:
        return StepResult(success=False, error="PROC ICLIFETEST requires TIME statement")
    left_name = str(time_statement.get("left", "")).upper()
    right_name = str(time_statement.get("right", "")).upper()
    left_column = _column(frame, left_name)
    right_column = _column(frame, right_name)
    if left_column is None or right_column is None:
        missing = left_name if left_column is None else right_name
        return StepResult(success=False, error=f"Variable {missing} not found in dataset")
    by_statement = next((statement for statement in proc.statements
                         if isinstance(statement, dict) and statement.get("action") == "by"),
                        {"variables": []})
    by_names = by_statement.get("variables", [])
    by_columns = [_column(frame, name) for name in by_names]
    if any(column is None for column in by_columns):
        missing = by_names[by_columns.index(None)]
        return StepResult(success=False, error=f"Variable {missing} not found in dataset")
    group_key: Any = by_columns[0] if len(by_columns) == 1 else by_columns
    blocks = list(frame.groupby(group_key, dropna=False, sort=False)) if by_columns else [((), frame)]
    alpha = float(proc.options.get("ALPHA", 0.05))
    curves: list[pd.DataFrame] = []
    quartile_rows: list[dict[str, Any]] = []
    try:
        for group_value, block in blocks:
            curve, quartiles = _turnbull_group(block, left_column, right_column, alpha)
            values = group_value if isinstance(group_value, tuple) else (group_value,)
            labels = dict(zip(by_columns, values))
            for column, value in labels.items():
                curve[column] = value
            curves.append(curve)
            quartile_rows.extend({**labels, **row} for row in quartiles)
    except ValueError as exc:
        return StepResult(success=False, error=str(exc))
    outputs = {
        "SURVIVALPLOT": pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(),
        "QUARTILES": pd.DataFrame(quartile_rows),
    }
    table_items = list(getattr(session, "_ods_output_items", []))
    if not table_items:
        table_items = list(getattr(session, "_ods_output_targets", {}).items())
    for statement in proc.statements:
        if isinstance(statement, dict) and statement.get("action") == "ods":
            table_items.extend(statement.get("table_items", []) or statement.get("tables", {}).items())
    for table, target in table_items:
        table_name = str(table).upper()
        if table_name in outputs and isinstance(target, DatasetRefNode):
            _write_dataset(session, target, outputs[table_name])
    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=[f"PROC ICLIFETEST computed Turnbull estimates for {len(blocks)} BY group(s)."],
    )
