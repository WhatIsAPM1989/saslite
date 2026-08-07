"""Statistical modeling PROCs: REG (OLS), LOGISTIC (logistic regression), CORR (correlation), and TTEST (t-tests).

Implemented with numpy and scipy.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from saslite.ast.proc import ProcNode
from saslite.runtime.dataset import Dataset
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session
from saslite.diagnostics.reporter import Reporter
from saslite.executor.proc.extras import _resolve_dataset, _split_name, _col_map
from saslite.functions.numeric_funcs import probt, probf


def _get_model(proc: ProcNode) -> dict[str, Any] | None:
    for stmt in proc.statements:
        if isinstance(stmt, dict) and stmt.get("action") == "model":
            return stmt
    return None


def _get_output(proc: ProcNode) -> dict[str, Any] | None:
    for stmt in proc.statements:
        if isinstance(stmt, dict) and stmt.get("action") == "output":
            return stmt
    return None


def _design_matrix(df: pd.DataFrame, y_name: str, x_names: list[str],
                   intercept: bool) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, list[str]]:
    """Build y vector and X matrix, dropping rows with missing values."""
    cmap = _col_map(df)
    y_col = cmap.get(y_name)
    if y_col is None:
        raise ValueError(f"Dependent variable {y_name} not found")
    x_cols = []
    for xn in x_names:
        xc = cmap.get(xn)
        if xc is None:
            raise ValueError(f"Predictor {xn} not found")
        x_cols.append(xc)

    sub = df[[y_col] + x_cols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) == 0:
        raise ValueError("No complete observations for model fitting")

    y = sub[y_col].to_numpy(dtype=float)
    X = sub[x_cols].to_numpy(dtype=float)
    names = list(x_cols)
    if intercept:
        X = np.column_stack([np.ones(len(X)), X])
        names = ["Intercept"] + names
    return y, X, sub, names


# ─── PROC REG ──────────────────────────────────────────


def handle_proc_reg(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """PROC REG — ordinary least squares regression."""
    data_name = proc.options.get("DATA", "")
    outest_name = proc.options.get("OUTEST", "")
    noprint = proc.options.get("NOPRINT", False)
    if not data_name:
        return StepResult(success=False, error="PROC REG requires DATA=")

    model = _get_model(proc)
    if model is None or not model.get("y") or not model.get("x"):
        return StepResult(success=False, error="PROC REG requires MODEL y = x1 x2 ...;")

    try:
        ds = _resolve_dataset(session, data_name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_name} not found")

    intercept = "NOINT" not in [o.upper() for o in model.get("options", [])]

    try:
        y, X, sub, coef_names = _design_matrix(ds.data, model["y"], model["x"], intercept)
    except ValueError as e:
        return StepResult(success=False, error=f"PROC REG: {e}")

    n, p = X.shape
    if n <= p:
        return StepResult(success=False,
                          error=f"PROC REG: not enough observations (n={n}, parameters={p})")

    # OLS via least squares
    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    resid = y - yhat

    sse = float(resid @ resid)
    if sse < 1e-10:
        sse = 0.0
    if intercept:
        sst = float(((y - y.mean()) ** 2).sum())
        df_model = p - 1
    else:
        sst = float((y ** 2).sum())
        df_model = p
    ssr = sst - sse
    df_error = n - p
    mse = sse / df_error if df_error > 0 else float("nan")
    rmse = math.sqrt(mse) if mse >= 0 else float("nan")
    r2 = 1.0 - sse / sst if sst > 0 else float("nan")
    adj_r2 = (1.0 - (1.0 - r2) * (n - 1) / df_error
              if df_error > 0 and not math.isnan(r2) else float("nan"))
    f_stat = ((ssr / df_model) / mse
              if df_model > 0 and mse > 0 else float("nan"))
    f_pvalue = (1.0 - probf(f_stat, df_model, df_error)
                if not math.isnan(f_stat) else float("nan"))

    # Standard errors from (X'X)^-1
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(np.clip(np.diag(xtx_inv) * mse, 0, None))
    except np.linalg.LinAlgError:
        se = np.full(p, float("nan"))

    with np.errstate(divide="ignore", invalid="ignore"):
        t_vals = np.where(se > 0, beta / np.where(se > 0, se, 1.0), float("nan"))
    p_vals = np.array([2.0 * (1.0 - probt(abs(t), df_error)) if not math.isnan(t)
                       else float("nan") for t in t_vals])

    buf = io.StringIO()
    buf.write(f"\n{'=' * 60}\n")
    buf.write(f"  PROC REG: {ds.metadata.libref}.{ds.metadata.member_name}\n")
    buf.write(f"  Model: {model['y']} = {' '.join(model['x'])}"
              f"{' (no intercept)' if not intercept else ''}\n")
    buf.write(f"{'=' * 60}\n\n")
    buf.write(f"  Number of Observations Used: {n}\n\n")
    buf.write("  Analysis of Variance\n")
    buf.write(f"  {'Source':<12} {'DF':>4} {'Sum of Squares':>16} {'Mean Square':>14} "
              f"{'F Value':>10} {'Pr > F':>8}\n")
    buf.write(f"  {'-' * 68}\n")
    buf.write(f"  {'Model':<12} {df_model:>4} {ssr:>16.5f} "
              f"{(ssr / df_model if df_model else float('nan')):>14.5f} "
              f"{f_stat:>10.2f} {f_pvalue:>8.4f}\n")
    buf.write(f"  {'Error':<12} {df_error:>4} {sse:>16.5f} {mse:>14.5f}\n")
    buf.write(f"  {'Total':<12} {n - (1 if intercept else 0):>4} {sst:>16.5f}\n\n")
    buf.write(f"  Root MSE:      {rmse:.5f}\n")
    buf.write(f"  R-Square:      {r2:.4f}\n")
    buf.write(f"  Adj R-Sq:      {adj_r2:.4f}\n\n")
    buf.write("  Parameter Estimates\n")
    buf.write(f"  {'Variable':<14} {'DF':>3} {'Estimate':>14} {'Std Error':>12} "
              f"{'t Value':>9} {'Pr > |t|':>9}\n")
    buf.write(f"  {'-' * 64}\n")
    for name, b, s, t, pv in zip(coef_names, beta, se, t_vals, p_vals):
        buf.write(f"  {name:<14} {1:>3} {b:>14.6f} {s:>12.6f} {t:>9.2f} {pv:>9.4f}\n")
    buf.write("\n")

    output = buf.getvalue()
    if not noprint:
        reporter.log(output)

    # OUTEST= dataset
    if outest_name:
        out_libref, out_member = _split_name(outest_name)
        row: dict[str, Any] = {"_MODEL_": "MODEL1", "_TYPE_": "PARMS",
                               "_DEPVAR_": model["y"], "_RMSE_": rmse}
        for name, b in zip(coef_names, beta):
            row[name.upper()] = b
        out_df = pd.DataFrame([row])
        out_ds = Dataset.from_dataframe(out_df, name=out_member, libref=out_libref)
        session.put_dataset(out_libref, out_member, out_ds)

    # OUTPUT OUT= P= R=
    out_stmt = _get_output(proc)
    if out_stmt and out_stmt.get("OUT"):
        out_libref, out_member = _split_name(out_stmt["OUT"])
        out_df = ds.data.copy()
        pred_col = out_stmt.get("P") or out_stmt.get("PREDICTED")
        resid_col = out_stmt.get("R") or out_stmt.get("RESIDUAL")
        pred_series = pd.Series(float("nan"), index=out_df.index)
        pred_series.loc[sub.index] = yhat
        if pred_col:
            out_df[str(pred_col).upper()] = pred_series
        if resid_col:
            resid_series = pd.Series(float("nan"), index=out_df.index)
            resid_series.loc[sub.index] = resid
            out_df[str(resid_col).upper()] = resid_series
        out_ds = Dataset.from_dataframe(out_df, name=out_member, libref=out_libref)
        session.put_dataset(out_libref, out_member, out_ds)

    return StepResult(success=True, rows_affected=n,
                      output_messages=[] if noprint else [output])


# ─── PROC LOGISTIC ─────────────────────────────────────


def handle_proc_logistic(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """PROC LOGISTIC — binary logistic regression (Newton-Raphson)."""
    data_name = proc.options.get("DATA", "")
    outest_name = proc.options.get("OUTEST", "")
    noprint = proc.options.get("NOPRINT", False)
    descending = proc.options.get("DESCENDING", False) or proc.options.get("DESC", False)
    alpha = float(proc.options.get("ALPHA", 0.05))
    if not data_name:
        return StepResult(success=False, error="PROC LOGISTIC requires DATA=")

    model = _get_model(proc)
    if model is None or not model.get("y"):
        return StepResult(success=False, error="PROC LOGISTIC requires MODEL y = ...;")

    try:
        ds = _resolve_dataset(session, data_name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_name} not found")

    # Get CLASS variables
    class_vars = []
    for stmt in proc.statements:
        if isinstance(stmt, dict) and stmt.get("action") == "class":
            class_vars = [v.upper() for v in stmt.get("variables", [])]
            break

    # Get ODDSRATIO variables
    oddsratio_vars = []
    for stmt in proc.statements:
        if isinstance(stmt, dict) and stmt.get("action") == "oddsratio":
            oddsratio_vars = [v.upper() for v in stmt.get("variables", [])]
            break

    cmap = _col_map(ds.data)
    y_col = cmap.get(model["y"])
    if y_col is None:
        return StepResult(success=False, error=f"PROC LOGISTIC: variable {model['y']} not found")

    # Support intercept-only model (empty predictor list)
    x_names = model.get("x", [])
    x_cols = []
    for xn in x_names:
        xc = cmap.get(xn)
        if xc is None:
            return StepResult(success=False, error=f"PROC LOGISTIC: variable {xn} not found")
        x_cols.append(xc)

    # Prepare data
    all_cols = [y_col] + x_cols
    sub = ds.data[all_cols].copy()

    # Convert only non-class numeric variables
    for c in x_cols:
        c_upper = c.upper()
        if c_upper not in class_vars:
            sub[c] = pd.to_numeric(sub[c], errors="coerce")

    sub = sub.dropna()
    if len(sub) == 0:
        return StepResult(success=False, error="PROC LOGISTIC: no complete observations")

    # Determine the modeled event level
    levels = sorted(sub[y_col].astype(str).unique())
    if len(levels) != 2:
        return StepResult(success=False,
                          error=f"PROC LOGISTIC: response must have exactly 2 levels, found {len(levels)}")
    event = model.get("event", "")
    if event:
        event_level = event
    elif descending:
        event_level = levels[1]  # model the larger value
    else:
        event_level = levels[0]  # SAS default: model the smaller (first ordered) value
    if event_level not in levels:
        return StepResult(success=False,
                          error=f"PROC LOGISTIC: EVENT='{event_level}' is not a response level")

    y = (sub[y_col].astype(str) == str(event_level)).to_numpy(dtype=float)

    # Build design matrix - handle categorical variables
    X_list = [np.ones(len(sub))]  # Intercept
    coef_names = ["Intercept"]

    for xc in x_cols:
        xn_upper = xc.upper()
        if xn_upper in class_vars:
            # Categorical variable - use dummy coding (reference = first level)
            unique_vals = sorted(sub[xc].unique())
            if len(unique_vals) > 1:
                for i, val in enumerate(unique_vals[1:], 1):  # Skip first (reference)
                    dummy = (sub[xc] == val).astype(float).to_numpy()
                    X_list.append(dummy)
                    coef_names.append(f"{xc}_{val}")
        else:
            # Continuous variable
            X_list.append(sub[xc].to_numpy(dtype=float))
            coef_names.append(xc)

    X = np.column_stack(X_list)
    n, p = X.shape

    # Newton-Raphson with simple step-halving
    beta = np.zeros(p)
    converged = False
    for _ in range(50):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        W = mu * (1.0 - mu)
        grad = X.T @ (y - mu)
        hess = X.T @ (X * W[:, None])
        try:
            delta = np.linalg.solve(hess + np.eye(p) * 1e-10, grad)
        except np.linalg.LinAlgError:
            return StepResult(success=False, error="PROC LOGISTIC: singular Hessian (separation?)")
        beta_new = beta + delta
        if np.max(np.abs(delta)) < 1e-8:
            beta = beta_new
            converged = True
            break
        beta = beta_new

    eta = np.clip(X @ beta, -30, 30)
    mu = 1.0 / (1.0 + np.exp(-eta))
    eps = 1e-12
    loglik = float(np.sum(y * np.log(mu + eps) + (1 - y) * np.log(1 - mu + eps)))

    # Null model log-likelihood
    p_null = y.mean()
    if 0 < p_null < 1:
        loglik_null = float(len(y) * (p_null * math.log(p_null)
                                      + (1 - p_null) * math.log(1 - p_null)))
    else:
        loglik_null = 0.0

    # Standard errors from inverse Hessian
    W = mu * (1.0 - mu)
    try:
        cov = np.linalg.inv(X.T @ (X * W[:, None]))
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(p, float("nan"))

    from saslite.functions.numeric_funcs import probchi, probit
    with np.errstate(divide="ignore", invalid="ignore"):
        wald = np.where(se > 0, (beta / np.where(se > 0, se, 1.0)) ** 2, float("nan"))
    p_vals = np.array([1.0 - probchi(w, 1) if not math.isnan(w) else float("nan")
                       for w in wald])

    # Calculate confidence intervals for parameters
    z_crit = abs(probit(alpha / 2))  # Two-tailed
    ci_lower = beta - z_crit * se
    ci_upper = beta + z_crit * se

    buf = io.StringIO()
    buf.write(f"\n{'=' * 60}\n")
    buf.write(f"  PROC LOGISTIC: {ds.metadata.libref}.{ds.metadata.member_name}\n")
    pred_str = ' '.join(x_cols) if x_cols else "(Intercept only)"
    buf.write(f"  Model: {model['y']} (event='{event_level}') = {pred_str}\n")
    buf.write(f"{'=' * 60}\n\n")
    buf.write(f"  Number of Observations Used: {n}\n")
    buf.write(f"  Convergence: {'converged' if converged else 'NOT converged'}\n\n")
    buf.write(f"  -2 Log L (intercept only): {-2 * loglik_null:.4f}\n")
    buf.write(f"  -2 Log L (full model):     {-2 * loglik:.4f}\n")
    lr_chi2 = 2 * (loglik - loglik_null)
    lr_p = 1.0 - probchi(lr_chi2, p - 1) if p > 1 else float("nan")
    buf.write(f"  Likelihood Ratio Chi-Sq:   {lr_chi2:.4f} (df={p - 1}, p={lr_p:.4f})\n\n")
    buf.write("  Parameter Estimates\n")
    buf.write(f"  {'Variable':<14} {'DF':>3} {'Estimate':>12} {'Std Error':>12} "
              f"{'Wald Chi-Sq':>12} {'Pr > ChiSq':>11} {'Odds Ratio':>11}\n")
    buf.write(f"  {'-' * 78}\n")
    for i, (name, b, s, w, pv) in enumerate(zip(coef_names, beta, se, wald, p_vals)):
        orat = math.exp(b) if abs(b) < 50 else float("inf")
        or_str = f"{orat:>11.3f}" if i > 0 else " " * 11
        buf.write(f"  {name:<14} {1:>3} {b:>12.6f} {s:>12.6f} {w:>12.4f} {pv:>11.4f} {or_str}\n")
    buf.write("\n")

    # ODDSRATIO statement output
    if oddsratio_vars:
        buf.write("  Odds Ratio Estimates\n")
        buf.write(f"  {'Effect':<14} {'Point Estimate':>15} {f'{int((1-alpha)*100)}% Wald CL':>25}\n")
        buf.write(f"  {'-' * 54}\n")
        for i, (name, b, cil, ciu) in enumerate(zip(coef_names, beta, ci_lower, ci_upper)):
            if i == 0:  # Skip intercept
                continue
            name_base = name.split('_')[0].upper()
            if not oddsratio_vars or name_base in oddsratio_vars:
                or_est = math.exp(b) if abs(b) < 50 else float("inf")
                or_lower = math.exp(cil) if abs(cil) < 50 else float("inf")
                or_upper = math.exp(ciu) if abs(ciu) < 50 else float("inf")
                buf.write(f"  {name:<14} {or_est:>15.3f} {or_lower:>12.3f} - {or_upper:>11.3f}\n")
        buf.write("\n")

    output = buf.getvalue()
    if not noprint:
        reporter.log(output)

    if outest_name:
        out_libref, out_member = _split_name(outest_name)
        row: dict[str, Any] = {"_MODEL_": "MODEL1", "_TYPE_": "PARMS",
                               "_DEPVAR_": model["y"], "_LNLIKE_": loglik}
        for name, b in zip(coef_names, beta):
            row[name.upper()] = b
        out_df = pd.DataFrame([row])
        out_ds = Dataset.from_dataframe(out_df, name=out_member, libref=out_libref)
        session.put_dataset(out_libref, out_member, out_ds)

    out_stmt = _get_output(proc)
    if out_stmt and out_stmt.get("OUT"):
        out_libref, out_member = _split_name(out_stmt["OUT"])
        out_df = ds.data.copy()
        pred_col = out_stmt.get("P") or out_stmt.get("PREDICTED")
        if pred_col:
            pred_series = pd.Series(float("nan"), index=out_df.index)
            pred_series.loc[sub.index] = mu
            out_df[str(pred_col).upper()] = pred_series
        out_ds = Dataset.from_dataframe(out_df, name=out_member, libref=out_libref)
        session.put_dataset(out_libref, out_member, out_ds)

    return StepResult(success=True, rows_affected=n,
                      output_messages=[] if noprint else [output])


# ─── PROC CORR ─────────────────────────────────────────


def handle_proc_corr(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """PROC CORR — correlation analysis (Pearson, Spearman, Kendall)."""
    data_name = proc.options.get("DATA", "")
    outp_name = proc.options.get("OUTP", "")
    noprob = proc.options.get("NOPROB", False)
    nosimple = proc.options.get("NOSIMPLE", False)

    # Method selection
    method = "pearson"
    if proc.options.get("SPEARMAN", False):
        method = "spearman"
    elif proc.options.get("KENDALL", False):
        method = "kendall"
    elif proc.options.get("PEARSON", False):
        method = "pearson"

    if not data_name:
        return StepResult(success=False, error="PROC CORR requires DATA=")

    try:
        ds = _resolve_dataset(session, data_name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_name} not found")

    # Get VAR statement
    var_cols = []
    for stmt in proc.statements:
        if isinstance(stmt, dict) and stmt.get("action") == "var":
            var_cols = [v.upper() for v in stmt.get("variables", [])]
            break

    if not var_cols:
        # Use all numeric columns
        var_cols = [c for c in ds.data.columns
                   if pd.api.types.is_numeric_dtype(ds.data[c])]

    cmap = _col_map(ds.data)
    resolved = [cmap[v] for v in var_cols if v in cmap]

    if len(resolved) < 2:
        return StepResult(success=False,
                         error="PROC CORR requires at least 2 numeric variables")

    # Extract numeric data
    sub = ds.data[resolved].apply(pd.to_numeric, errors="coerce").dropna()
    if len(sub) < 2:
        return StepResult(success=False, error="Not enough observations for correlation")

    # Compute correlation matrix
    corr_matrix = sub.corr(method=method)

    buf = io.StringIO()
    buf.write(f"\n{'=' * 60}\n")
    buf.write(f"  PROC CORR: {ds.metadata.libref}.{ds.metadata.member_name}\n")
    buf.write(f"  Method: {method.capitalize()}\n")
    buf.write(f"{'=' * 60}\n\n")

    if not nosimple:
        buf.write("  Simple Statistics\n")
        buf.write(f"  {'Variable':<12} {'N':>8} {'Mean':>12} {'Std Dev':>12} {'Min':>12} {'Max':>12}\n")
        buf.write(f"  {'-' * 68}\n")
        for col in resolved:
            n = sub[col].count()
            mean = sub[col].mean()
            std = sub[col].std()
            vmin = sub[col].min()
            vmax = sub[col].max()
            buf.write(f"  {col:<12} {n:>8} {mean:>12.4f} {std:>12.4f} "
                     f"{vmin:>12.4f} {vmax:>12.4f}\n")
        buf.write("\n")

    buf.write("  Correlation Coefficients\n")
    buf.write(f"  {'':12}")
    for col in resolved:
        buf.write(f" {col:>12}")
    buf.write("\n")
    buf.write(f"  {'-' * (12 + 13 * len(resolved))}\n")

    for row_var in resolved:
        buf.write(f"  {row_var:<12}")
        for col_var in resolved:
            corr_val = corr_matrix.loc[row_var, col_var]
            buf.write(f" {corr_val:>12.4f}")
        buf.write("\n")

    buf.write("\n")
    output = buf.getvalue()
    reporter.log(output)

    # OUTP= dataset
    if outp_name:
        out_libref, out_member = _split_name(outp_name)
        rows = []
        for var in resolved:
            row = {"_TYPE_": "CORR", "_NAME_": var}
            for col_var in resolved:
                row[col_var.upper()] = corr_matrix.loc[var, col_var]
            rows.append(row)

        out_df = pd.DataFrame(rows)
        out_ds = Dataset.from_dataframe(out_df, name=out_member, libref=out_libref)
        session.put_dataset(out_libref, out_member, out_ds)

    return StepResult(success=True, rows_affected=len(sub),
                     output_messages=[output])


# ─── PROC TTEST ────────────────────────────────────────


def handle_proc_ttest(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """PROC TTEST — one-sample, two-sample, and paired t-tests."""
    data_name = proc.options.get("DATA", "")
    h0 = float(proc.options.get("H0", 0))

    if not data_name:
        return StepResult(success=False, error="PROC TTEST requires DATA=")

    try:
        ds = _resolve_dataset(session, data_name)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {data_name} not found")

    # Extract VAR, CLASS, and PAIRED statements
    var_cols = []
    class_col = None
    paired_vars = []

    for stmt in proc.statements:
        if isinstance(stmt, dict):
            action = stmt.get("action", "")
            if action == "var":
                var_cols = [v.upper() for v in stmt.get("variables", [])]
            elif action == "class":
                class_vars = stmt.get("variables", [])
                class_col = class_vars[0].upper() if class_vars else None
            elif action == "paired":
                paired_vars = [stmt.get("var1", ""), stmt.get("var2", "")]

    cmap = _col_map(ds.data)
    buf = io.StringIO()
    buf.write(f"\n{'=' * 60}\n")
    buf.write(f"  PROC TTEST: {ds.metadata.libref}.{ds.metadata.member_name}\n")
    buf.write(f"{'=' * 60}\n\n")

    # Paired t-test
    if paired_vars and len(paired_vars) == 2:
        var1_col = cmap.get(paired_vars[0])
        var2_col = cmap.get(paired_vars[1])
        if var1_col is None or var2_col is None:
            return StepResult(success=False, error=f"Paired variables not found")

        sub = ds.data[[var1_col, var2_col]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(sub) < 2:
            return StepResult(success=False, error="Not enough observations for paired t-test")

        diff = sub[var1_col] - sub[var2_col]
        t_stat, p_value = stats.ttest_rel(sub[var1_col], sub[var2_col])
        mean_diff = diff.mean()
        se_diff = diff.std() / np.sqrt(len(diff))
        df = len(diff) - 1
        ci_low = mean_diff - 1.96 * se_diff
        ci_high = mean_diff + 1.96 * se_diff

        buf.write(f"  Paired T-test: {paired_vars[0]} - {paired_vars[1]}\n")
        buf.write(f"  N = {len(diff)}, Mean Difference = {mean_diff:.4f}\n")
        buf.write(f"  T = {t_stat:.4f}, DF = {df}, Pr > |t| = {p_value:.4f}\n")
        buf.write(f"  95% CI: [{ci_low:.4f}, {ci_high:.4f}]\n\n")

    # Two-sample t-test (CLASS statement)
    elif class_col:
        if not var_cols:
            var_cols = [c for c in ds.data.columns if pd.api.types.is_numeric_dtype(ds.data[c])]

        class_actual = cmap.get(class_col)
        if class_actual is None:
            return StepResult(success=False, error=f"CLASS variable {class_col} not found")

        groups = ds.data[class_actual].unique()
        if len(groups) != 2:
            return StepResult(success=False, error=f"CLASS variable must have exactly 2 levels, found {len(groups)}")

        for var in var_cols:
            var_col = cmap.get(var)
            if var_col is None:
                continue

            group1_data = ds.data[ds.data[class_actual] == groups[0]][var_col].apply(pd.to_numeric, errors="coerce").dropna()
            group2_data = ds.data[ds.data[class_actual] == groups[1]][var_col].apply(pd.to_numeric, errors="coerce").dropna()

            if len(group1_data) < 2 or len(group2_data) < 2:
                continue

            t_stat, p_value = stats.ttest_ind(group1_data, group2_data)
            df = len(group1_data) + len(group2_data) - 2

            buf.write(f"  Variable: {var}\n")
            buf.write(f"  {class_col} = {groups[0]}: N = {len(group1_data)}, Mean = {group1_data.mean():.4f}\n")
            buf.write(f"  {class_col} = {groups[1]}: N = {len(group2_data)}, Mean = {group2_data.mean():.4f}\n")
            buf.write(f"  T = {t_stat:.4f}, DF = {df}, Pr > |t| = {p_value:.4f}\n\n")

    # One-sample t-test
    else:
        if not var_cols:
            var_cols = [c for c in ds.data.columns if pd.api.types.is_numeric_dtype(ds.data[c])]

        for var in var_cols:
            var_col = cmap.get(var)
            if var_col is None:
                continue

            data = ds.data[var_col].apply(pd.to_numeric, errors="coerce").dropna()
            if len(data) < 2:
                continue

            t_stat, p_value = stats.ttest_1samp(data, h0)
            df = len(data) - 1
            mean = data.mean()
            se = data.std() / np.sqrt(len(data))
            ci_low = mean - 1.96 * se
            ci_high = mean + 1.96 * se

            buf.write(f"  Variable: {var}\n")
            buf.write(f"  N = {len(data)}, Mean = {mean:.4f}, H0 = {h0}\n")
            buf.write(f"  T = {t_stat:.4f}, DF = {df}, Pr > |t| = {p_value:.4f}\n")
            buf.write(f"  95% CI: [{ci_low:.4f}, {ci_high:.4f}]\n\n")

    output = buf.getvalue()
    reporter.log(output)

    return StepResult(success=True, rows_affected=ds.nrow, output_messages=[output])
