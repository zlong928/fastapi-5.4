from __future__ import annotations

import re

from app.services.chart_extraction.extractors.base import ExtractorContext, ExtractorResult


OD600_AXIS_MAX = 0.6
PHENOL_AXIS_MAX = 100.0
PHENOL_FROM_LEFT_AXIS_SCALE = PHENOL_AXIS_MAX / OD600_AXIS_MAX


def _clean_cell(value: str) -> str:
    return value.strip().replace("₆₀₀", "600")


def _parse_number(value: str) -> float | None:
    cleaned = value.strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return [], []
    headers = [_clean_cell(cell) for cell in lines[0].strip("|").split("|")]
    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = [_clean_cell(cell) for cell in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(cells)
    return headers, rows


def _series_values(rows: list[list[str]], column_index: int) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _parse_number(row[column_index])
        if value is not None:
            values.append(value)
    return values


def _semantic_axis(header: str, raw_values: list[float]) -> tuple[str, str, str, float]:
    header_lower = header.lower()
    max_value = max(raw_values) if raw_values else 0.0
    if "phenol" in header_lower:
        scale = PHENOL_FROM_LEFT_AXIS_SCALE if 0 < max_value <= 1.5 else 1.0
        return "Phenol", "%", "right", scale
    if "od" in header_lower or "bacteria" in header_lower:
        scale = 1 / PHENOL_FROM_LEFT_AXIS_SCALE if max_value > 5 else 1.0
        return "Bacteria OD600", "", "left", scale
    return header.strip(), "", "left", 1.0


def _axis_normalized_value(axis_label: str, value: float) -> float:
    if axis_label == "Phenol":
        return value / PHENOL_AXIS_MAX
    if axis_label == "Bacteria OD600":
        return value / OD600_AXIS_MAX
    return value


def _unique_headers(headers: list[str]) -> list[str]:
    totals: dict[str, int] = {}
    for header in headers:
        totals[header] = totals.get(header, 0) + 1
    seen: dict[str, int] = {}
    unique: list[str] = []
    for header in headers:
        seen[header] = seen.get(header, 0) + 1
        unique.append(f"{header} #{seen[header]}" if totals[header] > 1 else header)
    return unique


class ChartTableExtractor:
    image_type = "line_plot"

    @staticmethod
    def matches(context: ExtractorContext) -> bool:
        content = context.record.content
        return "| " in content and " |" in content and context.record.mineru_type == "chart"

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        headers, rows = _parse_markdown_table(context.record.content)
        if len(headers) < 2 or not rows:
            return ExtractorResult(image_type=self.image_type, points=[], extraction_method="mineru_chart_table_empty")

        x_values = [_parse_number(row[0]) for row in rows]
        numeric_x_values = [value for value in x_values if value is not None]
        if not numeric_x_values:
            return ExtractorResult(image_type=self.image_type, points=[], extraction_method="mineru_chart_table_empty")
        x_min = min(numeric_x_values)
        x_max = max(numeric_x_values)
        x_span = max(1e-9, x_max - x_min)
        x_label, x_unit = self._split_label_and_unit(headers[0])
        x0, y0, x1, y1 = context.plot_area
        points: list[dict] = []

        series_headers = _unique_headers(headers[1:])
        for column_index, header in enumerate(headers[1:], start=1):
            series_name = series_headers[column_index - 1]
            raw_values = _series_values(rows, column_index)
            if not raw_values:
                continue
            y_label, y_unit, y_axis_side, scale = _semantic_axis(header, raw_values)
            for row_index, row in enumerate(rows, start=1):
                x_value = _parse_number(row[0])
                raw_y = _parse_number(row[column_index])
                if x_value is None or raw_y is None:
                    continue
                y_value = round(raw_y * scale, 5)
                x_coordinate = round((x_value - x_min) / x_span, 5)
                y_coordinate = round(max(0.0, min(1.0, _axis_normalized_value(y_label, y_value))), 5)
                point = {
                    "series_name": series_name,
                    "x_value": x_value,
                    "y_value": y_value,
                    "x_coordinate": x_coordinate,
                    "y_coordinate": y_coordinate,
                    "x_axis_label": x_label,
                    "x_axis_unit": x_unit,
                    "y_axis_label": y_label,
                    "y_axis_unit": y_unit,
                    "x_axis_type": "linear",
                    "y_axis_type": "linear",
                    "pixel_x": round(x0 + x_coordinate * max(1, x1 - x0), 1),
                    "pixel_y": round(y1 - y_coordinate * max(1, y1 - y0), 1),
                    "color_group": "table",
                    "component_area_px": 999,
                    "axis_calibration_method": "mineru_chart_table",
                    "legend_label": series_name,
                    "legend_binding_status": "table_column_bound",
                    "legend_binding_method": "mineru_chart_content",
                }
                if y_axis_side == "right":
                    point["y_right_value"] = y_value
                    point["y_right_axis_type"] = "linear"
                points.append(point)

        return ExtractorResult(
            image_type=self.image_type,
            points=points,
            extraction_method="mineru_chart_table",
        )

    @staticmethod
    def _split_label_and_unit(header: str) -> tuple[str, str]:
        match = re.match(r"(.+?)\s*\((.+)\)\s*$", header.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return header.strip(), ""
