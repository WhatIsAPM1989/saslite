"""Survival-analysis PROC handlers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize
from scipy.stats import chi2, norm

from saslite.ast.data_step import DatasetRefNode, WhereNode
from saslite.ast.proc import ProcNode
from saslite.executor.proc.registry import _apply_export_dataset_options
from saslite.runtime.dataset import Dataset
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session
from saslite.diagnostics.reporter import Reporter


def handle_ods(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """Track ODS OUTPUT destinations; presentation-only ODS is a no-op."""
    action = str(proc.options.get("ACTION", "")).upper()
    if not hasattr(session, "_ods_output_targets"):
        session._ods_output_targets = {}
    if action == "OUTPUT":
        session._ods_output_targets.update(proc.options.get("TABLES", {}))
    elif action == "OUTPUT_CLOSE":
        session._ods_output_targets.clear()
    return StepResult(success=True)


def _write_dataset(
    session: Session,
    target: DatasetRefNode,
    frame: pd.DataFrame,
) -> None:
    dataset = Dataset.from_dataframe(
        frame,
        name=target.name,
        libref=target.libref,
    )
    dataset = _apply_export_dataset_options(dataset, target.options, session)
    session.put_dataset(target.libref, target.name, dataset)


def _column(frame: pd.DataFrame, name: str) -> str | None:
    mapping = {str(column).upper(): str(column) for column in frame.columns}
    return mapping.get(name.upper())


def _sas_value_key(value: Any) -> str:
    if pd.isna(value):
        return "."
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if number.is_integer():
            return str(int(number))
    return str(value).strip()


def _safe_exp(value: float) -> float:
    return math.exp(max(-700.0, min(700.0, value)))


def _level_sort_key(value: Any) -> tuple[int, Any]:
    if isinstance(value, (int, float, np.integer, np.floating)):
        return 0, float(value)
    return 1, str(value)


def _at_risk_times(plot: Any) -> list[float]:
    if not isinstance(plot, dict):
        return []
    pieces = [str(piece) for piece in plot.get("pieces", [])]
    upper = [piece.upper() for piece in pieces]
    if "ATRISK" not in upper:
        return []
    numbers: list[float] = []
    for piece in pieces[upper.index("ATRISK") + 1:]:
        try:
            numbers.append(float(piece))
        except ValueError:
            continue
    if not numbers:
        return []
    if len(numbers) < 3:
        return numbers
    start, stop, increment = numbers[:3]
    if increment <= 0:
        return []
    count = int(math.floor((stop - start) / increment + 1e-12))
    return [start + index * increment for index in range(count + 1)]


def _crossing_time(
    times: list[float],
    values: list[float],
    threshold: float,
) -> float:
    for time, value in zip(times, values):
        if not math.isnan(value) and value <= threshold:
            return float(time)
    return float("nan")


def _km_group(
    frame: pd.DataFrame,
    duration_column: str,
    event_column: str,
) -> tuple[pd.DataFrame, list[dict[str, float]]]:
    working = frame[[duration_column, event_column]].copy()
    working[duration_column] = pd.to_numeric(
        working[duration_column], errors="coerce"
    )
    working = working.dropna(subset=[duration_column])
    working = working[working[duration_column] >= 0]

    curve_rows: list[dict[str, float]] = [
        {
            "TIME": 0.0,
            "SURVIVAL": 1.0,
            "SDF_LCL": 1.0,
            "SDF_UCL": 1.0,
            "ATRISK": float(len(working)),
            "EVENT": 0.0,
            "CENSORED": 0.0,
            "TATRISK": float("nan"),
        }
    ]
    survival = 1.0
    greenwood = 0.0
    z_value = float(norm.ppf(0.975))

    for time in sorted(working[duration_column].unique()):
        at_risk = int((working[duration_column] >= time).sum())
        at_time = working[working[duration_column] == time]
        events = int(at_time[event_column].sum())
        censored = int(len(at_time) - events)
        if at_risk and events:
            survival *= 1.0 - events / at_risk
            if at_risk > events:
                greenwood += events / (at_risk * (at_risk - events))

        lower = upper = survival
        if 0.0 < survival < 1.0 and greenwood > 0:
            theta = math.log(-math.log(survival))
            standard_error = math.sqrt(greenwood) / abs(math.log(survival))
            lower = math.exp(-math.exp(theta + z_value * standard_error))
            upper = math.exp(-math.exp(theta - z_value * standard_error))
        elif survival <= 0:
            lower = upper = 0.0

        curve_rows.append(
            {
                "TIME": float(time),
                "SURVIVAL": float(survival),
                "SDF_LCL": float(lower),
                "SDF_UCL": float(upper),
                "ATRISK": float(at_risk),
                "EVENT": float(events),
                "CENSORED": float(censored),
                "TATRISK": float("nan"),
            }
        )

    curve = pd.DataFrame(curve_rows)
    event_curve = curve[curve["TIME"] > 0]
    times = event_curve["TIME"].tolist()
    survival_values = event_curve["SURVIVAL"].tolist()
    lower_values = event_curve["SDF_LCL"].tolist()
    upper_values = event_curve["SDF_UCL"].tolist()
    quartiles: list[dict[str, float]] = []
    for percent in (25.0, 50.0, 75.0):
        threshold = 1.0 - percent / 100.0
        quartiles.append(
            {
                "PERCENT": percent,
                "ESTIMATE": _crossing_time(times, survival_values, threshold),
                "LOWERLIMIT": _crossing_time(times, lower_values, threshold),
                "UPPERLIMIT": _crossing_time(times, upper_values, threshold),
            }
        )
    return curve, quartiles


def _logrank_test(
    frame: pd.DataFrame,
    duration_column: str,
    event_column: str,
    group_columns: list[str],
    adjustment_columns: list[str],
) -> pd.DataFrame:
    columns = [duration_column, event_column, *group_columns, *adjustment_columns]
    working = frame[columns].copy().dropna()
    working[duration_column] = pd.to_numeric(working[duration_column], errors="coerce")
    working = working.dropna(subset=[duration_column])
    if not group_columns or working.empty:
        return pd.DataFrame(
            [{"TEST": "Log-Rank", "CHISQ": float("nan"), "DF": 0, "PROBCHISQ": float("nan")}]
        )

    group_keys = working[group_columns].astype(str).agg("\x1f".join, axis=1)
    levels = sorted(group_keys.unique().tolist())
    if len(levels) < 2:
        return pd.DataFrame(
            [{"TEST": "Log-Rank", "CHISQ": float("nan"), "DF": 0, "PROBCHISQ": float("nan")}]
        )
    group_index = {level: index for index, level in enumerate(levels)}
    observed = np.zeros(len(levels))
    expected = np.zeros(len(levels))
    covariance = np.zeros((len(levels), len(levels)))

    if adjustment_columns:
        adjustment_key: Any = (
            adjustment_columns[0]
            if len(adjustment_columns) == 1
            else adjustment_columns
        )
        adjustment_groups = working.groupby(adjustment_key, dropna=False, sort=False)
    else:
        adjustment_groups = [((), working)]

    for _, block in adjustment_groups:
        block_group_keys = block[group_columns].astype(str).agg("\x1f".join, axis=1)
        for event_time in sorted(block.loc[block[event_column], duration_column].unique()):
            risk_mask = block[duration_column] >= event_time
            event_mask = (block[duration_column] == event_time) & block[event_column]
            risk_total = int(risk_mask.sum())
            event_total = int(event_mask.sum())
            if risk_total == 0 or event_total == 0:
                continue
            risk_counts = np.zeros(len(levels))
            event_counts = np.zeros(len(levels))
            for level, index in group_index.items():
                risk_counts[index] = int((risk_mask & (block_group_keys == level)).sum())
                event_counts[index] = int((event_mask & (block_group_keys == level)).sum())
            proportions = risk_counts / risk_total
            observed += event_counts
            expected += event_total * proportions
            if risk_total > 1:
                factor = event_total * (risk_total - event_total) / (risk_total - 1)
                covariance += factor * (
                    np.diag(proportions) - np.outer(proportions, proportions)
                )

    contrast = observed[:-1] - expected[:-1]
    reduced_covariance = covariance[:-1, :-1]
    degrees = int(np.linalg.matrix_rank(reduced_covariance))
    if degrees:
        statistic = float(contrast @ np.linalg.pinv(reduced_covariance) @ contrast)
        probability = float(chi2.sf(statistic, degrees))
    else:
        statistic = probability = float("nan")
    return pd.DataFrame(
        [{"TEST": "Log-Rank", "CHISQ": statistic, "DF": degrees, "PROBCHISQ": probability}]
    )


def handle_proc_lifetest(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC LIFETEST — Kaplan–Meier estimates and common ODS tables."""
    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC LIFETEST requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(
            success=False,
            error=f"Dataset {data_ref.libref}.{data_ref.name} not found",
        )
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    where_options = [
        {"WHERE": statement.condition}
        for statement in proc.statements
        if isinstance(statement, WhereNode)
    ]
    if where_options:
        dataset = _apply_export_dataset_options(dataset, where_options, session)
    frame = dataset.data.copy()

    duration_name = str(proc.options.get("TIME_VAR", ""))
    censor_name = str(proc.options.get("CENSOR_VAR", ""))
    duration_column = _column(frame, duration_name)
    censor_column = _column(frame, censor_name)
    if duration_column is None or censor_column is None:
        missing = duration_name if duration_column is None else censor_name
        return StepResult(
            success=False,
            error=f"Variable {missing} not found in dataset",
        )

    censor_values = proc.options.get("CENSOR_VALUES", [])
    if not censor_values:
        censor_values = [1]
    normalized_censor = {_sas_value_key(value) for value in censor_values}
    event_column = "__SASLITE_EVENT__"
    frame[event_column] = ~frame[censor_column].map(
        lambda value: _sas_value_key(value) in normalized_censor
    )

    strata_names = [str(name).upper() for name in proc.options.get("STRATA", [])]
    strata_columns = [_column(frame, name) for name in strata_names]
    missing_strata = [
        name for name, column in zip(strata_names, strata_columns) if column is None
    ]
    if missing_strata:
        return StepResult(
            success=False,
            error=f"Variable {missing_strata[0]} not found in dataset",
        )
    actual_strata = [column for column in strata_columns if column is not None]

    if actual_strata:
        group_key: Any = actual_strata[0] if len(actual_strata) == 1 else actual_strata
        groups = list(frame.groupby(group_key, dropna=False, sort=True))
    else:
        groups = [((), frame)]

    curve_frames: list[pd.DataFrame] = []
    quartile_rows: list[dict[str, Any]] = []
    atrisk_times = _at_risk_times(proc.options.get("PLOTS"))
    if not atrisk_times:
        atrisk_times = [float(value) for value in proc.options.get("TIMELIST", [])]

    for stratum_number, (group_value, group_frame) in enumerate(groups, start=1):
        values = group_value if isinstance(group_value, tuple) else (group_value,)
        curve, quartiles = _km_group(group_frame, duration_column, event_column)
        labels = dict(zip(actual_strata, values))
        curve["STRATUMNUM"] = stratum_number
        curve["STRATUM"] = " ".join(str(value) for value in values) if values else "1"
        for column, value in labels.items():
            curve[column] = value

        for at_time in atrisk_times:
            eligible = group_frame[pd.to_numeric(
                group_frame[duration_column], errors="coerce"
            ) >= at_time]
            prior = curve[curve["TIME"] <= at_time]
            probability = float(prior["SURVIVAL"].iloc[-1]) if len(prior) else 1.0
            risk_row: dict[str, Any] = {
                "TIME": float(at_time),
                "SURVIVAL": probability,
                "SDF_LCL": float("nan"),
                "SDF_UCL": float("nan"),
                "ATRISK": float(len(eligible)),
                "EVENT": float("nan"),
                "CENSORED": float("nan"),
                "TATRISK": float(at_time),
                "STRATUMNUM": stratum_number,
                "STRATUM": " ".join(str(value) for value in values) if values else "1",
                **labels,
            }
            curve = pd.concat([curve, pd.DataFrame([risk_row])], ignore_index=True)
        curve_frames.append(curve)

        for quartile in quartiles:
            quartile_rows.append({**labels, **quartile})

    survival_frame = pd.concat(curve_frames, ignore_index=True) if curve_frames else pd.DataFrame()
    quartiles_frame = pd.DataFrame(quartile_rows)
    ods_targets = getattr(session, "_ods_output_targets", {})
    if isinstance(ods_targets.get("QUARTILES"), DatasetRefNode):
        _write_dataset(session, ods_targets["QUARTILES"], quartiles_frame)
    if isinstance(ods_targets.get("SURVIVALPLOT"), DatasetRefNode):
        _write_dataset(session, ods_targets["SURVIVALPLOT"], survival_frame)
    homtest_targets = [
        ods_targets.get("HOMTESTS"),
        ods_targets.get("LOGUNICHISQ"),
    ]
    if any(isinstance(target, DatasetRefNode) for target in homtest_targets):
        strata_options = proc.options.get("STRATA_OPTIONS", {})
        group_option = strata_options.get("GROUP")
        test_variables = [str(name).upper() for name in proc.options.get("TEST", [])]
        if group_option:
            group_names = (
                [str(name).upper() for name in group_option]
                if isinstance(group_option, list)
                else [str(group_option).upper()]
            )
            adjustment_names = strata_names
        elif test_variables:
            group_names = test_variables
            adjustment_names = strata_names
        else:
            group_names = strata_names
            adjustment_names = []
        group_columns = [_column(frame, name) for name in group_names]
        adjustment_columns = [_column(frame, name) for name in adjustment_names]
        if all(column is not None for column in [*group_columns, *adjustment_columns]):
            homtests = _logrank_test(
                frame,
                duration_column,
                event_column,
                [column for column in group_columns if column is not None],
                [column for column in adjustment_columns if column is not None],
            )
        else:
            homtests = pd.DataFrame(
                [{"TEST": "Log-Rank", "CHISQ": float("nan"), "DF": 0, "PROBCHISQ": float("nan")}]
            )
        for target in homtest_targets:
            if isinstance(target, DatasetRefNode):
                _write_dataset(session, target, homtests)
    outsurv = proc.options.get("OUTSURV")
    if isinstance(outsurv, DatasetRefNode):
        _write_dataset(session, outsurv, survival_frame)

    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=[
            f"PROC LIFETEST computed Kaplan-Meier estimates for {len(groups)} stratum(a)."
        ],
    )


