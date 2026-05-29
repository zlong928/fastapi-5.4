from __future__ import annotations

import json
from typing import Any

from app.models import DocumentAsset

EVIDENCE_TYPES = {"text", "table", "figure", "chart", "equation", "page_region", "unknown"}
VISUAL_EVIDENCE_TYPES = {"figure", "chart"}


def asset_metadata(asset: DocumentAsset | None) -> dict[str, Any]:
    if asset is None or not asset.metadata_json:
        return {}
    try:
        parsed = json.loads(asset.metadata_json)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_evidence_type(
    *,
    source_type: str | None = None,
    asset: DocumentAsset | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    metadata = metadata if metadata is not None else asset_metadata(asset)
    raw_type = metadata.get("evidence_type") or metadata.get("evidenceType")
    if raw_type is not None:
        normalized = str(raw_type).strip().lower()
        if normalized in EVIDENCE_TYPES:
            return normalized
        if normalized in {"image", "visual", "picture"}:
            return "figure"
        if normalized in {"text_region", "ocr_text"}:
            return "text"

    if source_type == "text":
        return "text"
    if source_type == "table":
        return "table"
    if source_type == "figure":
        return "figure"

    if asset is None:
        return "unknown"

    source = str(metadata.get("source") or "")
    visual_role = str(metadata.get("visual_role") or "")
    if asset.asset_type == "table":
        return "table"
    if asset.asset_type == "equation":
        return "equation"
    if asset.asset_type == "page_snapshot" or source in {"page_visual_snapshot", "fallback_snapshot"}:
        return "page_region"
    if source == "extracted_image":
        return "figure"
    if source == "rendered_figure_region":
        if visual_role in {"chart", "chart_candidate"}:
            return "chart"
        if visual_role in {"figure", "figure_candidate", "image_object"} and asset.file_path:
            return "figure"
        return "page_region"
    if asset.asset_type == "figure" and asset.file_path:
        return "figure"
    return "unknown"


def is_visual_evidence(asset: DocumentAsset) -> bool:
    return normalize_evidence_type(asset=asset) in VISUAL_EVIDENCE_TYPES


def asset_image_url(asset: DocumentAsset | None) -> str | None:
    if asset is None or not asset.file_path:
        return None
    mime_type = (asset.mime_type or "").lower()
    if mime_type and not mime_type.startswith("image/"):
        return None
    return f"/papers/assets/{asset.id}"


def asset_bbox(metadata: dict[str, Any]) -> list[float] | None:
    raw_bbox = metadata.get("bbox")
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        return [float(value) for value in raw_bbox]
    except (TypeError, ValueError):
        return None
