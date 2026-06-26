from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models import DocumentAsset
from app.services.content_extraction.models import PropertyRecord
from app.services.content_extraction.prompts import FIGURE_EXTRACTION_SYSTEM_PROMPT
from app.services.extraction.figure_extraction_pipeline import FigureExtractionPipeline
from app.services.file_storage import FileStorageService

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.extraction.classification_pipeline_v2 import IndicatorMapping
    from app.services.markdown_ref_builder import MarkdownDocument

logger = logging.getLogger(__name__)


class FigureExtractor:
    def __init__(self, visual_client: LLMClient) -> None:
        self.visual_client = visual_client
        self._pipeline = FigureExtractionPipeline(visual_client)
        self._storage = FileStorageService()

    def extract(
        self,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        assets: list[DocumentAsset],
        db: Session,
        user_query: str,
    ) -> list[PropertyRecord]:
        image_map = mrf_doc.images_by_label()
        asset_map = self._build_asset_map(assets)
        tasks: list[dict] = []
        records: list[PropertyRecord] = []

        for mapping in mappings:
            if not mapping.figures:
                continue
            for fig_label in mapping.figures:
                img_ref = image_map.get(fig_label)
                asset = (
                    asset_map.get(fig_label)
                    or self._find_asset_by_caption(db, mapping, fig_label, getattr(img_ref, "caption", "") if img_ref else "")
                )
                if not asset or not asset.file_path:
                    continue
                try:
                    image_path = str(self._storage.get_file_path(asset.file_path))
                except Exception as e:
                    logger.warning("Figure asset path resolution failed for %s: %s", fig_label, e)
                    continue
                caption = getattr(img_ref, "caption", "") if img_ref else (asset.caption or "")
                nearby_text = getattr(img_ref, "nearby_text", "") if img_ref else ""
                tasks.append({
                    "mapping": mapping,
                    "fig_label": fig_label,
                    "asset": asset,
                    "image_path": image_path,
                    "caption": caption,
                    "nearby_text": nearby_text,
                })

        if not tasks:
            return records

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_task = {
                executor.submit(self._extract_single, task): task
                for task in tasks
            }
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result_records = future.result()
                    if result_records:
                        records.extend(result_records)
                except Exception as e:
                    logger.warning("Figure extraction failed for %s: %s", task["fig_label"], e)

        return records

    def _extract_single(self, task: dict) -> list[PropertyRecord]:
        mapping = task["mapping"]
        fig_label = task["fig_label"]
        asset = task["asset"]
        image_path = task["image_path"]
        caption = task["caption"]
        nearby_text = task["nearby_text"]

        result = self._pipeline.extract(
            image_path=image_path,
            figure_label=fig_label,
            caption=caption,
            nearby_text=nearby_text,
            extraction_hint=mapping.extraction_hint,
        )
        chart_type = (result.chart_type or "").lower()
        non_data_types = {"microscopy", "schematic", "schematic_or_photo", "non_data_image", "error"}
        if chart_type in non_data_types:
            return []

        asset_bbox = _safe_parse_json_field(asset.metadata_json).get("bbox")
        figure_payload = {
            "chart_type": chart_type or result.chart_type,
            "figure_label": fig_label,
            "caption": caption,
            "axes": {
                "x_axis": _axis_payload(result.x_axis),
                "y_axis": _axis_payload(result.y_axis),
                "y2_axis": _axis_payload(result.y2_axis) if result.y2_axis else None,
            },
            "bbox": asset_bbox,
            "legend": result.series,
        }
        records: list[PropertyRecord] = []
        for pt in result.data_points:
            property_name = result.y_axis.label or mapping.indicator
            condition = ""
            if result.x_axis.label:
                condition = f"{result.x_axis.label}: {pt.x_value}"
                if result.x_axis.unit:
                    condition += f" {result.x_axis.unit}"
            point_payload = {
                **figure_payload,
                "point": {
                    "series": pt.series_name or "",
                    "x": pt.x_value,
                    "y": pt.y_value,
                    "x_unit": pt.x_unit,
                    "y_unit": pt.y_unit,
                    "error_bar": pt.error_bar or "",
                },
            }

            records.append(PropertyRecord(
                entity=pt.series_name or fig_label or mapping.indicator,
                property_name=property_name,
                property_category="",
                value_text=f"{pt.y_value} {pt.y_unit}",
                value_numeric=pt.y_value,
                value_unit=pt.y_unit or None,
                condition=condition,
                method=chart_type,
                confidence=result.extraction_confidence,
                source_type="figure",
                source_ref=fig_label,
                source_cell_range=figure_payload.get("cell_range"),
                source_bbox=_to_json_string(asset_bbox),
                source_mrf_node_id=f"figure:{fig_label}",
                source_page=asset.page_number,
                source_asset_id=asset.id,
                evidence_excerpt=(
                    f"{fig_label}: {condition}, {property_name} = {pt.y_value}"
                    + (f", {pt.error_bar}" if pt.error_bar else "")
                ),
                evidence_payload=json.dumps(point_payload, ensure_ascii=False),
                extraction_method="figure_vlm",
            ))

        return records

    def _build_asset_map(self, assets: list[DocumentAsset]) -> dict[str, DocumentAsset]:
        asset_map: dict[str, DocumentAsset] = {}
        for asset in assets:
            if asset.label:
                asset_map[asset.label] = asset
        return asset_map

    def _find_asset_by_caption(
        self,
        db: Session,
        _mapping: IndicatorMapping,
        _fig_label: str,
        caption: str,
    ) -> DocumentAsset | None:
        if not caption:
            return None
        assets = (
            db.query(DocumentAsset)
            .filter(
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            )
            .all()
        )
        for asset in assets:
            if asset.caption and caption.lower() in asset.caption.lower():
                return asset
        return None


def _axis_payload(axis) -> dict:
    return {
        "label": getattr(axis, "label", "") or "",
        "unit": getattr(axis, "unit", "") or "",
        "scale": getattr(axis, "scale", "") or "",
        "range_min": getattr(axis, "range_min", None),
        "range_max": getattr(axis, "range_max", None),
        "tick_values": list(getattr(axis, "tick_values", []) or []),
        "calibration_confidence": getattr(axis, "calibration_confidence", None),
    }


def _safe_parse_json_field(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _to_json_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)