def _cox_negative_log_likelihood(
    beta: np.ndarray,
    durations: np.ndarray,
    events: np.ndarray,
    design: np.ndarray,
    strata: np.ndarray,
) -> float:
    """Efron partial negative log likelihood for a Cox PH model."""
    total = 0.0
    for stratum in np.unique(strata):
        selected = strata == stratum
        stratum_times = durations[selected]
        stratum_events = events[selected]
        stratum_design = design[selected]
        eta = np.clip(stratum_design @ beta, -500.0, 500.0)
        for event_time in np.unique(stratum_times[stratum_events]):
            event_mask = (stratum_times == event_time) & stratum_events
            risk_mask = stratum_times >= event_time
            event_count = int(event_mask.sum())
            if event_count == 0:
                continue
            maximum = float(np.max(eta[risk_mask]))
            risk_sum = float(np.exp(eta[risk_mask] - maximum).sum())
            event_sum = float(np.exp(eta[event_mask] - maximum).sum())
            total -= float(eta[event_mask].sum())
            for tied_index in range(event_count):
                denominator = risk_sum - tied_index / event_count * event_sum
                if denominator <= 0 or not math.isfinite(denominator):
                    return float("inf")
                total += maximum + math.log(denominator)
    return total


def _profile_interval_one_parameter(
    estimate: float,
    standard_error: float,
    objective: Any,
    alpha: float,
) -> tuple[float, float]:
    target = float(chi2.ppf(1.0 - alpha, 1))
    optimum = float(objective(np.array([estimate])))

    def equation(value: float) -> float:
        return 2.0 * (float(objective(np.array([value]))) - optimum) - target

    initial_step = max(standard_error, 0.25)

    def boundary(direction: float) -> float:
        inner = estimate
        outer = estimate + direction * initial_step
        for _ in range(30):
            value = equation(outer)
            if math.isfinite(value) and value >= 0:
                low, high = sorted((inner, outer))
                return float(brentq(equation, low, high, maxiter=200))
            outer = estimate + 2.0 * (outer - estimate)
        return float("nan")

    return boundary(-1.0), boundary(1.0)


