from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.services.chart_extraction.extractors import ExtractorContext, select_extractor
from app.services.chart_extraction.chart_type_catalog import CHART_TYPE_CATALOG
from app.services.chart_extraction.chart_recipes import chart_recipe_catalog
from app.services.chart_extraction.image_routing import refine_image_type_from_extracted_axes, skip_reason
from app.services.chart_extraction.io import (
    load_image_records,
    write_coordinate_csv,
    write_quality_audit_csv,
    write_summary_csv,
)
from app.services.chart_extraction.models import ImageRecord
from app.services.chart_extraction.plot_geometry import detect_plot_area
from app.services.chart_extraction.quality import annotate_quality, image_status_from_rows, summarize_quality


@dataclass(frozen=True)
class MinerUImageBatchResult:
    summary_path: Path
    combined_csv_path: Path
    quality_audit_path: Path
    manifest_path: Path
    processed: list[dict]


def sample_points(points: list[dict], limit: int, seed: int) -> list[dict]:
    if len(points) <= limit:
        chosen = points
    else:
        chosen = random.Random(seed).sample(points, limit)
    return sorted(
        chosen,
        key=lambda item: (
            str(item.get("color_group", "")),
            float(item["x_coordinate"]),
            float(item["y_coordinate"]),
        ),
    )


def write_overlay(image: np.ndarray, points: list[dict], out_path: Path) -> None:
    overlay = image.copy()
    for idx, point in enumerate(points, start=1):
        x = int(round(float(point["pixel_x"])))
        y = int(round(float(point["pixel_y"])))
        cv2.circle(overlay, (x, y), 5, (0, 0, 255), 1)
        cv2.putText(overlay, str(idx), (x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    cv2.imwrite(str(out_path), overlay)


def process_mineru_image_record(record: ImageRecord, out_dir: Path, sample_limit: int = 15) -> dict:
    image = cv2.imread(str(record.path))
    if image is None:
        return {"image_file": record.path.name, "status": "failed", "reason": "image_unreadable", "row_count": 0}

    reason = skip_reason(record, image)
    if reason:
        return {"image_file": record.path.name, "image_type": "", "status": "skipped", "reason": reason, "row_count": 0}

    area = detect_plot_area(image)
    context = ExtractorContext(record=record, image=image, plot_area=area)
    extractor = select_extractor(context)
    extraction = extractor.extract(context)
    raw_image_type = extraction.image_type
    image_type = refine_image_type_from_extracted_axes(record, raw_image_type, extraction.points)
    routing_status = "refined" if image_type != raw_image_type else "direct"
    selected_extractor = extractor.__class__.__name__
    sampled = sample_points(extraction.points, sample_limit, seed=record.ordinal * 1009)
    rows = []
    for idx, point in enumerate(sampled, start=1):
        row = dict(point)
        row.update(
            {
                "image_file": record.path.name,
                "image_type": image_type,
                "mineru_sub_type": record.mineru_sub_type,
                "series_name": point.get("series_name") or f"{point.get('color_group', 'series')}_{idx}",
                "extraction_method": extraction.extraction_method,
                "selected_extractor": selected_extractor,
                "raw_image_type": raw_image_type,
                "final_image_type": image_type,
                "routing_status": routing_status,
            }
        )
        rows.append(row)
    annotate_quality(rows)

    csv_path = out_dir / f"{record.ordinal:02d}_{record.path.stem}_coordinates.csv"
    overlay_path = out_dir / f"{record.ordinal:02d}_{record.path.stem}_overlay.jpg"
    write_coordinate_csv(csv_path, rows)
    write_overlay(image, sampled, overlay_path)
    return {
        "image_file": record.path.name,
        "image_type": image_type,
        "status": image_status_from_rows(rows),
        "reason": "",
        "row_count": len(rows),
        **summarize_quality(rows),
        "selected_extractor": selected_extractor,
        "raw_image_type": raw_image_type,
        "final_image_type": image_type,
        "routing_status": routing_status,
        "csv_path": str(csv_path),
        "overlay_path": str(overlay_path),
    }


def process_mineru_image_batch(
    *,
    images_dir: Path,
    out_dir: Path,
    content_list_path: Path | None = None,
    sample_limit: int = 15,
    image_path: Path | None = None,
) -> MinerUImageBatchResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = load_image_records(images_dir, content_list_path)
    if image_path:
        resolved_image_path = image_path.resolve()
        records = [record for record in records if record.path.resolve() == resolved_image_path]

    summary = [process_mineru_image_record(record, out_dir, sample_limit) for record in records]
    combined_rows: list[dict] = []
    for item in summary:
        csv_path = item.get("csv_path")
        if not csv_path:
            continue
        with Path(str(csv_path)).open(encoding="utf-8-sig") as handle:
            combined_rows.extend(csv.DictReader(handle))

    combined_path = out_dir / "combined_coordinate_samples.csv"
    if combined_rows:
        write_coordinate_csv(combined_path, combined_rows)

    summary_path = out_dir / "batch_coordinate_summary.csv"
    write_summary_csv(summary_path, summary)
    audit_path = out_dir / "quality_audit_report.csv"
    write_quality_audit_csv(audit_path, summary)
    manifest_path = out_dir / "run_manifest.json"
    manifest_payload = {
        "schema_version": "chart_extraction_run_manifest.v1",
        "inputs": {
            "images_dir": str(images_dir),
            "content_list_path": str(content_list_path) if content_list_path else "",
            "image_path": str(image_path) if image_path else "",
            "sample_limit": sample_limit,
        },
        "outputs": {
            "summary_csv": str(summary_path),
            "combined_csv": str(combined_path),
            "quality_audit_csv": str(audit_path),
        },
        "chart_type_catalog": [
            {
                "image_type": spec.image_type,
                "label": spec.label,
                "processing_chain": spec.processing_chain,
                "suitable_for_csv": spec.suitable_for_csv,
                "coordinate_output": spec.coordinate_output,
                "binding_requirements": list(spec.binding_requirements),
                "requires_review": spec.requires_review,
            }
            for spec in CHART_TYPE_CATALOG
        ],
        "internal_fallback_types": [
            {
                "image_type": "coordinate_plot",
                "label": "通用坐标图兜底",
                "processing_chain": "coordinate_plot",
                "suitable_for_csv": True,
                "coordinate_output": "xy_normalized_or_ocr_csv",
                "binding_requirements": ["axis_tick_binding"],
                "requires_review": True,
                "reason": "Used when MinerU metadata or visual routing cannot bind the image to a more specific planned chart type.",
            }
        ],
        "recipe_catalog": chart_recipe_catalog(),
        "processed": summary,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return MinerUImageBatchResult(
        summary_path=summary_path,
        combined_csv_path=combined_path,
        quality_audit_path=audit_path,
        manifest_path=manifest_path,
        processed=summary,
    )
