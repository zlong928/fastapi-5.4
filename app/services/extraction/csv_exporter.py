"""CSV exporter for the new extraction pipeline.

Produces CSV files with proper physical column headers — not generic x/y labels.
Each CSV column reflects the actual physical quantity and unit extracted.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any


def export_items_to_csv(
    items: list[dict[str, Any]],
    *,
    include_data_points: bool = True,
) -> str:
    """Export extraction items to a CSV string with semantic, unit-aware columns."""
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        "indicator",
        "figure_label",
        "image_type",
        "series_name",
        "review_status",
        "confidence",
        "extraction_method",
        "value_text",
        "value_numeric",
        "value_unit",
        "value_error",
        "source_type",
        "semantic_x_field",
        "semantic_y_field",
        "semantic_value_field",
        "text_evidence_refs",
        "verified",
    ]
    writer.writerow(headers)

    point_rows: list[list[str]] = []
    point_headers = _data_point_headers(items)
    point_header = [
        "indicator",
        "figure_label",
        "series_name",
        point_headers[0],
        point_headers[1],
        "error_bar",
        "review_status",
    ]

    for item in items:
        if _is_non_data_item(item):
            continue
        semantic_x_field = _semantic_axis_field(
            item.get("x_axis_label"),
            item.get("x_axis_unit"),
            item.get("indicator"),
            item.get("text_evidence_refs"),
            axis_name="x",
        )
        semantic_y_field = _semantic_axis_field(
            item.get("y_axis_label"),
            item.get("y_axis_unit"),
            item.get("indicator"),
            item.get("text_evidence_refs"),
            axis_name="y",
        )
        semantic_value_field = _semantic_value_field(item, semantic_y_field)
        writer.writerow([
            item.get("indicator", ""),
            item.get("figure_label", ""),
            item.get("image_type", item.get("chart_type", "")),
            item.get("series_name", ""),
            item.get("review_status", item.get("verification_notes", "")),
            _fmt_float(item.get("confidence")),
            item.get("extraction_method", ""),
            item.get("value_text", ""),
            _fmt_float(item.get("value_numeric")),
            item.get("value_unit", ""),
            item.get("value_error", ""),
            item.get("source_type", ""),
            semantic_x_field,
            semantic_y_field,
            semantic_value_field,
            _stringify_evidence_refs(item.get("text_evidence_refs")),
            _fmt_bool(item.get("verified")),
        ])

        if include_data_points:
            data_points_json = item.get("data_points_json")
            if data_points_json:
                points = _parse_points(data_points_json)
                indicator = item.get("indicator", "")
                fig_label = item.get("figure_label", "")
                for pt in points:
                    point_rows.append([
                        indicator,
                        fig_label,
                        pt.get("series", ""),
                        _fmt_semantic_point(pt, semantic_x_field, value_key="x"),
                        _fmt_semantic_point(pt, semantic_y_field, value_key="y"),
                        pt.get("error_bar", ""),
                        item.get("review_status", item.get("verification_notes", "")),
                    ])

    if point_rows:
        writer.writerow([])  # blank separator
        writer.writerow(["--- Data Points ---"])
        writer.writerow(point_header)
        for row in point_rows:
            writer.writerow(row)

    return output.getvalue()


def export_items_to_csv_file(
    items: list[dict[str, Any]],
    path: str | Path,
    *,
    include_data_points: bool = True,
) -> Path:
    """Export extraction items to a CSV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = export_items_to_csv(items, include_data_points=include_data_points)
    path.write_text(content, encoding="utf-8-sig")
    return path


def _parse_points(data_points_json: Any) -> list[dict]:
    """Parse data_points_json into a list of point dicts."""
    if isinstance(data_points_json, list):
        return data_points_json
    if isinstance(data_points_json, str):
        try:
            parsed = json.loads(data_points_json)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _fmt_float(value: Any) -> str:
    if value is None:
        return ""
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return f"{f:.6g}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_bool(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def _is_non_data_item(item: dict[str, Any]) -> bool:
    image_type = str(item.get("image_type") or item.get("chart_type") or "").strip().lower()
    return image_type in {"non_data_image", "schematic", "schematic_or_photo", "microscopy_quant", "multi_panel_composite"}


def _semantic_axis_field(axis_label: Any, axis_unit: Any, indicator: Any, evidence_refs: Any, *, axis_name: str) -> str:
    label = str(axis_label or "").strip()
    unit = str(axis_unit or "").strip()
    if label:
        if unit and unit not in label:
            return f"{label} ({unit})"
        return label
    fallback = _indicator_from_evidence(indicator, evidence_refs)
    if unit:
        return f"{fallback} ({unit})"
    return fallback if fallback else ("x_measure" if axis_name == "x" else "value")


def _semantic_value_field(item: dict[str, Any], semantic_y_field: str) -> str:
    value_unit = str(item.get("value_unit") or "").strip()
    indicator = str(item.get("indicator") or "").strip()
    if value_unit and indicator and value_unit not in indicator:
        return f"{indicator} ({value_unit})"
    if indicator:
        return indicator
    return semantic_y_field


def _indicator_from_evidence(indicator: Any, evidence_refs: Any) -> str:
    text = str(indicator or "").strip()
    if text:
        return text
    refs = _parse_evidence_refs(evidence_refs)
    if refs:
        compact = refs[0].strip()
        return compact[:64]
    return ""


def _parse_evidence_refs(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _stringify_evidence_refs(value: Any) -> str:
    refs = _parse_evidence_refs(value)
    return " | ".join(refs)


def _data_point_headers(items: list[dict[str, Any]]) -> tuple[str, str]:
    x_field = "x_measure"
    y_field = "value"
    for item in items:
        if _is_non_data_item(item):
            continue
        x_field = _semantic_axis_field(item.get("x_axis_label"), item.get("x_axis_unit"), item.get("indicator"), item.get("text_evidence_refs"), axis_name="x")
        y_field = _semantic_axis_field(item.get("y_axis_label"), item.get("y_axis_unit"), item.get("indicator"), item.get("text_evidence_refs"), axis_name="y")
        if x_field or y_field:
            break
    return x_field, y_field


def _fmt_semantic_point(point: dict[str, Any], semantic_field: str, *, value_key: str) -> str:
    value = _fmt_float(point.get(value_key))
    unit = str(point.get(f"{value_key}_unit") or "").strip()
    if value and unit and unit not in semantic_field:
        return f"{value} {unit}"
    return value