def _resolve_reference(levels: list[Any], requested: Any) -> Any:
    text = str(requested).strip().strip("'\"") if requested is not None else "LAST"
    if text.upper() == "FIRST":
        return levels[0]
    if text.upper() == "LAST" or not text:
        return levels[-1]
    for level in levels:
        if _sas_value_key(level).upper() == text.upper():
            return level
    return levels[-1]


def _fit_cox_block(
    frame: pd.DataFrame,
    model: dict[str, Any],
    classes: dict[str, dict[str, Any]],
    strata_names: list[str],
    hazard_requests: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    duration_column = _column(frame, model.get("duration", ""))
    censor_column = _column(frame, model.get("censor", ""))
    if duration_column is None or censor_column is None:
        missing = model.get("duration", "") if duration_column is None else model.get("censor", "")
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

    needed = [duration_column, censor_column]
    needed.extend(column for column in predictor_columns.values() if column is not None)
    needed.extend(column for column in strata_columns if column is not None)
    working = frame[needed].copy().dropna()
    working[duration_column] = pd.to_numeric(working[duration_column], errors="coerce")
    working = working.dropna(subset=[duration_column])
    working = working[working[duration_column] >= 0]
    if working.empty:
        raise ValueError("PROC PHREG has no complete observations")

    censor_values = {_sas_value_key(value) for value in model.get("censor_values", [1])}
    events = ~working[censor_column].map(lambda value: _sas_value_key(value) in censor_values)
    if not events.any():
        raise ValueError("PROC PHREG has no events")

    design_columns: list[np.ndarray] = []
    coefficient_info: list[dict[str, Any]] = []
    for predictor in predictor_names:
        column = predictor_columns[predictor]
        assert column is not None
        class_definition = classes.get(predictor)
        if class_definition is not None:
            levels = sorted(
                working[column].dropna().unique().tolist(),
                key=_level_sort_key,
            )
            if len(levels) < 2:
                continue
            reference = _resolve_reference(levels, class_definition.get("REF", "LAST"))
            for level in levels:
                if _sas_value_key(level) == _sas_value_key(reference):
                    continue
                design_columns.append((working[column].map(_sas_value_key) == _sas_value_key(level)).astype(float).to_numpy())
                coefficient_info.append(
                    {"variable": predictor, "level": level, "reference": reference}
                )
        else:
            numeric = pd.to_numeric(working[column], errors="coerce")
            if numeric.isna().any():
                raise ValueError(f"Variable {predictor} must be numeric or listed in CLASS")
            design_columns.append(numeric.to_numpy(dtype=float))
            coefficient_info.append(
                {"variable": predictor, "level": None, "reference": None}
            )
    if not design_columns:
        raise ValueError("PROC PHREG has no estimable model effects")

    design = np.column_stack(design_columns)
    durations = working[duration_column].to_numpy(dtype=float)
    event_array = events.to_numpy(dtype=bool)
    if strata_columns:
        strata = pd.MultiIndex.from_frame(working[strata_columns]).factorize()[0]
    else:
        strata = np.zeros(len(working), dtype=int)
    objective = lambda beta: _cox_negative_log_likelihood(
        np.asarray(beta, dtype=float), durations, event_array, design, strata
    )
    result = minimize(objective, np.zeros(design.shape[1]), method="BFGS")
    if not np.all(np.isfinite(result.x)):
        raise ValueError("PROC PHREG failed to estimate finite coefficients")
    if not result.success:
        warnings.append(f"PROC PHREG convergence warning: {result.message}")
    beta = np.asarray(result.x, dtype=float)
    covariance = np.atleast_2d(np.asarray(result.hess_inv, dtype=float))
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))

    parameter_rows: list[dict[str, Any]] = []
    for index, info in enumerate(coefficient_info):
        estimate = float(beta[index])
        standard_error = float(standard_errors[index])
        statistic = (estimate / standard_error) ** 2 if standard_error > 0 else float("nan")
        parameter_rows.append(
            {
                "PARAMETER": info["variable"],
                "VARIABLE": info["variable"],
                "CLASSVAL0": "" if info["level"] is None else str(info["level"]),
                "ESTIMATE": estimate,
                "STDERR": standard_error,
                "CHISQ": statistic,
                "PROBCHISQ": float(chi2.sf(statistic, 1)) if math.isfinite(statistic) else float("nan"),
                "HAZARDRATIO": _safe_exp(estimate),
            }
        )

    if not hazard_requests:
        hazard_requests = [
            {"variable": info["variable"], "label": "", "options": {}}
            for info in coefficient_info
        ]
    hazard_rows: list[dict[str, Any]] = []
    profile_warning_added = False
    for request in hazard_requests:
        requested = str(request.get("variable", "")).upper()
        alpha = float(request.get("options", {}).get("ALPHA", 0.05))
        z_value = float(norm.ppf(1.0 - alpha / 2.0))
        for index, info in enumerate(coefficient_info):
            if info["variable"] != requested:
                continue
            estimate = float(beta[index])
            standard_error = float(standard_errors[index])
            lower_beta = estimate - z_value * standard_error
            upper_beta = estimate + z_value * standard_error
            wants_profile = str(request.get("options", {}).get("CL", "")).upper() == "PL"
            if wants_profile and len(beta) == 1:
                lower_beta, upper_beta = _profile_interval_one_parameter(
                    estimate, standard_error, objective, alpha
                )
            elif wants_profile and not profile_warning_added:
                warnings.append(
                    "Profile-likelihood limits for multivariable PHREG are not yet available; Wald limits were returned in PLLOWER/PLUPPER."
                )
                profile_warning_added = True
            description = request.get("label") or info["variable"]
            if info["level"] is not None:
                description = (
                    f"{description} {info['level']} vs {info['reference']}"
                )
            hazard_rows.append(
                {
                    "DESCRIPTION": description,
                    info["variable"]: info["level"],
                    "HAZARDRATIO": _safe_exp(estimate),
                    "WALDLOWER": _safe_exp(estimate - z_value * standard_error),
                    "WALDUPPER": _safe_exp(estimate + z_value * standard_error),
                    "PLLOWER": _safe_exp(lower_beta) if math.isfinite(lower_beta) else float("nan"),
                    "PLUPPER": _safe_exp(upper_beta) if math.isfinite(upper_beta) else float("nan"),
                    "HRLOWERCL": _safe_exp(lower_beta) if math.isfinite(lower_beta) else float("nan"),
                    "HRUPPERCL": _safe_exp(upper_beta) if math.isfinite(upper_beta) else float("nan"),
                }
            )
    return pd.DataFrame(hazard_rows), pd.DataFrame(parameter_rows), warnings


