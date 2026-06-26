from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, DocumentAsset, ExtractionJob, ExtractionResult
from app.schemas.paper import ChartTypeRuntimeStats, PaperFigureAsset, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult
from app.services.chart_extraction import CHART_TYPE_CATALOG
from app.services.extraction.formatters import confidence_label, display_field_name, is_negative_result_text, legacy_localized_value
from app.services.paper.coordinate_preview import coordinate_preview_read, is_coordinate_asset
from app.services.paper.evidence import asset_image_url, asset_metadata, normalize_evidence_type
from app.services.paper.visual_assets import display_visual_assets


def should_hide_legacy_result(result: ExtractionResult) -> bool:
    if result.extraction_mode == "not_found":
        return False
    if result.confidence is not None and result.confidence < 0.5:
        return True
    if result.source_type in {"asset", "figure", "chart"} or result.figure_id:
        return is_negative_result_text(result.content) or is_negative_result_text(result.notes)
    return not (result.content or "").strip() or not (result.evidence or "").strip() or is_negative_result_text(result.content)


def asset_source(asset: DocumentAsset | None, metadata: dict | None = None) -> str | None:
    if asset is None:
        return None
    metadata = metadata if metadata is not None else asset_metadata(asset)
    return str(metadata.get("source") or asset.asset_type) or None


def chart_type_stats(figure_assets: list[DocumentAsset]) -> list[ChartTypeRuntimeStats]:
    buckets = {
        spec.image_type: {
            "image_type": spec.image_type,
            "total": 0,
            "accepted": 0,
            "review_required": 0,
            "skipped": 0,
            "failed": 0,
            "row_count": 0,
        }
        for spec in CHART_TYPE_CATALOG
    }
    for asset in figure_assets:
        metadata = asset_metadata(asset)
        preview = metadata.get("coordinate_preview")
        if not isinstance(preview, dict):
            continue
        image_type = str(preview.get("image_type") or metadata.get("image_type") or metadata.get("chart_type") or "")
        if image_type not in buckets:
            continue
        bucket = buckets[image_type]
        status_value = str(preview.get("status") or "")
        bucket["total"] += 1
        bucket["row_count"] += int(preview.get("row_count") or 0)
        if status_value == "accepted":
            bucket["accepted"] += 1
        elif status_value == "review_required":
            bucket["review_required"] += 1
        elif status_value == "skipped":
            bucket["skipped"] += 1
        elif status_value == "failed":
            bucket["failed"] += 1
    return [ChartTypeRuntimeStats(**bucket) for bucket in buckets.values()]


