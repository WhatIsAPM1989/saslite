"""Output Delivery System destinations used by presentation procedures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import pandas as pd

from saslite.ast.proc import ProcNode
from saslite.ast.data_step import DatasetRefNode
from saslite.diagnostics.reporter import Reporter
from saslite.runtime.dataset import Dataset
from saslite.runtime.execution_result import StepResult
from saslite.session.session import Session


_NAMED_COLORS = {
    "BLACK": "000000",
    "WHITE": "FFFFFF",
    "RED": "FF0000",
    "GREEN": "008000",
    "BLUE": "0000FF",
    "NAVY": "000080",
    "GRAY": "808080",
    "GREY": "808080",
    "SILVER": "C0C0C0",
    "YELLOW": "FFFF00",
    "PURPLE": "800080",
    "MAROON": "800000",
    "TEAL": "008080",
    "AQUA": "00FFFF",
    "LIME": "00FF00",
    "ORANGE": "FFA500",
}


_RTF_STYLES: dict[str, dict[str, Any]] = {
    "DEFAULT": {
        "report": {
            "font_face": "Arial", "font_size": "10pt", "foreground": "#000000",
            "background": "#FFFFFF", "bordercolor": "#9FBAD0",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "12pt", "font_weight": "bold", "foreground": "#1F4E78"},
        "header": {"font_weight": "bold", "foreground": "#FFFFFF", "background": "#4472C4", "just": "center"},
        "column": {},
        "alternate": "#F2F6FA",
    },
    "RTF": {
        "report": {
            "font_face": "Times New Roman", "font_size": "10pt", "foreground": "#000000",
            "background": "#FFFFFF", "bordercolor": "#7F7F7F",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "12pt", "font_weight": "bold"},
        "header": {"font_weight": "bold", "background": "#D9E2F3", "just": "center"},
        "column": {},
        "alternate": "#F7F7F7",
    },
    "JOURNAL": {
        "report": {
            "font_face": "Times New Roman", "font_size": "9pt", "foreground": "#000000",
            "background": "#FFFFFF", "bordercolor": "#000000",
            "borderwidth": "0.5pt", "cellpadding": "2pt",
        },
        "title": {"font_size": "11pt", "font_weight": "bold", "just": "center"},
        "header": {"font_weight": "bold", "background": "#FFFFFF", "just": "center"},
        "column": {},
        "alternate": "#FFFFFF",
    },
    "PRINTER": {
        "report": {
            "font_face": "Arial", "font_size": "9pt", "foreground": "#000000",
            "background": "#FFFFFF", "bordercolor": "#666666",
            "borderwidth": "0.5pt", "cellpadding": "2.5pt",
        },
        "title": {"font_size": "12pt", "font_weight": "bold"},
        "header": {"font_weight": "bold", "background": "#D9D9D9", "just": "center"},
        "column": {},
        "alternate": "#F2F2F2",
    },
    "STATISTICAL": {
        "report": {
            "font_face": "Arial", "font_size": "9pt", "foreground": "#202020",
            "background": "#FFFFFF", "bordercolor": "#A6A6C8",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "12pt", "font_weight": "bold", "foreground": "#303064"},
        "header": {"font_weight": "bold", "foreground": "#FFFFFF", "background": "#56568A", "just": "center"},
        "column": {},
        "alternate": "#EFEFF7",
    },
    "HTMLBLUE": {
        "report": {
            "font_face": "Arial", "font_size": "10pt", "foreground": "#112233",
            "background": "#FFFFFF", "bordercolor": "#A7C5E3",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "12pt", "font_weight": "bold", "foreground": "#17365D"},
        "header": {"font_weight": "bold", "foreground": "#FFFFFF", "background": "#2F75B5", "just": "center"},
        "column": {},
        "alternate": "#DDEBF7",
    },
    "SAPPHIRE": {
        "report": {
            "font_face": "Calibri", "font_size": "10pt", "foreground": "#1F1F1F",
            "background": "#FFFFFF", "bordercolor": "#8FAADC",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "13pt", "font_weight": "bold", "foreground": "#1F3864"},
        "header": {"font_weight": "bold", "foreground": "#FFFFFF", "background": "#203864", "just": "center"},
        "column": {},
        "alternate": "#D9E2F3",
    },
    "MEADOW": {
        "report": {
            "font_face": "Calibri", "font_size": "10pt", "foreground": "#1F2D1F",
            "background": "#FFFFFF", "bordercolor": "#A9C7A0",
            "borderwidth": "0.5pt", "cellpadding": "3pt",
        },
        "title": {"font_size": "13pt", "font_weight": "bold", "foreground": "#375623"},
        "header": {"font_weight": "bold", "foreground": "#FFFFFF", "background": "#548235", "just": "center"},
        "column": {},
        "alternate": "#E2F0D9",
    },
}

_RTF_STYLE_ALIASES = {
    "NORMAL": "DEFAULT", "JOURNAL2": "JOURNAL", "JOURNAL3": "JOURNAL",
    "MINIMAL": "JOURNAL", "PLATEAU": "SAPPHIRE", "SEASIDE": "HTMLBLUE",
}


@dataclass
class _RtfResources:
    fonts: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)

    def font(self, value: str) -> int:
        font = str(value).strip().strip("'\"") or "Arial"
        if font not in self.fonts:
            self.fonts.append(font)
        return self.fonts.index(font)

    def color(self, value: Any) -> int:
        color = _normalize_color(value) or "000000"
        if color not in self.colors:
            self.colors.append(color)
        return self.colors.index(color) + 1


def handle_ods(proc: ProcNode, session: Session, reporter: Reporter) -> StepResult:
    """Track ODS OUTPUT tables and file-based RTF/LISTING destinations."""
    action = str(proc.options.get("ACTION", "")).upper()
    if not hasattr(session, "_ods_output_targets"):
        session._ods_output_targets = {}
    if not hasattr(session, "_ods_output_items"):
        session._ods_output_items = []

    if action == "OUTPUT":
        new_items = list(proc.options.get("TABLE_ITEMS", []))
        if not new_items:
            new_items = list(proc.options.get("TABLES", {}).items())
        replaced = {str(name).upper() for name, _target in new_items}
        session._ods_output_items = [
            item for item in session._ods_output_items
            if str(item[0]).upper() not in replaced
        ] + new_items
        session._ods_output_targets.update(proc.options.get("TABLES", {}))
        return StepResult(success=True)

    if action == "OUTPUT_CLOSE":
        session._ods_output_targets.clear()
        session._ods_output_items.clear()
        return StepResult(success=True)

    if action != "CONTROL":
        return StepResult(success=True)

    destination = str(proc.options.get("DESTINATION", "")).upper()
    if destination not in {"RTF", "LISTING"}:
        # SELECT, EXCLUDE, and GRAPHICS are accepted compatibility controls.
        return StepResult(success=True)

    destinations = _document_destinations(session)
    if proc.options.get("CLOSE"):
        closed = destinations.pop(destination, None)
        notes = []
        if closed is not None:
            notes.append(f"ODS {destination} closed {closed['path']}")
        return StepResult(success=True, notes=notes)

    raw_path = proc.options.get("FILE", proc.options.get("BODY", ""))
    if not raw_path:
        if destination == "LISTING":
            # ODS LISTING; restores the normal terminal listing.
            destinations.pop(destination, None)
            return StepResult(success=True)
        return StepResult(success=False, error="ODS RTF requires FILE=")

    path = _resolve_destination_path(str(raw_path), session)
    style_name = _style_name(proc.options.get("STYLE", "DEFAULT"))
    try:
        if destination == "RTF":
            resources = _resources_for_style(style_name)
            _write_rtf_document(path, [], style_name=style_name, resources=resources)
        else:
            path.write_text("", encoding="utf-8")
    except OSError as exc:
        return StepResult(
            success=False,
            error=f"Unable to open ODS {destination} file {path}: {exc}",
        )

    destinations[destination] = {"path": path, "blocks": []}
    if destination == "RTF":
        destinations[destination].update({
            "style_name": style_name,
            "resources": resources,
        })
    return StepResult(
        success=True,
        notes=[f"ODS {destination} opened {path}"],
    )


def write_report_destinations(
    session: Session,
    frame: pd.DataFrame,
    *,
    title: str,
    listing_text: str,
    presentation: dict[str, Any] | None = None,
) -> list[str]:
    """Append a PROC REPORT result to every active document destination."""
    written: list[str] = []
    for destination, state in _document_destinations(session).items():
        path = state["path"]
        if destination == "RTF":
            style_name = state.get("style_name", "DEFAULT")
            resources = state.get("resources")
            if not isinstance(resources, _RtfResources):
                resources = _resources_for_style(style_name)
                state["resources"] = resources
            state["blocks"].append(_render_rtf_table(
                frame,
                title,
                style_name=style_name,
                resources=resources,
                presentation=presentation,
            ))
            _write_rtf_document(
                path,
                state["blocks"],
                style_name=style_name,
                resources=resources,
            )
        elif destination == "LISTING":
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(listing_text)
                if not listing_text.endswith("\n"):
                    stream.write("\n")
        written.append(f"ODS {destination} wrote {path}")
    return written


def output_items(session: Session, proc: ProcNode | None = None) -> list[tuple[Any, Any]]:
    """Return active ODS OUTPUT assignments, preserving duplicate table targets.

    SAS permits the same output object to be routed to more than one data set,
    commonly with different target data-set options.  The historical mapping
    on ``Session`` cannot represent duplicates, so consumers should use this
    ordered form.
    """
    items = list(getattr(session, "_ods_output_items", []))
    if not items:
        items = list(getattr(session, "_ods_output_targets", {}).items())
    if proc is not None:
        for statement in proc.statements:
            if not isinstance(statement, dict) or statement.get("action") != "ods":
                continue
            local_items = list(statement.get("table_items", []))
            items.extend(local_items or statement.get("tables", {}).items())
    return items


def write_output_tables(
    session: Session,
    tables: dict[str, pd.DataFrame],
    *,
    proc: ProcNode | None = None,
) -> list[str]:
    """Materialize requested ODS output objects as SASLite data sets."""
    normalized = {str(name).upper(): frame for name, frame in tables.items()}
    written: list[str] = []
    for table_name, target in output_items(session, proc):
        frame = normalized.get(str(table_name).upper())
        if frame is None or not isinstance(target, DatasetRefNode):
            continue
        dataset = Dataset.from_dataframe(
            frame.copy(),
            name=target.name,
            libref=target.libref,
        )
        # Import lazily: registry imports the ODS handler through the facade,
        # while several PROC modules also depend on this helper.
        from saslite.executor.proc.registry import _apply_export_dataset_options

        dataset = _apply_export_dataset_options(dataset, target.options, session)
        session.put_dataset(target.libref, target.name, dataset)
        written.append(f"{str(table_name)}={target.libref}.{target.name}")
    return written


def _document_destinations(session: Session) -> dict[str, dict[str, Any]]:
    if not hasattr(session, "_ods_document_destinations"):
        session._ods_document_destinations = {}
    return session._ods_document_destinations


def _resolve_destination_path(value: str, session: Session) -> Path:
    fileref = session.get_macro_var(f"_FILEREF_{value.upper()}")
    path = Path(fileref if fileref is not None else value).expanduser()
    return path.resolve()


def _write_rtf_document(
    path: Path,
    blocks: list[str],
    *,
    style_name: str = "DEFAULT",
    resources: _RtfResources | None = None,
) -> None:
    resources = resources or _resources_for_style(style_name)
    fonts = "".join(
        f"{{\\f{index}\\fnil {_rtf_escape(font)};}}"
        for index, font in enumerate(resources.fonts)
    )
    colors = "".join(
        f"\\red{int(color[0:2], 16)}\\green{int(color[2:4], 16)}"
        f"\\blue{int(color[4:6], 16)};"
        for color in resources.colors
    )
    document = (
        r"{\rtf1\ansi\deff0"
        f"{{\\fonttbl{fonts}}}"
        f"{{\\colortbl;{colors}}}"
        "\n"
        r"\viewkind4\uc1\paperw12240\paperh15840\margl1320\margr1320"
        "\n"
        + "\n".join(blocks)
        + "\n}"
    )
    path.write_text(document, encoding="ascii")


def _render_rtf_table(
    frame: pd.DataFrame,
    title: str,
    *,
    style_name: str = "DEFAULT",
    resources: _RtfResources | None = None,
    presentation: dict[str, Any] | None = None,
) -> str:
    preset = _RTF_STYLES[_style_name(style_name)]
    resources = resources or _resources_for_style(style_name)
    presentation = presentation or {}

    report_override = _parse_style_attributes(presentation.get("REPORT", ""))
    report_style = _merged_style(preset["report"], report_override)
    title_style = _merged_style(report_style, preset.get("title", {}))
    cell_report_style = dict(report_style)
    cell_report_style.pop("width", None)
    column_base_override = _parse_style_attributes(presentation.get("COLUMN", ""))
    header_style = _merged_style(
        cell_report_style,
        preset.get("header", {}),
        _parse_style_attributes(presentation.get("HEADER", "")),
    )
    body_style = _merged_style(
        cell_report_style,
        preset.get("column", {}),
        column_base_override,
    )

    column_overrides = list(presentation.get("COLUMNS", []))
    columns = [str(column) for column in frame.columns]
    count = max(1, len(columns))
    body_styles: list[dict[str, str]] = []
    header_styles: list[dict[str, str]] = []
    for index in range(count):
        overrides = column_overrides[index] if index < len(column_overrides) else {}
        body_styles.append(_merged_style(
            body_style,
            _parse_style_attributes(overrides.get("COLUMN", "")),
        ))
        header_styles.append(_merged_style(
            header_style,
            _parse_style_attributes(overrides.get("HEADER", "")),
        ))

    # Register resources before the document header is rewritten.
    for style in [report_style, title_style, *header_styles, *body_styles]:
        resources.font(style.get("font_face", "Arial"))
        for key in ("foreground", "background", "bordercolor"):
            if key in style and _normalize_color(style[key]):
                resources.color(style[key])
    alternate = _normalize_color(preset.get("alternate"))
    if alternate:
        resources.color(alternate)

    total_width = _table_width(report_style.get("width", "100%"))
    boundaries = _cell_boundaries(total_width, body_styles)
    padding = _twips(report_style.get("cellpadding", "3pt"), default=60)
    row_prefix = (
        f"\\trowd\\trgaph{max(0, padding)}"
        f"\\trpaddl{max(0, padding)}\\trpaddfl3"
        f"\\trpaddr{max(0, padding)}\\trpaddfr3"
    )

    lines = [
        f"\\pard{_paragraph_alignment(title_style)}"
        f"{_text_controls(title_style, resources)} "
        f"{_rtf_escape(title)}\\par"
    ]
    if not columns:
        lines.append(r"\pard (no columns)\par")
        return "\n".join(lines)

    def row(values: list[Any], styles: list[dict[str, str]]) -> str:
        definitions = "".join(
            _cell_definition(style, boundary, resources)
            for style, boundary in zip(styles, boundaries)
        )
        cells = "".join(
            f"\\pard\\intbl{_paragraph_alignment(style)}"
            f"{_text_controls(style, resources)} "
            f"{_rtf_escape(_display_value(value))}\\cell"
            for value, style in zip(values, styles)
        )
        return f"{row_prefix}{definitions}{cells}\\row"

    lines.append(row(columns, header_styles))
    for row_index, values in enumerate(frame.itertuples(index=False, name=None)):
        styles = body_styles
        if row_index % 2 and alternate:
            styles = [
                style if (
                    "background" in report_override
                    or "background" in column_base_override
                    or "background" in _parse_style_attributes(
                        (
                            column_overrides[index]
                            if index < len(column_overrides) else {}
                        ).get("COLUMN", "")
                    )
                ) else _merged_style(style, {"background": f"#{alternate}"})
                for index, style in enumerate(body_styles)
            ]
        lines.append(row(list(values), styles))
    lines.append(r"\pard\par")
    return "\n".join(lines)


def _style_name(value: Any) -> str:
    name = str(value or "DEFAULT").strip().strip("'\"").upper()
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    name = _RTF_STYLE_ALIASES.get(name, name)
    return name if name in _RTF_STYLES else "DEFAULT"


def _resources_for_style(style_name: str) -> _RtfResources:
    preset = _RTF_STYLES[_style_name(style_name)]
    resources = _RtfResources()
    for component in ("report", "title", "header", "column"):
        style = preset.get(component, {})
        resources.font(style.get(
            "font_face",
            preset["report"].get("font_face", "Arial"),
        ))
        for key in ("foreground", "background", "bordercolor"):
            if key in style and _normalize_color(style[key]):
                resources.color(style[key])
    if preset.get("alternate"):
        resources.color(preset["alternate"])
    return resources


def _parse_style_attributes(value: Any) -> dict[str, str]:
    if not value:
        return {}
    aliases = {
        "backgroundcolor": "background", "background_color": "background",
        "color": "foreground", "foregroundcolor": "foreground",
        "fontface": "font_face", "fontfamily": "font_face",
        "fontsize": "font_size", "fontweight": "font_weight",
        "fontstyle": "font_style", "textdecoration": "text_decoration",
        "cellwidth": "width", "border_color": "bordercolor",
        "border_width": "borderwidth", "cell_padding": "cellpadding",
    }
    result: dict[str, str] = {}
    pattern = re.compile(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)"
    )
    for match in pattern.finditer(str(value)):
        key = match.group(1).lower()
        key = aliases.get(key, key)
        result[key] = match.group(2).strip().strip("'\"")
    return result


def _merged_style(*styles: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for style in styles:
        result.update({str(key).lower(): str(value) for key, value in style.items()})
    return result


def _normalize_color(value: Any) -> str | None:
    if value is None:
        return None
    color = str(value).strip().strip("'\"").upper()
    if color in {"", "TRANSPARENT", "NONE", "AUTO", "AUTOMATIC"}:
        return None
    color = _NAMED_COLORS.get(color, color)
    if color.startswith("CX"):
        color = color[2:]
    elif color.startswith("#"):
        color = color[1:]
    if re.fullmatch(r"[0-9A-F]{6}", color):
        return color
    if re.fullmatch(r"[0-9A-F]{3}", color):
        return "".join(character * 2 for character in color)
    return None


def _number(value: Any, default: float) -> float:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value))
    return float(match.group(0)) if match else default


def _half_points(value: Any, default: int = 20) -> int:
    return max(1, round(_number(value, default / 2) * 2))


def _twips(value: Any, default: int = 10) -> int:
    text = str(value).strip().lower()
    amount = _number(text, default / 20)
    if text.endswith("in"):
        return round(amount * 1440)
    if text.endswith("cm"):
        return round(amount * 567)
    if text.endswith("mm"):
        return round(amount * 56.7)
    return round(amount * 20)


def _table_width(value: Any) -> int:
    text = str(value).strip().lower()
    if text.endswith("%"):
        return max(1200, round(9600 * _number(text, 100) / 100))
    if any(text.endswith(unit) for unit in ("pt", "in", "cm", "mm")):
        return max(1200, _twips(text, 9600))
    return 9600


def _cell_boundaries(total_width: int, styles: list[dict[str, str]]) -> list[int]:
    count = max(1, len(styles))
    widths: list[int | None] = []
    for style in styles:
        value = str(style.get("width", "")).strip().lower()
        if not value:
            widths.append(None)
        elif value.endswith("%"):
            widths.append(round(total_width * _number(value, 0) / 100))
        else:
            widths.append(_twips(value, total_width // count))
    assigned = sum(width for width in widths if width is not None)
    unspecified = sum(width is None for width in widths)
    remaining = max(240 * unspecified, total_width - assigned)
    fallback = remaining // unspecified if unspecified else 0
    concrete = [max(240, width if width is not None else fallback) for width in widths]
    if sum(concrete) > total_width and sum(concrete) > 0:
        scale = total_width / sum(concrete)
        concrete = [max(240, round(width * scale)) for width in concrete]
    boundaries: list[int] = []
    position = 0
    for width in concrete:
        position += width
        boundaries.append(position)
    return boundaries


def _cell_definition(
    style: dict[str, str],
    boundary: int,
    resources: _RtfResources,
) -> str:
    controls: list[str] = []
    background = _normalize_color(style.get("background"))
    if background:
        controls.append(f"\\clcbpat{resources.color(background)}")
    valign = style.get("vjust", "").lower()
    controls.append({"center": r"\clvertalc", "middle": r"\clvertalc", "bottom": r"\clvertalb"}.get(valign, r"\clvertalt"))
    border_width = _twips(style.get("borderwidth", "0.5pt"), default=10)
    border = _normalize_color(style.get("bordercolor", "#000000"))
    if border_width > 0 and border:
        color = resources.color(border)
        for side in ("t", "l", "b", "r"):
            controls.append(f"\\clbrdr{side}\\brdrs\\brdrw{border_width}\\brdrcf{color}")
    controls.append(f"\\cellx{boundary}")
    return "".join(controls)


def _paragraph_alignment(style: dict[str, str]) -> str:
    just = style.get("just", style.get("text_align", "left")).lower()
    return {"c": r"\qc", "center": r"\qc", "r": r"\qr", "right": r"\qr"}.get(just, r"\ql")


def _text_controls(style: dict[str, str], resources: _RtfResources) -> str:
    controls = [
        f"\\f{resources.font(style.get('font_face', 'Arial'))}",
        f"\\fs{_half_points(style.get('font_size', '10pt'))}",
    ]
    foreground = _normalize_color(style.get("foreground", "#000000"))
    if foreground:
        controls.append(f"\\cf{resources.color(foreground)}")
    weight = style.get("font_weight", "").lower()
    controls.append(r"\b" if weight in {"bold", "b", "700", "800", "900"} else r"\b0")
    font_style = style.get("font_style", "").lower()
    controls.append(r"\i" if font_style in {"italic", "i"} else r"\i0")
    decoration = style.get("text_decoration", "").lower()
    controls.append(r"\ul" if "underline" in decoration else r"\ul0")
    return "".join(controls)


def _display_value(value: Any) -> str:
    try:
        if pd.isna(value):
            return "."
    except (TypeError, ValueError):
        pass
    return str(value)


def _rtf_escape(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character in "\\{}":
            escaped.append("\\" + character)
        elif character == "\n":
            escaped.append(r"\line ")
        elif 32 <= codepoint < 127:
            escaped.append(character)
        else:
            for offset in range(0, len(character.encode("utf-16-le")), 2):
                unit = int.from_bytes(
                    character.encode("utf-16-le")[offset:offset + 2],
                    "little",
                )
                signed = unit if unit < 32768 else unit - 65536
                escaped.append(f"\\u{signed}?")
    return "".join(escaped)