def handle_proc_phreg(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """PROC PHREG — Cox proportional hazards regression with Efron ties."""
    data_ref = proc.options.get("DATA")
    if not isinstance(data_ref, DatasetRefNode):
        return StepResult(success=False, error="PROC PHREG requires DATA=")
    try:
        dataset = session.get_dataset(data_ref.libref, data_ref.name)
    except KeyError:
        return StepResult(
            success=False,
            error=f"Dataset {data_ref.libref}.{data_ref.name} not found",
        )
    dataset = _apply_export_dataset_options(dataset, data_ref.options, session)
    frame = dataset.data.copy()
    where_statements = [statement for statement in proc.statements if isinstance(statement, WhereNode)]
    if where_statements:
        dataset = _apply_export_dataset_options(
            dataset,
            [{"WHERE": statement.condition} for statement in where_statements],
            session,
        )
        frame = dataset.data.copy()

    model = next(
        (statement for statement in proc.statements
         if isinstance(statement, dict) and statement.get("action") == "model"),
        None,
    )
    if model is None:
        return StepResult(success=False, error="PROC PHREG requires MODEL statement")
    class_statement = next(
        (statement for statement in proc.statements
         if isinstance(statement, dict) and statement.get("action") == "class"),
        {"classes": []},
    )
    classes = {
        item["name"]: item.get("options", {})
        for item in class_statement.get("classes", [])
    }
    strata_statement = next(
        (statement for statement in proc.statements
         if isinstance(statement, dict) and statement.get("action") == "strata"),
        {"variables": []},
    )
    by_statement = next(
        (statement for statement in proc.statements
         if isinstance(statement, dict) and statement.get("action") == "by"),
        {"variables": []},
    )
    hazard_requests = [
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "hazardratio"
    ]
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
    hazard_frames: list[pd.DataFrame] = []
    parameter_frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    try:
        for by_value, block in blocks:
            hazard, parameters, block_warnings = _fit_cox_block(
                block,
                model,
                classes,
                strata_statement.get("variables", []),
                hazard_requests,
            )
            values = by_value if isinstance(by_value, tuple) else (by_value,)
            for column, value in zip(by_columns, values):
                hazard[column] = value
                parameters[column] = value
            hazard_frames.append(hazard)
            parameter_frames.append(parameters)
            warnings.extend(block_warnings)
    except ValueError as exc:
        return StepResult(success=False, error=str(exc))

    hazard_output = pd.concat(hazard_frames, ignore_index=True) if hazard_frames else pd.DataFrame()
    parameter_output = pd.concat(parameter_frames, ignore_index=True) if parameter_frames else pd.DataFrame()
    ods_targets = getattr(session, "_ods_output_targets", {})
    if isinstance(ods_targets.get("HAZARDRATIOS"), DatasetRefNode):
        _write_dataset(session, ods_targets["HAZARDRATIOS"], hazard_output)
    if isinstance(ods_targets.get("PARAMETERESTIMATES"), DatasetRefNode):
        _write_dataset(session, ods_targets["PARAMETERESTIMATES"], parameter_output)

    return StepResult(
        success=True,
        rows_affected=len(frame),
        notes=[f"PROC PHREG fitted {len(blocks)} Cox model(s) with Efron ties."],
        warnings=warnings,
    )