def build_legacy_structured_extraction(db: Session, job: ExtractionJob, paper: Document | None) -> StructuredExtractionResponse:
    results = sorted(job.results, key=lambda row: row.id)
    assets_map = _assets_by_id(db, results)
    figure_assets = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == job.paper_id, DocumentAsset.asset_type.in_(["figure", "page_snapshot"]))
        .all()
    )
    figure_assets = display_visual_assets(figure_assets)
    all_figure_assets = {asset.id: asset for asset in figure_assets if asset.file_path}

    figure_results: list[StructuredFigureResult] = []
    table_results: list[StructuredTableResult] = []
    text_results: list[StructuredTextResult] = []
    not_found: list[str] = []

    for result in results:
        if should_hide_legacy_result(result):
            continue
        asset = assets_map.get(result.source_id) if result.source_id else None
        metadata = asset_metadata(asset)
        evidence_type = normalize_evidence_type(source_type=result.source_type, asset=asset, metadata=metadata)
        if result.extraction_mode == "not_found":
            not_found.append(result.field_name)
            continue
        is_figure_result = (
            (evidence_type in ("figure", "chart", "page_region") and asset and asset.file_path)
            or result.figure_id is not None
            or (result.source_type == "asset" and result.source_id and result.source_id in all_figure_assets)
        )
        if is_figure_result:
            image_asset = asset or (all_figure_assets.get(result.source_id) if result.source_id else None)
            image_metadata = asset_metadata(image_asset) if image_asset else {}
            figure_results.append(
                StructuredFigureResult(
                    id=result.id,
                    figure_id=result.figure_id or str(image_metadata.get("figure_label") or (f"Asset {image_asset.id}" if image_asset else "")),
                    caption=result.caption or str(image_metadata.get("caption") or ""),
                    image_url=asset_image_url(image_asset),
                    page=image_asset.page_number if image_asset else None,
                    evidence_type=evidence_type,
                    source=asset_source(image_asset, image_metadata),
                    metric=display_field_name(result.field_name, result.source_type, result.figure_id),
                    value=result.content,
                    evidence=result.evidence,
                    confidence=confidence_label(result.confidence),
                    notes=result.notes,
                )
            )
        elif evidence_type == "table":
            table_results.append(
                StructuredTableResult(
                    id=result.id,
                    table_id=str(asset.label or f"Table {asset.id}") if asset else None,
                    structured_data=result.structured_data,
                    parse_status=result.parse_status,
                    page=asset.page_number if asset else None,
                    evidence_type=evidence_type,
                    source=asset_source(asset, metadata),
                    metric=display_field_name(result.field_name, result.source_type, result.figure_id),
                    value=result.content,
                    evidence=result.evidence,
                    notes=result.notes,
                )
            )
        else:
            metric = display_field_name(result.field_name, result.source_type, result.figure_id)
            text_results.append(
                StructuredTextResult(
                    id=result.id,
                    metric=metric,
                    value=legacy_localized_value(metric, result.content or ""),
                    evidence=result.evidence,
                    page=asset.page_number if asset else None,
                    evidence_type=evidence_type,
                    source=asset_source(asset, metadata),
                    confidence=confidence_label(result.confidence),
                )
            )

    paper_figures: list[PaperFigureAsset] = []
    for figure_asset in all_figure_assets.values():
        figure_metadata = asset_metadata(figure_asset)
        figure_source = str(figure_metadata.get("source") or "")
        if figure_source == "fallback_snapshot":
            continue
        paper_figures.append(
            PaperFigureAsset(
                id=figure_asset.id,
                figure_label=str(figure_metadata.get("figure_label") or figure_asset.label or f"Asset {figure_asset.id}"),
                caption=str(figure_metadata.get("caption") or figure_asset.caption or ""),
                image_url=asset_image_url(figure_asset),
                page=figure_asset.page_number,
                source=figure_source or figure_asset.asset_type,
                evidence_type=normalize_evidence_type(asset=figure_asset, metadata=figure_metadata),
                asset_type=figure_asset.asset_type,
                coordinate_capable=is_coordinate_asset(figure_asset, figure_metadata),
                coordinate_preview=coordinate_preview_read(figure_asset, figure_metadata),
            )
        )
    paper_figures.sort(key=lambda row: (row.page or 999, row.id))

    summary = {
        "figures_analyzed": len(figure_results),
        "tables_analyzed": len(table_results),
        "text_items_extracted": len(text_results),
        "failed_items": len(not_found),
        "total_results": len(results),
        "paper_figure_count": len([asset for asset in all_figure_assets.values() if asset.asset_type == "figure"]),
    }
    return StructuredExtractionResponse(
        paper_id=job.paper_id,
        title=paper.title if paper else "",
        task=job.query,
        status=job.status,
        error_message=job.error_message,
        summary=summary,
        figure_results=figure_results,
        table_results=table_results,
        text_results=text_results,
        not_found=not_found,
        paper_figures=paper_figures,
        chart_type_stats=chart_type_stats(list(all_figure_assets.values())),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _assets_by_id(db: Session, results: list[ExtractionResult]) -> dict[int, DocumentAsset]:
    asset_ids = sorted({result.source_id for result in results if result.source_id is not None and result.source_type in {"asset", "figure", "table"}})
    if not asset_ids:
        return {}
    assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
    return {asset.id: asset for asset in assets}
