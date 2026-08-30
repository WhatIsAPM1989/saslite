"""Matplotlib-backed SGPLOT, SGPANEL, and GTL rendering."""

from __future__ import annotations

import base64
import io
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from saslite.ast.data_step import DatasetRefNode, WhereNode
from saslite.ast.proc import ProcNode
from saslite.diagnostics.reporter import Reporter
from saslite.runtime.execution_result import OutputArtifact, StepResult
from saslite.session.session import Session


_GTL_KIND_MAP = {
    "SCATTERPLOT": "SCATTER",
    "SERIESPLOT": "SERIES",
    "STEPPLOT": "STEP",
    "NEEDLEPLOT": "NEEDLE",
    "BARCHART": "VBAR",
    "HISTOGRAM": "HISTOGRAM",
    "DENSITYPLOT": "DENSITY",
    "REGRESSIONPLOT": "REG",
    "LOESSPLOT": "LOESS",
    "BANDPLOT": "BAND",
    "REFERENCELINE": "REFLINE",
}

_MARKERS = {
    "CIRCLE": "o",
    "CIRCLEFILLED": "o",
    "SQUARE": "s",
    "SQUAREFILLED": "s",
    "DIAMOND": "D",
    "DIAMONDFILLED": "D",
    "TRIANGLE": "^",
    "TRIANGLEFILLED": "^",
    "PLUS": "+",
    "X": "x",
    "STAR": "*",
}

_LINESTYLES = {
    "SOLID": "-",
    "DASH": "--",
    "SHORTDASH": "--",
    "LONGDASH": "--",
    "DOT": ":",
    "DASHDOT": "-.",
}


