from __future__ import annotations

import logging
import random
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.services.chart_extraction.io import (
    load_image_records,
    write_quality_audit_csv,
    write_coordinate_csv,
    write_summary_csv,
)
from app.services.chart_extraction.models import ImageRecord
from app.services.chart_extraction.quality import summarize_quality


logger = logging.getLogger(__name__)


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
        chosen = _stratified_sample_points(points, limit, seed)
    return sorted(
        chosen,
        key=lambda item: (
            str(item.get("panel_id", "")),
            str(item.get("series_id", "")),
            str(item.get("curve_role", "")),
            str(item.get("color_group", "")),
            float(item.get("x_coordinate", 0)),
            float(item.get("y_coordinate", 0)),
        ),
    )


def _stratified_sample_points(points: list[dict], limit: int, seed: int) -> list[dict]:
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    for point in points:
        key = (
            str(point.get("panel_id") or ""),
            str(point.get("series_id") or point.get("color_group") or ""),
            str(point.get("curve_role") or ""),
        )
        buckets.setdefault(key, []).append(point)
    if len(buckets) <= 1:
        return random.Random(seed).sample(points, limit)

    rng = random.Random(seed)
    ordered_keys = sorted(buckets, key=lambda key: (key[0], key[1], key[2]))
    selected: list[dict] = []
    used_ids: set[int] = set()
    base_quota = max(1, limit // len(ordered_keys))
    for key in ordered_keys:
        bucket = buckets[key]
        quota = min(len(bucket), base_quota)
        picks = rng.sample(bucket, quota) if len(bucket) > quota else list(bucket)
        selected.extend(picks)
        used_ids.update(id(point) for point in picks)

    remaining = max(0, limit - len(selected))
    if remaining:
        leftovers = [point for key in ordered_keys for point in buckets[key] if id(point) not in used_ids]
        if len(leftovers) > remaining:
            leftovers = rng.sample(leftovers, remaining)
        selected.extend(leftovers)
    return selected[:limit]


def write_overlay(image: np.ndarray, points: list[dict], out_path: Path) -> None:
    overlay = image.copy()
    for idx, point in enumerate(points, start=1):
        x = int(round(float(point["pixel_x"])))
        y = int(round(float(point["pixel_y"])))
        cv2.circle(overlay, (x, y), 5, (0, 0, 255), 1)
        cv2.putText(overlay, str(idx), (x + 4, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    cv2.imwrite(str(out_path), overlay)


def process_mineru_image_record(
    record: ImageRecord,
    out_dir: Path,
    sample_limit: int = 15,
) -> dict:
    from app.services.chart_extraction.multi_agent_orchestrator import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator()
    result = orchestrator.extract(record, out_dir, sample_limit)

    return {
        "image_file": result.image_file,
        "image_type": result.image_type,
        "status": result.status,
        "reason": result.reason,
        "row_count": result.row_count,
        **summarize_quality(result.points),
        "verification_passed": result.verification_passed,
        "verification_confidence": result.verification_confidence,
        "csv_path": result.csv_path,
        "overlay_path": result.overlay_path,
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
        image_name = image_path.name
        original_count = len(records)

        records = [record for record in records if record.path.resolve() == resolved_image_path]

        if not records:
            all_records = load_image_records(images_dir, content_list_path)
            records = [record for record in all_records if record.path.name == image_name]
            if records:
                logger.info(
                    "image_path matched by filename: images_dir=%s filename=%s",
                    images_dir,
                    image_name,
                )

        if not records:
            logger.warning(
                "image_path filter resulted in empty records: images_dir=%s image_path=%s original_records=%d",
                images_dir,
                image_path,
                original_count,
            )
            if original_count > 0:
                logger.warning(
                    "available record paths: %s",
                    [str(r.path.resolve()) for r in load_image_records(images_dir, content_list_path)[:5]],
                )

    summary = []
    for record in records:
        for attempt in range(2):
            try:
                result = process_mineru_image_record(record, out_dir, sample_limit)
                summary.append(result)
                break
            except Exception:
                logger.exception("image_pipeline fatal error image=%s attempt=%d", record.path.name, attempt + 1)
                if attempt == 0:
                    continue
                summary.append({"image_file": record.path.name, "status": "failed", "reason": "unexpected_error", "row_count": 0})

    combined_path = out_dir / "combined_coordinate_samples.csv"
    summary_path = out_dir / "batch_coordinate_summary.csv"
    audit_path = out_dir / "quality_audit_report.csv"
    manifest_path = out_dir / "run_manifest.json"
    write_summary_csv(summary_path, summary)
    write_quality_audit_csv(audit_path, summary)
    _write_combined_coordinate_csv(combined_path, summary)
    _write_run_manifest(
        manifest_path,
        images_dir=images_dir,
        content_list_path=content_list_path,
        out_dir=out_dir,
        sample_limit=sample_limit,
        image_path=image_path,
        summary=summary,
    )
    return MinerUImageBatchResult(
        summary_path=summary_path,
        combined_csv_path=combined_path,
        quality_audit_path=audit_path,
        manifest_path=manifest_path,
        processed=summary,
    )


def _write_combined_coordinate_csv(path: Path, summary: list[dict]) -> None:
    csv_paths = [Path(str(row.get("csv_path") or "")) for row in summary if row.get("csv_path")]
    header: str | None = None
    lines: list[str] = []
    for csv_path in csv_paths:
        if not csv_path.is_file():
            continue
        file_lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
        if not file_lines:
            continue
        if header is None:
            header = file_lines[0]
            lines.append(header)
        if file_lines[0] != header:
            continue
        lines.extend(file_lines[1:])
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8-sig")


def _write_run_manifest(
    path: Path,
    *,
    images_dir: Path,
    content_list_path: Path | None,
    out_dir: Path,
    sample_limit: int,
    image_path: Path | None,
    summary: list[dict],
) -> None:
    payload = {
        "schema_version": "mineru_image_coordinate_batch.v1",
        "images_dir": str(images_dir),
        "content_list_path": str(content_list_path) if content_list_path else "",
        "out_dir": str(out_dir),
        "sample_limit": sample_limit,
        "image_path": str(image_path) if image_path else "",
        "image_count": len(summary),
        "processed": summary,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
