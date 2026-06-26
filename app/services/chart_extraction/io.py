from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from app.services.chart_extraction.models import ImageRecord


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

COORDINATE_CSV_FIELDS = [
    "indicator", "series_name",
    "x_value", "x_unit",
    "y_value", "y_unit",
    "confidence", "quality_tags",
]

RHEOLOGY_STEP_TIME_SWEEP_CSV_FIELDS = COORDINATE_CSV_FIELDS

# ── ImageRecords ──────────────────────────────────────────────────────────


def load_image_records(images_dir: Path, content_list_path: Path | None) -> list[ImageRecord]:
    """Load image records from a directory, merging metadata from a JSON content list."""
    by_path: dict[str, tuple[int, dict]] = {}
    if content_list_path and content_list_path.is_file():
        for index, item in enumerate(json.loads(content_list_path.read_text("utf-8"))):
            if isinstance(item, dict) and item.get("img_path"):
                by_path[str(item["img_path"])] = (index, item)

    records: list[ImageRecord] = []
    image_paths = sorted(p for p in images_dir.glob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    for ordinal, path in enumerate(image_paths, start=1):
        content_index, item = by_path.get(f"images/{path.name}", (ordinal, {}))
        captions = item.get("image_caption") or item.get("chart_caption") or []
        caption = " ".join(str(p) for p in captions) if isinstance(captions, list) else str(captions or "")
        records.append(ImageRecord(
            ordinal=ordinal, path=path, content_index=content_index,
            mineru_type=str(item.get("type") or ""),
            mineru_sub_type=str(item.get("sub_type") or ""),
            caption=caption, content=str(item.get("content") or ""),
        ))
    return records


# ── Coordinate CSV (semantic headers) ────────────────────────────────────


def _first_present(row: dict, *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return ""


def _semantic_value_field(rows: list[dict], axis: str) -> str:
    """Find the first non-default column name for axis values across rows.

    Uses row axis-label + unit to produce e.g. "Shear rate (s⁻¹)" instead of "x_value".
    """
    for row in rows:
        label = " ".join(str(_first_present(row, f"{axis}_axis_label", f"{axis}_label") or "").strip().split())
        unit = " ".join(str(_first_present(row, f"{axis}_unit", f"{axis}_axis_unit") or "").strip().split())
        if label:
            return f"{label} ({unit})" if unit and unit.lower() not in label.lower() else label
    return f"{axis}_value"


def write_coordinate_csv(path: Path, rows: list[dict]) -> None:
    """Write a coordinate CSV with dynamically-named x/y columns."""
    x_field = _semantic_value_field(rows, "x")
    y_field = _semantic_value_field(rows, "y")
    fieldnames = ["indicator", "series_name", x_field, "x_unit", y_field, "y_unit",
                  "x_scale", "y_scale", "confidence", "quality_tags"]

    def _build(row: dict) -> dict:
        x_unit = " ".join(str(_first_present(row, "x_axis_unit", "x_unit") or "").strip().split())
        y_unit = " ".join(str(_first_present(row, "y_axis_unit", "y_unit") or "").strip().split())
        return {
            "indicator": _first_present(row, "indicator", "field_name", "metric"),
            "series_name": _first_present(row, "series_id", "series_name"),
            x_field: _first_present(row, "x_value", "x", "x_strain_percent", "x_coordinate"),
            "x_unit": x_unit,
            y_field: _first_present(row, "y_value", "y", "y_modulus_pa", "y_coordinate"),
            "y_unit": y_unit,
            "x_scale": row.get("x_scale", ""),
            "y_scale": row.get("y_scale", ""),
            "confidence": row.get("confidence", ""),
            "quality_tags": row.get("quality_tags", ""),
        }

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(_build(r) for r in rows)


# ── Summary & Audit CSVs ─────────────────────────────────────────────────


SUMMARY_CSV_FIELDS = [
    "image_file", "image_type", "status", "reason",
    "row_count", "accepted_row_count", "data_quality",
    "recipe_ids", "panel_ids", "axis_calibration_methods",
    "csv_path", "overlay_path",
]


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_CSV_FIELDS)
        w.writeheader()
        w.writerows({f: row.get(f, "") for f in SUMMARY_CSV_FIELDS} for row in rows)


def write_quality_audit_csv(path: Path, summary_rows: list[dict]) -> None:
    """Group summary rows by (type, status, extractor, ...) and write aggregated audit CSV."""
    fields = [
        "image_type", "status", "data_quality",
        "recipe_ids", "axis_calibration_methods", "review_reasons",
        "image_count", "row_count", "accepted_row_count", "review_row_count",
        "example_images",
    ]

    def _group_key(row: dict) -> tuple[str, ...]:
        return tuple(str(row.get(k) or "") for k in fields[:10])

    buckets: dict[tuple[str, ...], dict] = defaultdict(lambda: {
        **{k: "" for k in fields[:10]},
        "image_count": 0, "row_count": 0,
        "accepted_row_count": 0, "review_row_count": 0,
        "_example_images": [],
    })

    for row in summary_rows:
        key = _group_key(row)
        b = buckets[key]
        # Populate key fields on first encounter
        if not b["image_count"]:
            for i, k in enumerate(fields[:10]):
                b[k] = key[i]
        b["row_count"] += int(row.get("row_count") or 0)
        b["accepted_row_count"] += int(row.get("accepted_row_count") or 0)
        b["review_row_count"] += int(row.get("review_row_count") or 0)
        b["image_count"] += 1
        if len(b["_example_images"]) < 3 and row.get("image_file"):
            b["_example_images"].append(str(row["image_file"]))

    audit_rows = sorted(
        [{**b, "example_images": "|".join(b["_example_images"])} for b in buckets.values()],
        key=lambda r: (r["status"], r["image_type"], r["review_reasons"]),
    )

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(audit_rows)