def handle_proc_template(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """Store DEFINE STATGRAPH definitions in the current session catalog."""
    if not hasattr(session, "_graph_templates"):
        session._graph_templates = {}
    names: list[str] = []
    for definition in proc.statements:
        if not isinstance(definition, dict) or definition.get("action") != "define_statgraph":
            continue
        name = str(definition.get("name", "")).upper()
        if not name:
            continue
        session._graph_templates[name] = list(definition.get("statements", []))
        names.append(name)
    if not names:
        return StepResult(success=False, error="PROC TEMPLATE requires DEFINE STATGRAPH")
    return StepResult(
        success=True,
        notes=[f"GTL template {name} compiled." for name in names],
    )


def handle_proc_sgplot(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """Render PROC SGPLOT to an in-memory PNG artifact."""
    return _render_proc_graph(proc, session, panel=False)


def handle_proc_sgpanel(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """Render PROC SGPANEL to an in-memory PNG artifact."""
    return _render_proc_graph(proc, session, panel=True)


def handle_proc_sgrender(
    proc: ProcNode,
    session: Session,
    reporter: Reporter,
) -> StepResult:
    """Render a session-catalog GTL STATGRAPH template."""
    template_name = str(proc.options.get("TEMPLATE", "")).upper()
    templates = getattr(session, "_graph_templates", {})
    statements = templates.get(template_name) if template_name else None
    if statements is None:
        # Keep historical compatibility with programs that reference a GTL
        # catalog compiled by a full SAS installation outside SASLite.  Such a
        # template cannot be rendered locally, but its input step remains a
        # valid presentation-only boundary.
        loaded = _load_dataset(proc, session)
        if isinstance(loaded, StepResult):
            return loaded
        frame, qualified = loaded
        suffix = f" using external template {template_name}" if template_name else ""
        return StepResult(
            success=True,
            dataset_name=qualified,
            rows_affected=len(frame),
            notes=[f"PROC SGRENDER validated {qualified}{suffix}; template is not in the SASLite catalog."],
        )

    dynamics = {
        str(statement.get("name", "")).upper(): statement.get("value", "")
        for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "dynamic"
    }
    translated = [_resolve_dynamic(statement, dynamics) for statement in statements]
    render_proc = ProcNode(
        proc_name="SGRENDER",
        options={"DATA": proc.options.get("DATA")},
        statements=translated,
    )
    result = _render_proc_graph(render_proc, session, panel=False)
    if result.success:
        result.notes.append(f"PROC SGRENDER used GTL template {template_name}.")
    return result


def _resolve_dynamic(value: Any, dynamics: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return dynamics.get(value.upper(), value)
    if isinstance(value, list):
        return [_resolve_dynamic(item, dynamics) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_dynamic(item, dynamics) for key, item in value.items()}
    return value


def _render_proc_graph(proc: ProcNode, session: Session, *, panel: bool) -> StepResult:
    try:
        plt = _pyplot()
    except ImportError:
        return StepResult(
            success=False,
            error=(
                f"PROC {proc.proc_name} requires matplotlib; install the "
                "saslite graphics dependencies"
            ),
        )

    loaded = _load_dataset(proc, session)
    if isinstance(loaded, StepResult):
        return loaded
    frame, qualified = loaded
    plot_specs = [
        statement for statement in proc.statements
        if isinstance(statement, dict) and statement.get("action") == "plot"
    ]
    if not plot_specs:
        return StepResult(
            success=False,
            error=f"PROC {proc.proc_name} requires at least one plot statement",
        )

    title = _statement_text(proc.statements, "title")
    footnote = _statement_text(proc.statements, "footnote")
    try:
        if panel:
            figure = _render_panel(plt, frame, proc.statements, plot_specs, title)
        elif proc.proc_name == "SGRENDER" and any(
            isinstance(statement, dict) and statement.get("action") == "layout"
            for statement in proc.statements
        ):
            figure = _render_gtl_layouts(
                plt,
                frame,
                proc.statements,
                title,
                proc,
            )
        else:
            figure, axis = plt.subplots(figsize=(8, 5), dpi=110)
            _render_specs(axis, frame, plot_specs)
            _apply_axes(axis, proc.statements)
            if title:
                axis.set_title(str(title))
            _apply_legend(axis, proc)
        if footnote:
            figure.text(0.5, 0.015, str(footnote), ha="center", va="bottom", fontsize=9)
        uses_suptitle = bool(title) and (
            panel
            or (
                proc.proc_name == "SGRENDER"
                and any(
                    isinstance(statement, dict) and statement.get("action") == "layout"
                    for statement in proc.statements
                )
            )
        )
        figure.tight_layout(
            rect=(
                0,
                0.035 if footnote else 0,
                1,
                0.94 if uses_suptitle else 1,
            )
        )
        artifact = _png_artifact(figure, title or f"PROC {proc.proc_name}")
    except (KeyError, TypeError, ValueError) as exc:
        return StepResult(
            success=False,
            error=f"PROC {proc.proc_name} rendering error: {exc}",
        )
    finally:
        # pyplot owns figures globally; closing here prevents long GUI sessions
        # from retaining every rendered graph.
        if "figure" in locals():
            plt.close(figure)

    return StepResult(
        success=True,
        dataset_name=qualified,
        rows_affected=len(frame),
        notes=[f"PROC {proc.proc_name} rendered {qualified} ({len(frame)} observations)."],
        artifacts=[artifact],
    )


def _pyplot():
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    return plt


def _load_dataset(proc: ProcNode, session: Session) -> tuple[pd.DataFrame, str] | StepResult:
    data_ref = proc.options.get("DATA")
    if not data_ref:
        data_ref = session.get_macro_var("SYSLAST") or ""
    if not data_ref:
        return StepResult(
            success=False,
            error=f"PROC {proc.proc_name} has no DATA= and no previously created dataset",
        )

    if isinstance(data_ref, DatasetRefNode):
        libref, member = data_ref.libref, data_ref.name
        options = data_ref.options
    else:
        text = str(data_ref)
        if "." in text:
            libref, member = text.split(".", 1)
        else:
            libref, member = "WORK", text
        options = []
    try:
        dataset = session.get_dataset(libref, member)
    except KeyError:
        return StepResult(success=False, error=f"Dataset {libref}.{member} not found")

    # Reuse the complete input data-set option implementation (KEEP, DROP,
    # RENAME, and WHERE) shared by the other procedures.
    from saslite.executor.proc.registry import _apply_export_dataset_options

    where_options = [
        {"WHERE": statement.condition}
        for statement in proc.statements
        if isinstance(statement, WhereNode)
    ]
    dataset = _apply_export_dataset_options(dataset, list(options) + where_options, session)
    return dataset.data.copy(), f"{libref.upper()}.{member.upper()}"


def _render_panel(plt, frame: pd.DataFrame, statements: list[Any], specs: list[dict[str, Any]], title: str):
    panel = next(
        (
            statement for statement in statements
            if isinstance(statement, dict) and statement.get("action") == "panelby"
        ),
        None,
    )
    if panel is None or not panel.get("variables"):
        raise ValueError("SGPANEL requires PANELBY statement")
    variables = [_column(frame, name) for name in panel["variables"]]
    keys: list[Any]
    subsets: list[pd.DataFrame]
    grouper: Any = variables[0] if len(variables) == 1 else variables
    grouped = frame.groupby(grouper, dropna=False, sort=False)
    keys, subsets = [], []
    for key, subset in grouped:
        keys.append(key)
        subsets.append(subset)
    if not subsets:
        keys, subsets = [""], [frame]

    panel_options = panel.get("options", {})
    columns = max(1, int(panel_options.get("COLUMNS", min(3, len(subsets)))))
    rows = max(1, int(panel_options.get("ROWS", math.ceil(len(subsets) / columns))))
    share = str(panel_options.get("UNISCALE", "ALL")).upper()
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(4.2 * columns, 3.4 * rows),
        dpi=110,
        squeeze=False,
        sharex=share in {"ALL", "COLUMN"},
        sharey=share in {"ALL", "ROW"},
    )
    flat_axes = list(axes.flat)
    for axis, key, subset in zip(flat_axes, keys, subsets):
        _render_specs(axis, subset, specs)
        _apply_axes(axis, statements)
        values = key if isinstance(key, tuple) else (key,)
        label = ", ".join(f"{name}={value}" for name, value in zip(panel["variables"], values))
        axis.set_title(label)
        if axis.get_legend_handles_labels()[0]:
            axis.legend()
    for axis in flat_axes[len(subsets):]:
        axis.set_visible(False)
    if title:
        figure.suptitle(str(title), fontsize=14)
    return figure


def _render_gtl_layouts(
    plt,
    frame: pd.DataFrame,
    statements: list[Any],
    title: str,
    proc: ProcNode,
):
    """Render a nested GTL layout stack using recursive Matplotlib grids."""
    root = _build_layout_tree(statements)
    items = root["items"]
    if not items:
        raise ValueError("GTL template contains no layout content")

    outer = items[0] if len(items) == 1 and _is_layout(items[0]) else {
        "kind": "LATTICE",
        "options": {"COLUMNS": len(items)},
        "items": items,
    }
    width_units, height_units = _layout_extent(outer)
    figure = plt.figure(
        figsize=(
            min(16.0, max(6.0, 4.2 * width_units)),
            min(14.0, max(4.0, 3.4 * height_units)),
        ),
        dpi=110,
    )
    top_grid = figure.add_gridspec(1, 1)
    axes = _render_layout_node(
        figure,
        top_grid[0, 0],
        outer,
        frame,
        proc,
    )
    if not axes:
        raise ValueError("GTL layout contains no plot statements")
    if title:
        figure.suptitle(str(title), fontsize=14)
    return figure


def _build_layout_tree(statements: list[Any]) -> dict[str, Any]:
    root: dict[str, Any] = {"kind": "ROOT", "options": {}, "items": []}
    stack = [root]
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        action = statement.get("action")
        if action == "layout":
            node = {
                "kind": str(statement.get("kind", "OVERLAY")).upper(),
                "options": dict(statement.get("options", {})),
                "items": [],
            }
            stack[-1]["items"].append(node)
            stack.append(node)
        elif action == "endlayout":
            if len(stack) == 1:
                raise ValueError("ENDLAYOUT has no matching LAYOUT")
            stack.pop()
        elif action in {"plot", "entry"}:
            stack[-1]["items"].append(statement)
    if len(stack) != 1:
        raise ValueError("LAYOUT statement has no matching ENDLAYOUT")
    return root


def _render_layout_node(
    figure,
    slot,
    node: dict[str, Any],
    frame: pd.DataFrame,
    proc: ProcNode,
    *,
    sharex=None,
    sharey=None,
) -> list[Any]:
    kind = str(node.get("kind", "OVERLAY")).upper()
    if kind == "OVERLAY":
        child_layouts = [item for item in node["items"] if _is_layout(item)]
        plots = [item for item in node["items"] if item.get("action") == "plot"]
        if child_layouts and not plots:
            if len(child_layouts) == 1:
                return _render_layout_node(
                    figure,
                    slot,
                    child_layouts[0],
                    frame,
                    proc,
                    sharex=sharex,
                    sharey=sharey,
                )
            implicit = {
                "kind": "LATTICE",
                "options": {"COLUMNS": len(child_layouts)},
                "items": child_layouts,
            }
            return _render_layout_node(figure, slot, implicit, frame, proc)
        if child_layouts and plots:
            raise ValueError("an OVERLAY cannot mix plots with nested layouts")

        axis = figure.add_subplot(slot, sharex=sharex, sharey=sharey)
        _render_specs(axis, frame, plots)
        _apply_gtl_layout_options(axis, node.get("options", {}))
        entry = next(
            (
                item for item in node["items"]
                if isinstance(item, dict) and item.get("action") == "entry"
            ),
            None,
        )
        if entry:
            axis.set_title(str(entry.get("text", "")))
        handles, _labels = axis.get_legend_handles_labels()
        if handles and not proc.options.get("NOAUTOLEGEND"):
            axis.legend()
        return [axis]

    if kind != "LATTICE":
        raise ValueError(f"unsupported GTL layout {kind}")

    cells = _layout_cells(node)
    if not cells:
        return []
    rows, columns = _layout_dimensions(node, len(cells))
    options = node.get("options", {})
    # Matplotlib needs enough room for both the upper cell's tick labels and
    # the lower cell's ENTRY title.  GTL gutter values are pixel-like, while
    # GridSpec uses a fraction of the average axis size, so keep a readable
    # baseline even when no explicit gutter is supplied.
    grid_kwargs: dict[str, Any] = {"hspace": 0.35, "wspace": 0.30}
    row_weights = _layout_weights(options.get("ROWWEIGHTS"), rows)
    column_weights = _layout_weights(options.get("COLUMNWEIGHTS"), columns)
    if row_weights:
        grid_kwargs["height_ratios"] = row_weights
    if column_weights:
        grid_kwargs["width_ratios"] = column_weights
    if "ROWGUTTER" in options:
        grid_kwargs["hspace"] = _gutter(options["ROWGUTTER"])
    if "COLUMNGUTTER" in options:
        grid_kwargs["wspace"] = _gutter(options["COLUMNGUTTER"])
    grid = slot.subgridspec(rows, columns, **grid_kwargs)

    column_range = str(options.get("COLUMNDATARANGE", "")).upper()
    row_range = str(options.get("ROWDATARANGE", "")).upper()
    share_columns = column_range.startswith("UNION")
    share_rows = row_range.startswith("UNION")
    share_all_x = column_range == "UNIONALL"
    share_all_y = row_range == "UNIONALL"
    x_references: dict[int, Any] = {}
    y_references: dict[int, Any] = {}
    rendered: list[Any] = []
    order = str(options.get("ORDER", "ROWMAJOR")).upper()
    for index, cell in enumerate(cells):
        if order == "COLUMNMAJOR":
            row, column = index % rows, index // rows
        else:
            row, column = divmod(index, columns)
        if row >= rows or column >= columns:
            break
        x_key = -1 if share_all_x else column
        y_key = -1 if share_all_y else row
        child_axes = _render_layout_node(
            figure,
            grid[row, column],
            cell,
            frame,
            proc,
            sharex=(
                sharex
                if sharex is not None
                else x_references.get(x_key) if share_columns else None
            ),
            sharey=(
                sharey
                if sharey is not None
                else y_references.get(y_key) if share_rows else None
            ),
        )
        if child_axes:
            if share_columns:
                x_references.setdefault(x_key, child_axes[0])
            if share_rows:
                y_references.setdefault(y_key, child_axes[0])
            rendered.extend(child_axes)
    return rendered


def _layout_cells(node: dict[str, Any]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []
    for item in node.get("items", []):
        if _is_layout(item):
            if pending_entries:
                item = {
                    **item,
                    "items": pending_entries + list(item.get("items", [])),
                }
                pending_entries = []
            cells.append(item)
        elif item.get("action") == "entry":
            pending_entries.append(item)
        elif item.get("action") == "plot":
            cells.append(
                {
                    "kind": "OVERLAY",
                    "options": {},
                    "items": pending_entries + [item],
                }
            )
            pending_entries = []
    if pending_entries:
        cells.append({"kind": "OVERLAY", "options": {}, "items": pending_entries})
    return cells


def _layout_dimensions(node: dict[str, Any], count: int) -> tuple[int, int]:
    options = node.get("options", {})
    rows_value = options.get("ROWS")
    columns_value = options.get("COLUMNS")
    if rows_value is not None:
        rows = max(1, int(rows_value))
    elif columns_value is not None:
        rows = max(1, math.ceil(count / max(1, int(columns_value))))
    else:
        rows = max(1, math.floor(math.sqrt(max(1, count))))
    if columns_value is not None:
        columns = max(1, int(columns_value))
    else:
        columns = max(1, math.ceil(count / rows))
    if rows * columns < count:
        rows = math.ceil(count / columns)
    return rows, columns


def _layout_extent(node: dict[str, Any]) -> tuple[float, float]:
    """Return recursive width/height units for a nested layout tree."""
    if str(node.get("kind", "OVERLAY")).upper() == "OVERLAY":
        children = [item for item in node.get("items", []) if _is_layout(item)]
        if not children:
            return 1.0, 1.0
        extents = [_layout_extent(child) for child in children]
        return max(width for width, _height in extents), sum(
            height for _width, height in extents
        )

    cells = _layout_cells(node)
    if not cells:
        return 1.0, 1.0
    rows, columns = _layout_dimensions(node, len(cells))
    column_widths = [1.0] * columns
    row_heights = [1.0] * rows
    order = str(node.get("options", {}).get("ORDER", "ROWMAJOR")).upper()
    for index, cell in enumerate(cells):
        if order == "COLUMNMAJOR":
            row, column = index % rows, index // rows
        else:
            row, column = divmod(index, columns)
        if row >= rows or column >= columns:
            continue
        width, height = _layout_extent(cell)
        column_widths[column] = max(column_widths[column], width)
        row_heights[row] = max(row_heights[row], height)
    return sum(column_widths), sum(row_heights)


def _layout_weights(value: Any, expected: int) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    weights = [float(item) for item in value.get("_VALUES", [])]
    if len(weights) == expected and all(item > 0 for item in weights):
        return weights
    return None


def _gutter(value: Any) -> float:
    return min(2.0, max(0.25, 0.25 + float(value) / 40.0))


def _is_layout(value: Any) -> bool:
    return isinstance(value, dict) and str(value.get("kind", "")).upper() in {
        "OVERLAY",
        "LATTICE",
    }


def _apply_gtl_layout_options(axis, options: dict[str, Any]) -> None:
    for key, axis_name in (("XAXISOPTS", "XAXIS"), ("YAXISOPTS", "YAXIS")):
        value = options.get(key)
        if isinstance(value, dict):
            _apply_axis_options(axis, axis_name, value)


def _render_specs(axis, frame: pd.DataFrame, specs: Iterable[dict[str, Any]]) -> None:
    for spec in specs:
        _render_plot(axis, frame, spec)


def _render_plot(axis, frame: pd.DataFrame, spec: dict[str, Any]) -> None:
    kind = _GTL_KIND_MAP.get(str(spec.get("kind", "")).upper(), str(spec.get("kind", "")).upper())
    args = {str(key).upper(): value for key, value in spec.get("args", {}).items()}
    options = {str(key).upper(): value for key, value in spec.get("options", {}).items()}
    positional = list(spec.get("positional", []))
    group_name = args.get("GROUP", options.get("GROUP"))
    groups = _groups(frame, group_name)
    label_override = options.get("LEGENDLABEL", options.get("NAME"))

    if kind in {"SCATTER", "SERIES", "STEP", "NEEDLE", "REG", "LOESS"}:
        x_name = args.get("X")
        y_name = args.get("Y")
        if x_name is None or y_name is None:
            raise ValueError(f"{kind} requires X= and Y=")
        x_col, y_col = _column(frame, x_name), _column(frame, y_name)
        for group_value, subset in groups:
            label = _plot_label(group_value, label_override)
            clean = subset[[x_col, y_col]].dropna()
            x, y = clean[x_col], clean[y_col]
            if kind == "SCATTER":
                axis.scatter(x, y, label=label, **_marker_kwargs(options))
            elif kind == "SERIES":
                axis.plot(x, y, label=label, **_line_kwargs(options, markers=bool(options.get("MARKERS"))))
            elif kind == "STEP":
                axis.step(x, y, where="mid", label=label, **_line_kwargs(options))
            elif kind == "NEEDLE":
                markerline, stemlines, _baseline = axis.stem(x, y, label=label)
                color = _attrs(options, "LINEATTRS").get("COLOR")
                if color:
                    markerline.set_color(_color(color))
                    stemlines.set_color(_color(color))
            elif kind == "REG":
                axis.scatter(x, y, label=None, **_marker_kwargs(options, alpha_default=0.45))
                numeric_x = pd.to_numeric(x, errors="coerce")
                numeric_y = pd.to_numeric(y, errors="coerce")
                valid = numeric_x.notna() & numeric_y.notna()
                if valid.sum() >= 2:
                    coefficients = np.polyfit(numeric_x[valid], numeric_y[valid], 1)
                    grid = np.linspace(numeric_x[valid].min(), numeric_x[valid].max(), 200)
                    axis.plot(grid, np.polyval(coefficients, grid), label=label, **_line_kwargs(options))
            else:  # LOESS: deterministic rolling smoother without statsmodels.
                numeric = pd.DataFrame(
                    {
                        "x": pd.to_numeric(x, errors="coerce"),
                        "y": pd.to_numeric(y, errors="coerce"),
                    }
                ).dropna().sort_values("x")
                if not numeric.empty:
                    window = max(3, int(math.ceil(len(numeric) * float(options.get("SMOOTH", 0.35)))))
                    smooth = numeric["y"].rolling(window, center=True, min_periods=1).mean()
                    axis.plot(numeric["x"], smooth, label=label, **_line_kwargs(options))
        return

    if kind in {"VBAR", "HBAR", "VLINE", "HLINE", "DOT"}:
        category = args.get("CATEGORY", args.get("X" if kind not in {"HBAR", "HLINE"} else "Y"))
        if category is None and positional:
            category = positional[0]
        response = args.get("RESPONSE", options.get("RESPONSE"))
        _render_summary(axis, frame, kind, category, response, group_name, options)
        return

    if kind == "HISTOGRAM":
        variable = args.get("X") or (positional[0] if positional else None)
        if variable is None:
            raise ValueError("HISTOGRAM requires a variable")
        column = _column(frame, variable)
        bins: Any = options.get("NBINS", "auto")
        if "BINWIDTH" in options:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if len(values):
                bins = max(1, int(math.ceil((values.max() - values.min()) / float(options["BINWIDTH"]))))
        for group_value, subset in groups:
            values = pd.to_numeric(subset[column], errors="coerce").dropna()
            axis.hist(
                values,
                bins=bins,
                alpha=0.55,
                label=_plot_label(group_value, label_override),
                **_fill_kwargs(options),
            )
        return

    if kind == "DENSITY":
        variable = args.get("X") or (positional[0] if positional else None)
        if variable is None:
            raise ValueError("DENSITY requires a variable")
        column = _column(frame, variable)
        from scipy.stats import gaussian_kde

        for group_value, subset in groups:
            values = pd.to_numeric(subset[column], errors="coerce").dropna().to_numpy()
            if len(values) >= 2 and np.ptp(values) > 0:
                grid = np.linspace(values.min(), values.max(), 250)
                axis.plot(
                    grid,
                    gaussian_kde(values)(grid),
                    label=_plot_label(group_value, label_override),
                    **_line_kwargs(options),
                )
        return

    if kind == "BAND":
        x_name = args.get("X")
        lower_name = args.get("LOWER")
        upper_name = args.get("UPPER")
        if not all((x_name, lower_name, upper_name)):
            raise ValueError("BAND requires X=, LOWER=, and UPPER=")
        x_col, low_col, high_col = (_column(frame, name) for name in (x_name, lower_name, upper_name))
        clean = frame[[x_col, low_col, high_col]].dropna()
        axis.fill_between(
            clean[x_col],
            clean[low_col],
            clean[high_col],
            alpha=float(options.get("TRANSPARENCY", 0.25)),
            **_fill_kwargs(options),
        )
        return

    if kind == "REFLINE":
        values = positional or ([args["VALUE"]] if "VALUE" in args else [])
        target_axis = str(options.get("AXIS", args.get("AXIS", "Y"))).upper()
        for value in values:
            numeric = float(value)
            if target_axis == "X":
                axis.axvline(numeric, **_line_kwargs(options))
            else:
                axis.axhline(numeric, **_line_kwargs(options))
        return

    raise ValueError(f"unsupported plot statement {kind}")


def _render_summary(
    axis,
    frame: pd.DataFrame,
    kind: str,
    category: Any,
    response: Any,
    group: Any,
    options: dict[str, Any],
) -> None:
    if category is None:
        raise ValueError(f"{kind} requires a category variable")
    category_col = _column(frame, category)
    group_col = _column(frame, group) if group else None
    response_col = _column(frame, response) if response else None
    columns = [category_col] + ([group_col] if group_col else []) + ([response_col] if response_col else [])
    working = frame[columns].dropna(subset=[category_col])
    keys = [category_col] + ([group_col] if group_col else [])
    stat = str(options.get("STAT", "SUM" if response_col else "FREQ")).upper()
    grouped = working.groupby(keys, dropna=False, sort=False)
    if response_col is None or stat in {"FREQ", "FREQUENCY", "PCT", "PERCENT"}:
        summary = grouped.size().rename("_VALUE").reset_index()
        if stat in {"PCT", "PERCENT"}:
            summary["_VALUE"] = summary["_VALUE"] / summary["_VALUE"].sum() * 100
    else:
        aggregation = {"MEAN": "mean", "MEDIAN": "median", "SUM": "sum", "MIN": "min", "MAX": "max"}.get(stat)
        if aggregation is None:
            raise ValueError(f"unsupported STAT={stat}")
        summary = grouped[response_col].agg(aggregation).rename("_VALUE").reset_index()

    categories = list(pd.unique(summary[category_col]))
    locations = np.arange(len(categories), dtype=float)
    group_values = list(pd.unique(summary[group_col])) if group_col else [None]
    width = 0.8 / max(1, len(group_values))
    for index, group_value in enumerate(group_values):
        subset = summary if group_col is None else summary[summary[group_col].eq(group_value)]
        value_by_category = dict(zip(subset[category_col], subset["_VALUE"]))
        values = [value_by_category.get(category, 0) for category in categories]
        label = None if group_value is None else str(group_value)
        offset = (index - (len(group_values) - 1) / 2) * width
        if kind in {"VBAR", "DOT"}:
            if kind == "DOT":
                axis.scatter(locations + offset, values, label=label, **_marker_kwargs(options))
            else:
                axis.bar(locations + offset, values, width=width, label=label, **_fill_kwargs(options))
            axis.set_xticks(locations, [str(value) for value in categories])
        elif kind == "HBAR":
            axis.barh(locations + offset, values, height=width, label=label, **_fill_kwargs(options))
            axis.set_yticks(locations, [str(value) for value in categories])
        elif kind == "VLINE":
            axis.plot(locations, values, label=label, **_line_kwargs(options, markers=True))
            axis.set_xticks(locations, [str(value) for value in categories])
        else:
            axis.plot(values, locations, label=label, **_line_kwargs(options, markers=True))
            axis.set_yticks(locations, [str(value) for value in categories])


def _apply_axes(axis, statements: list[Any]) -> None:
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("action") not in {"axis", "layout"}:
            continue
        if statement.get("action") == "layout":
            layout_options = statement.get("options", {})
            for key, axis_name in (("XAXISOPTS", "XAXIS"), ("YAXISOPTS", "YAXIS")):
                value = layout_options.get(key)
                if isinstance(value, dict):
                    _apply_axis_options(axis, axis_name, value)
        else:
            _apply_axis_options(axis, statement.get("axis", ""), statement.get("options", {}))


def _apply_axis_options(axis, axis_name: str, options: dict[str, Any]) -> None:
    normalized = "X" if str(axis_name).upper() in {"XAXIS", "COLAXIS"} else "Y"
    setter = axis.set_xlabel if normalized == "X" else axis.set_ylabel
    if "LABEL" in options:
        setter(str(options["LABEL"]))
    if options.get("GRID"):
        axis.grid(True, axis=normalized.lower(), alpha=0.3)
    if "MIN" in options or "MAX" in options:
        current = axis.get_xlim() if normalized == "X" else axis.get_ylim()
        limits = (float(options.get("MIN", current[0])), float(options.get("MAX", current[1])))
        (axis.set_xlim if normalized == "X" else axis.set_ylim)(*limits)
    if str(options.get("TYPE", "")).upper() == "LOG":
        (axis.set_xscale if normalized == "X" else axis.set_yscale)("log")
    values = options.get("VALUES")
    if isinstance(values, dict) and values.get("_VALUES"):
        ticks = values["_VALUES"]
        (axis.set_xticks if normalized == "X" else axis.set_yticks)(ticks)


def _apply_legend(axis, proc: ProcNode) -> None:
    handles, labels = axis.get_legend_handles_labels()
    if not handles or proc.options.get("NOAUTOLEGEND"):
        return
    legend = next(
        (
            statement for statement in proc.statements
            if isinstance(statement, dict) and statement.get("action") == "legend"
        ),
        None,
    )
    kwargs: dict[str, Any] = {}
    if legend:
        options = legend.get("options", {})
        if "TITLE" in options:
            kwargs["title"] = str(options["TITLE"])
        if "POSITION" in options:
            kwargs["loc"] = _legend_position(options["POSITION"])
        if "ACROSS" in options:
            kwargs["ncol"] = int(options["ACROSS"])
    axis.legend(**kwargs)


def _statement_text(statements: list[Any], action: str) -> str:
    return str(next(
        (
            statement.get("text", "") for statement in statements
            if isinstance(statement, dict) and statement.get("action") == action
        ),
        "",
    ))


def _groups(frame: pd.DataFrame, name: Any) -> list[tuple[Any, pd.DataFrame]]:
    if not name:
        return [(None, frame)]
    column = _column(frame, name)
    return list(frame.groupby(column, dropna=False, sort=False))


def _column(frame: pd.DataFrame, name: Any) -> Any:
    columns = {str(column).upper(): column for column in frame.columns}
    key = str(name).upper()
    if key not in columns:
        raise KeyError(f"variable {name} not found")
    return columns[key]


def _attrs(options: dict[str, Any], name: str) -> dict[str, Any]:
    value = options.get(name, {})
    return {str(key).upper(): item for key, item in value.items()} if isinstance(value, dict) else {}


def _color(value: Any) -> str:
    text = str(value)
    if text.upper().startswith("CX") and len(text) in {8, 10}:
        return "#" + text[2:]
    return text


def _marker_kwargs(options: dict[str, Any], *, alpha_default: float = 0.8) -> dict[str, Any]:
    attrs = _attrs(options, "MARKERATTRS")
    kwargs: dict[str, Any] = {
        "marker": _MARKERS.get(str(attrs.get("SYMBOL", "CIRCLEFILLED")).upper(), "o"),
        "s": float(attrs.get("SIZE", 7)) ** 2,
        "alpha": 1.0 - float(options.get("TRANSPARENCY", 1.0 - alpha_default)),
    }
    if "COLOR" in attrs:
        kwargs["color"] = _color(attrs["COLOR"])
    return kwargs


def _line_kwargs(options: dict[str, Any], *, markers: bool = False) -> dict[str, Any]:
    attrs = _attrs(options, "LINEATTRS")
    kwargs: dict[str, Any] = {
        "linestyle": _LINESTYLES.get(str(attrs.get("PATTERN", "SOLID")).upper(), "-"),
        "linewidth": float(attrs.get("THICKNESS", 1.8)),
        "alpha": 1.0 - float(options.get("TRANSPARENCY", 0)),
    }
    if markers:
        marker = _attrs(options, "MARKERATTRS").get("SYMBOL", "CIRCLEFILLED")
        kwargs["marker"] = _MARKERS.get(str(marker).upper(), "o")
    if "COLOR" in attrs:
        kwargs["color"] = _color(attrs["COLOR"])
    return kwargs


def _fill_kwargs(options: dict[str, Any]) -> dict[str, Any]:
    attrs = _attrs(options, "FILLATTRS")
    kwargs: dict[str, Any] = {}
    if "COLOR" in attrs:
        kwargs["color"] = _color(attrs["COLOR"])
    return kwargs


def _plot_label(group_value: Any, override: Any) -> str | None:
    if override not in {None, True, ""}:
        return str(override) if group_value is None else f"{override}: {group_value}"
    return None if group_value is None else str(group_value)


def _legend_position(value: Any) -> str:
    return {
        "TOP": "upper center",
        "BOTTOM": "lower center",
        "LEFT": "center left",
        "RIGHT": "center right",
        "TOPLEFT": "upper left",
        "TOPRIGHT": "upper right",
        "BOTTOMLEFT": "lower left",
        "BOTTOMRIGHT": "lower right",
    }.get(str(value).upper(), "best")


def _png_artifact(figure, title: str) -> OutputArtifact:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    width, height = figure.canvas.get_width_height()
    return OutputArtifact(
        kind="image",
        mime_type="image/png",
        data=base64.b64encode(buffer.getvalue()).decode("ascii"),
        title=str(title),
        width=int(width),
        height=int(height),
    )
