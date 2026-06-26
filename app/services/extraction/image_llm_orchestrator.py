from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.agent.llm_client import LLMClient
from app.services.agent.types import FigureExtractionPlan, ImageType
from app.services.agent.visual_agents import (
    BarChartAgent,
    CoordinateExtractionAgent,
    HeatmapAgent,
    ImageClassifierAgent,
    NonDataVisualAgent,
    TableImageAgent,
    image_type_from_string,
)
from app.services.extraction.figure_extraction_pipeline import FigureExtractionPipeline, FigureExtractionResult
from app.services.extraction.llm_config import build_vlm_config

if TYPE_CHECKING:
    from app.services.chart_extraction.models import ImageRecord


logger = logging.getLogger(__name__)

_NON_DATA_TYPES = {
    ImageType.NON_DATA_IMAGE,
    ImageType.MICROSCOPY_QUANT,
    ImageType.SCHEMATIC,
    ImageType.SCHEMATIC_OR_PHOTO,
    ImageType.MULTI_PANEL_COMPOSITE,
}
_TABLE_TYPES = {ImageType.TABLE_IMAGE}
_BAR_TYPES = {ImageType.BAR_CHART, ImageType.GROUPED_BAR, ImageType.BAR_OR_LINE_WITH_ERRORBAR}
_HEATMAP_TYPES = {ImageType.HEATMAP, ImageType.HEATMAP_MATRIX, ImageType.FIELD_2D_MAP}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


@dataclass
class IndicatorBinding:
    indicator_name: str
    indicator_aliases: list[str] = field(default_factory=list)
    binding_reason: str = ""
    expected_value_shape: str = "series"
    expected_unit_candidates: list[str] = field(default_factory=list)
    text_evidence_refs: list[str] = field(default_factory=list)
    priority: str = "high"


@dataclass
class ImageRoutingDecision:
    image_type: str
    is_data_bearing: bool
    route_family: str
    has_axes: bool
    has_table_structure: bool
    candidate_indicators: list[str] = field(default_factory=list)
    classification_confidence: float = 0.0
    fallback_reason: str = ""
    binding_candidates: list[IndicatorBinding] = field(default_factory=list)


@dataclass
class SemanticExtractionResult:
    image_type: str
    figure_label: str
    indicator_bindings: list[IndicatorBinding] = field(default_factory=list)
    series_name: str = ""
    x_axis_label: str = ""
    x_axis_unit: str = ""
    x_axis_scale: str = ""
    y_axis_label: str = ""
    y_axis_unit: str = ""
    y_axis_scale: str = ""
    value_text: str = ""
    value_numeric: float | None = None
    value_unit: str = ""
    value_error: str = ""
    data_points: list[dict[str, Any]] = field(default_factory=list)
    text_evidence_refs: list[str] = field(default_factory=list)
    review_status: str = "pending"
    review_notes: str = ""
    extraction_method: str = ""
    confidence: float = 0.0
    llm_succeeded: bool = False


