"""
PointExporter: 将统一 ExtractionPoint 导出为 CSV / DB / JSON。

桥接 agent 层的统一 schema 与现有的 result_mapper / csv_exporter / excel_exporter。
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from app.services.agent.types import (
    EXTRACTION_POINT_FIELDS,
    ExtractionPoint,
    extraction_point_to_dict,
)


def export_points_csv(points: list[ExtractionPoint], path: str | Path | None = None) -> str:
    """将 ExtractionPoint 列表导出为 CSV

    根据 route_family 自动选择列：
    - data_chart: x_value, y_value, x_unit, y_unit, series_name, confidence
    - microscopy: object_class, object_count, object_diameter_physical, channel, pixel_size
    - protein_assay: lane_number, band_label, band_intensity, molecular_weight_kda, target_protein
    """
    if not points:
        return ""
    output = io.StringIO()
    writer = csv.writer(output)

    family = points[0].route_family
    headers = _family_headers(family)
    writer.writerow(headers)

    for pt in points:
        d = extraction_point_to_dict(pt)
        row = [d.get(h, "") for h in headers]
        writer.writerow(row)

    if path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(output.getvalue(), encoding="utf-8-sig")

    return output.getvalue()


def _family_headers(family: str) -> list[str]:
    common = ["figure_id", "route_family", "image_type", "panel_id", "confidence", "needs_review", "quality_tags"]
    if family == "data_chart":
        return common + ["series_name", "x_value", "y_value", "x_unit", "y_unit", "x_label", "y_label", "x_axis_type", "y_axis_type", "error_bar", "significance"]
    elif family == "microscopy":
        return common + ["channel", "object_class", "object_count", "object_diameter_physical", "object_area_physical", "object_circularity", "pixel_size", "scale_bar_value", "scale_bar_unit", "object_area_fraction"]
    elif family == "protein_assay":
        return common + ["lane_number", "band_label", "band_intensity", "band_intensity_norm", "molecular_weight_kda", "target_protein", "loading_control"]
    else:
        return common + ["series_name", "qualitative", "overall_description"]


def extract_points_to_db_format(points: list[ExtractionPoint]) -> list[dict[str, Any]]:
    """转换为 DB-compatible dicts（适配 AgentResultMapper / ExtractionResult）"""
    items: list[dict[str, Any]] = []
    for pt in points:
        item = {
            "field_name": pt.target_protein or pt.object_class or pt.series_name or "visual_evidence",
            "content": pt.qualitative or pt.overall_description or "",
            "evidence": pt.text_evidence or "",
            "confidence": pt.confidence,
            "source_type": "asset",
            "extraction_mode": pt.extraction_method,
            "structured_data": json.dumps(extraction_point_to_dict(pt), ensure_ascii=False),
            "parse_status": "success" if pt.confidence >= 0.5 else "partial",
            "notes": pt.review_reason or "",
            "figure_id": pt.figure_id,
            "caption": pt.overall_description[:200] if pt.overall_description else "",
        }
        items.append(item)
    return items


def merge_points_into_extraction_result(
    final_results: dict[str, Any],
    points: list[ExtractionPoint],
    figure_id: str,
) -> dict[str, Any]:
    """将 ExtractionPoints 合并到最终的 extraction result dict 中"""
    d = extraction_point_to_dict(points[0]) if points else {}
    figure_entry = {
        "figure_id": figure_id,
        "image_path": d.get("image_path", ""),
        "figure_type": d.get("route_family", "unknown"),
        "image_type": d.get("image_type", "unknown"),
        "extraction_points": [extraction_point_to_dict(p) for p in points],
    }

    by_figure = final_results.setdefault("by_figure", {})
    by_figure[figure_id] = figure_entry

    # 提取 extractions
    extractions = []
    for pt in points:
        extractions.append({
            "metric": pt.target_protein or pt.object_class or pt.series_name or "visual_evidence",
            "success": pt.confidence >= 0.3,
            "data": extraction_point_to_dict(pt),
            "qualitative": pt.qualitative or pt.overall_description or "",
            "confidence": "high" if pt.confidence >= 0.7 else ("medium" if pt.confidence >= 0.4 else "low"),
            "notes": pt.review_reason or "",
            "evidence": pt.text_evidence or "",
            "mode": pt.extraction_method,
        })

    if extractions:
        figure_entry["extractions"] = extractions

    return final_results


def extract_points_csv_table(points: list[ExtractionPoint]) -> str:
    """生成可直接用于报告的人类可读 CSV（含 header mapping）"""
    if not points:
        return ""
    output = io.StringIO()
    writer = csv.writer(output)

    family = points[0].route_family
    if family == "data_chart":
        writer.writerow(["Figure", "Series", "X", "Y", "X Unit", "Y Unit", "Error Bar", "Significance", "Confidence"])
        for p in points:
            writer.writerow([p.figure_id, p.series_name, p.x_value, p.y_value, p.x_unit, p.y_unit, p.error_bar, p.significance, p.confidence])
    elif family == "microscopy":
        writer.writerow(["Figure", "Channel", "Class", "Count", "Diam (µm)", "Area (µm²)", "Circularity", "Scale Bar", "Confidence"])
        for p in points:
            writer.writerow([p.figure_id, p.channel, p.object_class, p.object_count or "", p.object_diameter_physical, p.object_area_physical, p.object_circularity,
                            f"{p.scale_bar_value} {p.scale_bar_unit}" if p.scale_bar_value else "", p.confidence])
    elif family == "protein_assay":
        writer.writerow(["Figure", "Lane", "Band", "Target Protein", "MW (kDa)", "Intensity", "Norm Intensity", "Loading Control", "Confidence"])
        for p in points:
            writer.writerow([p.figure_id, p.lane_number, p.band_label, p.target_protein, p.molecular_weight_kda, p.band_intensity, p.band_intensity_norm, p.loading_control, p.confidence])
    else:
        writer.writerow(["Figure", "Route Family", "Series", "Description", "Confidence"])
        for p in points:
            writer.writerow([p.figure_id, p.route_family, p.series_name, p.qualitative[:100], p.confidence])

    return output.getvalue()


def extract_points_json(points: list[ExtractionPoint], indent: int = 2) -> str:
    """导出为 JSON"""
    return json.dumps([extraction_point_to_dict(p) for p in points], ensure_ascii=False, indent=indent)
