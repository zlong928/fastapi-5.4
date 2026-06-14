from __future__ import annotations

import csv
import json
from pathlib import Path

from app.services.chart_extraction.models import ImageRecord


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

COORDINATE_CSV_FIELDS = [
    "image_file",
    "image_type",
    "mineru_sub_type",
    "recipe_id",
    "template_profile_id",
    "template_binding_policy",
    "panel_id",
    "series_name",
    "series_label_raw",
    "series_variable",
    "series_value",
    "series_unit",
    "series_role",
    "x_value",
    "y_value",
    "x_coordinate",
    "y_coordinate",
    "x_axis_label",
    "x_axis_unit",
    "y_axis_label",
    "y_axis_unit",
    "x_axis_type",
    "y_axis_type",
    "y_right_value",
    "y_right_axis_type",
    "z_value",
    "z_axis_label",
    "z_axis_unit",
    "z_axis_type",
    "scale_bar_length_px",
    "scale_bar_value",
    "scale_bar_unit",
    "scale_bar_binding_status",
    "scale_bar_binding_method",
    "scale_bar_left_px",
    "scale_bar_right_px",
    "scale_bar_top_px",
    "scale_bar_bottom_px",
    "pixel_size",
    "physical_area_value",
    "physical_area_unit",
    "object_class",
    "object_classification_method",
    "object_left_px",
    "object_right_px",
    "object_top_px",
    "object_bottom_px",
    "object_width_px",
    "object_height_px",
    "object_equivalent_diameter_px",
    "object_equivalent_diameter_value",
    "object_circularity",
    "legend_label",
    "legend_binding_status",
    "legend_binding_method",
    "legend_text_confidence",
    "legend_marker_x",
    "legend_marker_y",
    "legend_marker_area_px",
    "colorbar_min_value",
    "colorbar_max_value",
    "colorbar_unit",
    "colorbar_binding_status",
    "colorbar_binding_method",
    "colorbar_tick_count",
    "colorbar_tick_confidence",
    "colorbar_top_value",
    "colorbar_top_y_px",
    "colorbar_bottom_value",
    "colorbar_bottom_y_px",
    "colorbar_left_px",
    "colorbar_right_px",
    "colorbar_top_px",
    "colorbar_bottom_px",
    "category_index",
    "category_label",
    "category_binding_status",
    "category_binding_method",
    "category_text_confidence",
    "category_label_x",
    "category_label_y",
    "bar_left_px",
    "bar_right_px",
    "bar_top_px",
    "bar_bottom_px",
    "bar_width_px",
    "bar_height_px",
    "errorbar_top_px",
    "errorbar_bottom_px",
    "errorbar_height_px",
    "errorbar_center_x_px",
    "errorbar_binding_status",
    "errorbar_binding_method",
    "bar_geometry_status",
    "scatter_role",
    "fit_line_x1_px",
    "fit_line_y1_px",
    "fit_line_x2_px",
    "fit_line_y2_px",
    "fit_line_slope_px",
    "fit_line_intercept_px",
    "scatter_geometry_status",
    "pixel_x",
    "pixel_y",
    "color_group",
    "component_area_px",
    "extraction_method",
    "axis_calibration_method",
    "axis_label_binding_method",
    "selected_extractor",
    "raw_image_type",
    "final_image_type",
    "routing_status",
    "data_quality",
    "extraction_confidence",
    "needs_review",
    "review_reason",
]

SUMMARY_CSV_FIELDS = [
    "image_file",
    "image_type",
    "status",
    "reason",
    "row_count",
    "accepted_row_count",
    "review_row_count",
    "data_quality",
    "recipe_ids",
    "panel_ids",
    "axis_calibration_methods",
    "review_reasons",
    "csv_path",
    "overlay_path",
    "selected_extractor",
    "raw_image_type",
    "final_image_type",
    "routing_status",
]


def load_image_records(images_dir: Path, content_list_path: Path | None) -> list[ImageRecord]:
    by_path: dict[str, tuple[int, dict]] = {}
    if content_list_path and content_list_path.is_file():
        payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        for index, item in enumerate(payload):
            if isinstance(item, dict) and item.get("img_path"):
                by_path[str(item["img_path"])] = (index, item)

    records: list[ImageRecord] = []
    image_paths = [path for path in sorted(images_dir.glob("*")) if path.suffix.lower() in IMAGE_SUFFIXES]
    for ordinal, path in enumerate(image_paths, start=1):
        rel = f"images/{path.name}"
        content_index, item = by_path.get(rel, ("", {}))
        captions = item.get("image_caption") or item.get("chart_caption") or []
        caption = " ".join(str(part) for part in captions) if isinstance(captions, list) else str(captions or "")
        records.append(
            ImageRecord(
                ordinal=ordinal,
                path=path,
                content_index=content_index,
                mineru_type=str(item.get("type") or ""),
                mineru_sub_type=str(item.get("sub_type") or ""),
                caption=caption,
                content=str(item.get("content") or ""),
            )
        )
    return records


def write_coordinate_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COORDINATE_CSV_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in COORDINATE_CSV_FIELDS} for row in rows])


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_CSV_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in SUMMARY_CSV_FIELDS} for row in rows])


def write_quality_audit_csv(path: Path, summary_rows: list[dict]) -> None:
    fields = [
        "image_type",
        "status",
        "data_quality",
        "review_reasons",
        "selected_extractor",
        "routing_status",
        "recipe_ids",
        "axis_calibration_methods",
        "image_count",
        "row_count",
        "accepted_row_count",
        "review_row_count",
        "example_images",
    ]
    buckets: dict[tuple[str, ...], dict] = {}
    for row in summary_rows:
        review_reasons = str(row.get("review_reasons") or row.get("reason") or "")
        key = (
            str(row.get("image_type") or row.get("final_image_type") or ""),
            str(row.get("status") or ""),
            str(row.get("data_quality") or ""),
            review_reasons,
            str(row.get("selected_extractor") or ""),
            str(row.get("routing_status") or ""),
            str(row.get("recipe_ids") or ""),
            str(row.get("axis_calibration_methods") or ""),
        )
        bucket = buckets.setdefault(
            key,
            {
                "image_type": key[0],
                "status": key[1],
                "data_quality": key[2],
                "review_reasons": key[3],
                "selected_extractor": key[4],
                "routing_status": key[5],
                "recipe_ids": key[6],
                "axis_calibration_methods": key[7],
                "image_count": 0,
                "row_count": 0,
                "accepted_row_count": 0,
                "review_row_count": 0,
                "_example_images": [],
            },
        )
        bucket["row_count"] += int(row.get("row_count") or 0)
        bucket["accepted_row_count"] += int(row.get("accepted_row_count") or 0)
        bucket["review_row_count"] += int(row.get("review_row_count") or 0)
        bucket["image_count"] += 1
        if len(bucket["_example_images"]) < 3 and row.get("image_file"):
            bucket["_example_images"].append(str(row["image_file"]))

    audit_rows = []
    for bucket in buckets.values():
        audit_row = {field: bucket.get(field, "") for field in fields}
        audit_row["example_images"] = "|".join(bucket["_example_images"])
        audit_rows.append(audit_row)
    audit_rows.sort(
        key=lambda item: (
            str(item["status"]),
            str(item["image_type"]),
            str(item["review_reasons"]),
            str(item["selected_extractor"]),
            str(item["recipe_ids"]),
        )
    )

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audit_rows)