class LLMImageExtractionOrchestrator:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient(build_vlm_config())
        self.classifier = ImageClassifierAgent(self.client)
        self.coordinate_agent = CoordinateExtractionAgent(self.client)
        self.bar_agent = BarChartAgent(self.client)
        self.heatmap_agent = HeatmapAgent(self.client)
        self.table_agent = TableImageAgent(self.client)
        self.non_data_agent = NonDataVisualAgent(self.client)
        self.figure_pipeline = FigureExtractionPipeline(self.client)

    @classmethod
    def from_env(cls) -> "LLMImageExtractionOrchestrator":
        return cls()

    def route_image(
        self,
        *,
        image_path: str,
        figure_label: str,
        caption: str,
        nearby_text: str,
        indicator_hints: list[str] | None = None,
    ) -> ImageRoutingDecision:
        plan = FigureExtractionPlan(
            figure_id=figure_label or image_path,
            image_path=image_path,
            caption=caption,
            review_notes=nearby_text,
        )
        first_type = self.classifier.classify(plan)
        first_decision = self._decision_for_type(
            image_type=first_type,
            caption=caption,
            nearby_text=nearby_text,
            indicator_hints=indicator_hints or [],
            confidence=0.65 if first_type != ImageType.UNKNOWN else 0.0,
        )
        if first_type != ImageType.UNKNOWN:
            return first_decision

        second_type, confidence, reason = self._reclassify_with_context(plan, indicator_hints or [])
        decision = self._decision_for_type(
            image_type=second_type,
            caption=caption,
            nearby_text=nearby_text,
            indicator_hints=indicator_hints or [],
            confidence=confidence,
        )
        if second_type == ImageType.UNKNOWN:
            fallback_type = self._force_explicit_type(caption, nearby_text)
            decision = self._decision_for_type(
                image_type=fallback_type,
                caption=caption,
                nearby_text=nearby_text,
                indicator_hints=indicator_hints or [],
                confidence=0.2,
            )
            decision.fallback_reason = reason or "unknown_mapped_to_explicit_type"
        else:
            decision.fallback_reason = reason
        return decision

    def extract_semantic_data(
        self,
        *,
        image_path: str,
        figure_label: str,
        caption: str,
        nearby_text: str,
        indicator_hints: list[str] | None = None,
    ) -> SemanticExtractionResult:
        plan = FigureExtractionPlan(
            figure_id=figure_label or image_path,
            image_path=image_path,
            caption=caption,
            review_notes=nearby_text,
        )

        figure_result = self.figure_pipeline.extract(
            image_path=image_path,
            figure_label=figure_label,
            caption=caption,
            nearby_text=nearby_text,
            extraction_hint="",
            chart_type_hint="",
        )

        if figure_result.chart_type == "error":
            return SemanticExtractionResult(
                image_type=ImageType.UNKNOWN.value,
                figure_label=figure_label,
                review_status="llm_failed",
                review_notes=figure_result.overall_description,
                extraction_method="",
                confidence=0.0,
                llm_succeeded=False,
            )

        image_type = self._chart_type_to_image_type(figure_result.chart_type)
        is_data_bearing = image_type not in _NON_DATA_TYPES

        bindings = self._bind_indicators(
            caption=caption,
            nearby_text=nearby_text,
            indicator_hints=indicator_hints or [],
        )
        text_refs = [ref for binding in bindings for ref in binding.text_evidence_refs]

        if not is_data_bearing:
            notes = _clean_text(figure_result.overall_description) or image_type.value
            return SemanticExtractionResult(
                image_type=image_type.value,
                figure_label=figure_label,
                indicator_bindings=bindings,
                text_evidence_refs=text_refs,
                review_status="non_data_image",
                review_notes=notes,
                extraction_method="llm_figure_extraction",
                confidence=figure_result.extraction_confidence or 0.5,
                llm_succeeded=True,
            )

        agent_payload: dict = {}
        if not figure_result.data_points:
            plan.image_type = image_type
            agent_payload = self._route_specialist(plan)

        review_status, review_notes = self._review_result(figure_result, bindings)
        points = self._points_from_figure_result(figure_result)
        if not points and agent_payload:
            points = self._points_from_payload(agent_payload, figure_result)
        value_numeric = points[0].get("y") if points else figure_result.y_axis.range_max
        value_unit = figure_result.y_axis.unit or self._fallback_value_unit(bindings)
        value_text = self._build_value_text(value_numeric, value_unit, figure_result.series)
        return SemanticExtractionResult(
            image_type=image_type.value,
            figure_label=figure_label,
            indicator_bindings=bindings,
            series_name=figure_result.series[0] if figure_result.series else "",
            x_axis_label=self._semantic_axis_label(figure_result.x_axis.label, figure_result.x_axis.unit, bindings, "x"),
            x_axis_unit=figure_result.x_axis.unit,
            x_axis_scale=figure_result.x_axis.scale,
            y_axis_label=self._semantic_axis_label(figure_result.y_axis.label, figure_result.y_axis.unit, bindings, "y"),
            y_axis_unit=figure_result.y_axis.unit,
            y_axis_scale=figure_result.y_axis.scale,
            value_text=value_text,
            value_numeric=value_numeric,
            value_unit=value_unit,
            value_error=points[0].get("error_bar", "") if points else "",
            data_points=points,
            text_evidence_refs=text_refs,
            review_status=review_status,
            review_notes=review_notes,
            extraction_method=_clean_text(agent_payload.get("extraction_method")) if agent_payload else "llm_figure_extraction",
            confidence=float(figure_result.extraction_confidence or 0.0),
            llm_succeeded=bool(points or figure_result.x_axis.label or figure_result.y_axis.label),
        )

    def extractor_result_from_record(self, record: "ImageRecord"):
        try:
            from app.services.chart_extraction.extractors.base import ExtractorResult
        except ImportError:
            logger.warning("ExtractorResult not available (extractors module deleted)")
            return None

        semantic = self.extract_semantic_data(
            image_path=str(record.path),
            figure_label=record.path.stem,
            caption=record.caption,
            nearby_text=record.content,
            indicator_hints=self._indicator_hints(record.caption, record.content),
        )
        if not semantic.llm_succeeded:
            logger.warning("route=image_llm_primary image=%s fallback_trigger=%s", record.path.name, semantic.review_status)
            return None
        if semantic.review_status == "non_data_image":
            logger.info("route=image_llm_primary image=%s classification_result=%s", record.path.name, semantic.image_type)
            return ExtractorResult(
                image_type=semantic.image_type,
                points=[],
                extraction_method=semantic.extraction_method or "llm_non_data_visual",
                full_resolution_output=True,
            )
        rows = []
        for index, point in enumerate(semantic.data_points, start=1):
            row = {
                "panel_id": point.get("panel_id") or "plot",
                "series_id": point.get("series_id") or f"series_{index}",
                "series_name": point.get("series_name") or semantic.series_name or f"series_{index}",
                "curve_role": point.get("curve_role") or "",
                "x_value": point.get("x"),
                "x_unit": point.get("x_unit") or semantic.x_axis_unit,
                "x_scale": point.get("x_scale") or semantic.x_axis_scale,
                "x_axis_label": semantic.x_axis_label,
                "y_value": point.get("y"),
                "y_unit": point.get("y_unit") or semantic.y_axis_unit,
                "y_scale": point.get("y_scale") or semantic.y_axis_scale,
                "y_axis_label": semantic.y_axis_label,
                "image_type": semantic.image_type,
                "chart_type": semantic.image_type,
                "selected_extractor": "LLMImageExtractionOrchestrator",
                "extraction_method": semantic.extraction_method or "llm_figure_extraction",
                "axis_calibration_method": "llm_primary",
                "routing_status": "llm_primary",
                "review_status": semantic.review_status,
                "review_notes": semantic.review_notes,
                "indicator": semantic.indicator_bindings[0].indicator_name if semantic.indicator_bindings else "",
                "semantic_value_unit": semantic.value_unit,
                "text_evidence_refs": json.dumps(semantic.text_evidence_refs, ensure_ascii=False),
            }
            rows.append(row)
        logger.info(
            "route=image_llm_primary image=%s classification_result=%s review_status=%s",
            record.path.name,
            semantic.image_type,
            semantic.review_status,
        )
        return ExtractorResult(
            image_type=semantic.image_type,
            points=rows,
            extraction_method=semantic.extraction_method or "llm_figure_extraction",
            full_resolution_output=True,
        ) if rows else None

    def _reclassify_with_context(self, plan: FigureExtractionPlan, indicator_hints: list[str]) -> tuple[ImageType, float, str]:
        image_data_url = self.client.image_data_url(plan.image_path)
        if not image_data_url:
            return ImageType.GENERIC_COORDINATE_PLOT, 0.1, "image_unreadable"
        allowed_types = [image_type.value for image_type in ImageType if image_type != ImageType.UNKNOWN]
        prompt = (
            "Classify this scientific figure into exactly one explicit image type. "
            "Do not answer unknown. If it is ambiguous, choose the closest explicit type.\n"
            f"Allowed types: {', '.join(allowed_types)}\n"
            f"Figure label: {plan.figure_id}\n"
            f"Caption: {_clean_text(plan.caption)}\n"
            f"Nearby text: {_clean_text(plan.review_notes)[:1200]}\n"
            f"Candidate indicators: {', '.join(indicator_hints)}"
        )
        try:
            payload = self.client.chat_json(
                [
                    {"role": "system", "content": "Return JSON with image_type, confidence, reason. Never use unknown."},
                    {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_data_url}}]},
                ],
                phase="image_reclassification",
            )
        except Exception as exc:
            logger.warning("classification_result=retry_failed image=%s error=%s", plan.figure_id, exc)
            return ImageType.UNKNOWN, 0.0, "reclassification_error"
        image_type = image_type_from_string(payload.get("image_type"))
        confidence = float(payload.get("confidence") or 0.35)
        reason = _clean_text(payload.get("reason")) or "reclassified"
        return image_type, confidence, reason

    def _decision_for_type(
        self,
        *,
        image_type: ImageType,
        caption: str,
        nearby_text: str,
        indicator_hints: list[str],
        confidence: float,
    ) -> ImageRoutingDecision:
        explicit_type = image_type if image_type != ImageType.UNKNOWN else self._force_explicit_type(caption, nearby_text)
        route_family = "coordinate"
        if explicit_type in _NON_DATA_TYPES:
            route_family = "non_data"
        elif explicit_type in _TABLE_TYPES:
            route_family = "table"
        elif explicit_type in _BAR_TYPES:
            route_family = "bar"
        elif explicit_type in _HEATMAP_TYPES:
            route_family = "heatmap"
        bindings = self._bind_indicators(caption=caption, nearby_text=nearby_text, indicator_hints=indicator_hints)
        return ImageRoutingDecision(
            image_type=explicit_type.value,
            is_data_bearing=explicit_type not in _NON_DATA_TYPES,
            route_family=route_family,
            has_axes=explicit_type not in _NON_DATA_TYPES and explicit_type not in _TABLE_TYPES,
            has_table_structure=explicit_type in _TABLE_TYPES,
            candidate_indicators=[binding.indicator_name for binding in bindings],
            classification_confidence=confidence,
            binding_candidates=bindings,
        )

    def _bind_indicators(self, *, caption: str, nearby_text: str, indicator_hints: list[str]) -> list[IndicatorBinding]:
        raw_candidates = [*indicator_hints, *_extract_unit_candidates(caption), *_extract_unit_candidates(nearby_text)]
        unique: list[str] = []
        for value in raw_candidates:
            cleaned = _clean_text(value)
            if cleaned and cleaned.lower() not in {item.lower() for item in unique}:
                unique.append(cleaned)
        if not unique:
            fallback = _clean_text(caption)[:80] or "figure_signal"
            unique = [fallback]
        excerpt = _clean_text(nearby_text)[:240]
        caption_excerpt = _clean_text(caption)[:180]
        bindings = []
        for value in unique[:6]:
            units = _extract_unit_candidates(value) or _extract_unit_candidates(caption) or _extract_unit_candidates(nearby_text)
            refs = [text for text in [caption_excerpt, excerpt] if text]
            bindings.append(
                IndicatorBinding(
                    indicator_name=value,
                    indicator_aliases=[value],
                    binding_reason=f"Mapped from MinerU caption/text context for {value}",
                    expected_value_shape="series" if any(token in nearby_text.lower() for token in ["curve", "trend", "rate", "time"]) else "single_value",
                    expected_unit_candidates=units[:3],
                    text_evidence_refs=refs[:2],
                    priority="high",
                )
            )
        return bindings

    def _route_specialist(self, plan: FigureExtractionPlan) -> dict[str, Any]:
        image_type = plan.image_type or ImageType.GENERIC_COORDINATE_PLOT
        if image_type in _BAR_TYPES:
            return self.bar_agent.extract_bars(plan)
        if image_type in _HEATMAP_TYPES:
            return self.heatmap_agent.extract_heatmap(plan)
        if image_type in _TABLE_TYPES:
            return self.table_agent.extract_table_image(plan)
        if image_type in _NON_DATA_TYPES:
            return self.non_data_agent.describe_visual(plan)
        return self.coordinate_agent.extract_coordinates(plan)

    def _review_result(self, result: FigureExtractionResult, bindings: list[IndicatorBinding]) -> tuple[str, str]:
        notes: list[str] = []
        if not result.x_axis.label or not result.y_axis.label:
            notes.append("missing_axis_label")
        if not result.y_axis.unit and self._fallback_value_unit(bindings):
            notes.append("unit_backfilled_from_mineru_text")
        if result.x_axis.scale.startswith("log") and result.x_axis.range_min in {None, 0}:
            notes.append("log_axis_missing_range")
        if not result.data_points:
            notes.append("no_data_points")
        if notes:
            return "review_required", "; ".join(notes)
        return "reviewed", "axis_units_and_points_checked"

    def _points_from_figure_result(self, result: FigureExtractionResult) -> list[dict[str, Any]]:
        points = []
        for index, point in enumerate(result.data_points, start=1):
            points.append(
                {
                    "panel_id": result.figure_label or "plot",
                    "series_id": f"series_{index}",
                    "series_name": point.series_name or (result.series[0] if result.series else f"series_{index}"),
                    "x": point.x_value,
                    "x_unit": point.x_unit or result.x_axis.unit,
                    "x_scale": result.x_axis.scale,
                    "y": point.y_value,
                    "y_unit": point.y_unit or result.y_axis.unit,
                    "y_scale": result.y_axis.scale,
                    "error_bar": point.error_bar,
                }
            )
        return points

    def _points_from_payload(self, payload: dict[str, Any], figure_result: FigureExtractionResult) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        points: list[dict[str, Any]] = []
        for panel in payload.get("panels") or []:
            if not isinstance(panel, dict):
                continue
            for series in panel.get("series") or []:
                if not isinstance(series, dict):
                    continue
                for point in series.get("data_points") or []:
                    if not isinstance(point, dict):
                        continue
                    x_val = point.get("x")
                    y_val = point.get("y")
                    if not isinstance(x_val, (int, float)) or not isinstance(y_val, (int, float)):
                        continue
                    points.append(
                        {
                            "panel_id": panel.get("panel") or figure_result.figure_label or "plot",
                            "series_id": series.get("series_name") or "series",
                            "series_name": series.get("series_name") or "series",
                            "x": float(x_val),
                            "x_unit": figure_result.x_axis.unit,
                            "x_scale": figure_result.x_axis.scale,
                            "y": float(y_val),
                            "y_unit": figure_result.y_axis.unit,
                            "y_scale": figure_result.y_axis.scale,
                            "error_bar": point.get("error_bar") or "",
                        }
                    )
        return points

    def _semantic_axis_label(self, axis_label: str, axis_unit: str, bindings: list[IndicatorBinding], axis_name: str) -> str:
        cleaned = _clean_text(axis_label)
        if cleaned:
            return f"{cleaned} ({axis_unit})" if axis_unit and axis_unit not in cleaned else cleaned
        fallback = bindings[0].indicator_name if bindings else ("x_measure" if axis_name == "x" else "y_measure")
        unit = self._fallback_value_unit(bindings)
        return f"{fallback} ({unit})" if unit else fallback

    def _fallback_value_unit(self, bindings: list[IndicatorBinding]) -> str:
        for binding in bindings:
            for unit in binding.expected_unit_candidates:
                cleaned = _clean_text(unit)
                if cleaned:
                    return cleaned
        return ""

    def _build_value_text(self, value_numeric: float | None, value_unit: str, series: list[str]) -> str:
        if value_numeric is None:
            return "; ".join(series[:2])
        if value_unit:
            return f"{value_numeric:g} {value_unit}"
        return f"{value_numeric:g}"

    def _force_explicit_type(self, caption: str, nearby_text: str) -> ImageType:
        blob = f"{caption} {nearby_text}".lower()
        if any(token in blob for token in ["schematic", "workflow", "mechanism", "diagram", "示意", "流程"]):
            return ImageType.SCHEMATIC
        if any(token in blob for token in ["sem", "tem", "micrograph", "microscopy", "fluorescence", "照片", "显微"]):
            return ImageType.NON_DATA_IMAGE
        if any(token in blob for token in ["table", "row", "column", "表"]):
            return ImageType.TABLE_IMAGE
        return ImageType.GENERIC_COORDINATE_PLOT

    def _indicator_hints(self, caption: str, nearby_text: str) -> list[str]:
        return [value for value in _extract_indicator_phrases(caption) + _extract_indicator_phrases(nearby_text) if value]

    @staticmethod
    def _chart_type_to_image_type(chart_type: str) -> ImageType:
        mapping = {
            "line_plot": ImageType.LINE_PLOT,
            "bar_chart": ImageType.BAR_CHART,
            "scatter_plot": ImageType.SCATTER_PLOT,
            "rheology_flow_curve": ImageType.RHEOLOGY_FLOW_CURVE,
            "rheology_strain_sweep": ImageType.RHEOLOGY_STRAIN_SWEEP,
            "heatmap": ImageType.HEATMAP,
            "spectrum": ImageType.SPECTRUM_CURVE,
            "microscopy": ImageType.NON_DATA_IMAGE,
            "schematic": ImageType.SCHEMATIC,
            "other": ImageType.GENERIC_COORDINATE_PLOT,
            "error": ImageType.UNKNOWN,
        }
        return mapping.get(chart_type, ImageType.GENERIC_COORDINATE_PLOT)


def _extract_unit_candidates(text: str) -> list[str]:
    matches = re.findall(r"\(([^()]{1,20})\)", text or "")
    return [match.strip() for match in matches if any(ch.isalpha() or ch in "°%µμ·/^-" for ch in match)]


def _extract_indicator_phrases(text: str) -> list[str]:
    clean = _clean_text(text)
    if not clean:
        return []
    phrases = re.findall(r"[A-Za-z][A-Za-z0-9\-/'% ]{2,40}", clean)
    return [phrase.strip(" ,.;:") for phrase in phrases[:12] if len(phrase.strip()) >= 3]
