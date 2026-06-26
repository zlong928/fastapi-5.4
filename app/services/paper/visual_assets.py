from __future__ import annotations

import re
from typing import Any

from app.models import DocumentAsset
from app.services.paper.evidence import asset_metadata

VISUAL_ASSET_TYPES = {"figure", "page_snapshot"}
MINERU_VISUAL_SOURCES = {"mineru_chart", "mineru_image", "mineru_markdown"}
REGION_VISUAL_SOURCES = {"rendered_figure_region"}
LEGACY_PARENT_SOURCES = {"extracted_image"}
PAGE_SNAPSHOT_SOURCES = {"page_visual_snapshot", "fallback_snapshot"}


def visual_asset_source(asset: DocumentAsset, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata if metadata is not None else asset_metadata(asset)
    return str(metadata.get("source") or "").strip()


def is_mineru_visual_asset(asset: DocumentAsset, metadata: dict[str, Any] | None = None) -> bool:
    return visual_asset_source(asset, metadata) in MINERU_VISUAL_SOURCES


def is_page_snapshot_asset(asset: DocumentAsset, metadata: dict[str, Any] | None = None) -> bool:
    metadata = metadata if metadata is not None else asset_metadata(asset)
    source = visual_asset_source(asset, metadata)
    visual_role = str(metadata.get("visual_role") or "").strip()
    if source in MINERU_VISUAL_SOURCES or source in REGION_VISUAL_SOURCES:
        return False
    return asset.asset_type == "page_snapshot" or source in PAGE_SNAPSHOT_SOURCES or visual_role in {"page_evidence", "fallback_snapshot"}


def _normalized_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _figure_key(asset: DocumentAsset, metadata: dict[str, Any]) -> tuple[int | None, str] | None:
    label = _normalized_label(metadata.get("figure_label") or metadata.get("label") or asset.label)
    if not label:
        caption = _normalized_label(metadata.get("caption") or asset.caption)
        match = re.search(r"\bfig(?:ure)?\.?\s*\d+[a-z]?\b", caption)
        label = match.group(0) if match else caption[:80]
    if not label:
        return None
    return asset.page_number, label


def display_visual_assets(assets: list[DocumentAsset]) -> list[DocumentAsset]:
    """Return the visual assets that should be shown on paper/result pages.

    The database can retain raw parser artifacts, but the product surface should
    prefer the most atomic visual evidence: MinerU crops first, then rendered
    figure regions, then legacy PDF image objects, with page snapshots only as a
    fallback when there is no finer visual asset for that page.
    """

    visual_assets = [asset for asset in assets if asset.asset_type in VISUAL_ASSET_TYPES and asset.asset_type != "page_snapshot"]
    metadata_by_id = {asset.id: asset_metadata(asset) for asset in visual_assets}
    mineru_assets = [asset for asset in visual_assets if is_mineru_visual_asset(asset, metadata_by_id[asset.id])]
    if mineru_assets:
        return mineru_assets

    rendered_region_keys = {
        key
        for asset in visual_assets
        if visual_asset_source(asset, metadata_by_id[asset.id]) in REGION_VISUAL_SOURCES
        for key in [_figure_key(asset, metadata_by_id[asset.id])]
        if key is not None
    }
    pages_with_fine_assets = {
        asset.page_number
        for asset in visual_assets
        if asset.asset_type == "figure" and not is_page_snapshot_asset(asset, metadata_by_id[asset.id])
    }

    visible: list[DocumentAsset] = []
    for asset in visual_assets:
        metadata = metadata_by_id[asset.id]
        source = visual_asset_source(asset, metadata)
        key = _figure_key(asset, metadata)
        if source in LEGACY_PARENT_SOURCES and key in rendered_region_keys:
            continue
        if is_page_snapshot_asset(asset, metadata) and asset.page_number in pages_with_fine_assets:
            continue
        if source == "fallback_snapshot":
            continue
        visible.append(asset)
    return visible
