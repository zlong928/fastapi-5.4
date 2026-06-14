from __future__ import annotations

import json
import re

from app.models import DocumentAsset, ExtractionResult


CONFIDENCE_MAP = {"high": 0.85, "medium": 0.65, "low": 0.4, "none": 0.15}

NEGATIVE_RESULT_MARKERS = (
    "没有任何",
    "没有可",
    "不包含可",
    "无法提取",
    "不能提取",
    "不可读取",
    "无法读取",
    "没有坐标轴",
    "没有可见比例尺",
    "没有可直接读取",
    "不存在可",
    "无可提取",
    "not contain",
    "no extractable",
    "no visible",
)

GENERIC_METRIC_NAMES = {
    "comprehensive_data_extraction",
    "visible_evidence",
    "figure_data",
    "key_metrics",
    "materials_methods",
    "materials",
    "experiment_groups",
    "conclusion",
    "objective",
}


class AgentResultMapper:
    def map_results(self, *, job_id: int, final_results: dict, figures: list[DocumentAsset], tables: list[DocumentAsset]) -> list[ExtractionResult]:
        rows: list[ExtractionResult] = []
        figure_ids = self._figure_ids(figures)
        figure_captions = self._figure_captions(figures)
        table_assets = {table.id: table for table in tables}

        for item in final_results.get("text_only_data", []) or []:
            metric = self._field_name(item)
            value = self._stringify(item.get("value", ""))
            evidence = self._stringify(item.get("evidence", ""))
            if not self._valid_text_result(value, evidence):
                continue
            is_fallback = str(item.get("mode", "")).startswith("fallback")
            source_type, source_id = self._detect_table_source(metric, value, evidence, tables)
            confidence = 0.2 if is_fallback else (0.7 if value else 0.3)
            extraction_mode = "fallback_caption_only" if is_fallback else "text_extraction"

            structured_data = None
            parse_status = None
            if source_type == "asset" and source_id and source_id in table_assets:
                table_asset = table_assets[source_id]
                structured_data = self._table_structured_data(table_asset)
                parse_status = "success" if structured_data else "partial"

            rows.append(ExtractionResult(
                job_id=job_id,
                source_type=source_type,
                source_id=source_id,
                field_name=metric,
                content=value or "未在当前论文解析内容中找到明确证据",
                evidence=evidence or ("无原文证据（fallback模式）" if is_fallback else ""),
                confidence=confidence,
                extraction_mode=extraction_mode,
                structured_data=structured_data,
                parse_status=parse_status,
            ))

        for figure_id, payload in (final_results.get("by_figure", {}) or {}).items():
            figure_db_id = figure_ids.get(str(figure_id))
            figure_caption = figure_captions.get(str(figure_id), "")
            overall_desc = self._stringify(payload.get("overall_description", ""))
            is_fallback = str(payload.get("mode", "")).startswith("fallback")

            # 提取 chart_data（新增）
            chart_data = payload.get("chart_data") or payload.get("coordinate_data")
            chart_type = chart_data.get("chart_type", "") if isinstance(chart_data, dict) else ""

            for extraction in payload.get("extractions", []) or []:
                content = self._stringify(extraction.get("qualitative") or extraction.get("data") or "")
                notes = str(extraction.get("notes") or "") or None
                evidence = self._stringify(extraction.get("evidence") or overall_desc or figure_caption)
                if not self._valid_visual_result(extraction, content, evidence, notes):
                    continue

                extraction_is_fallback = is_fallback or str(extraction.get("mode", "")).startswith("fallback")
                if extraction_is_fallback:
                    confidence = 0.15
                    extraction_mode = "fallback_caption_only"
                else:
                    confidence = CONFIDENCE_MAP.get(str(extraction.get("confidence", "medium")).lower(), 0.65)
                    # 根据图表类型设置 extraction_mode
                    extraction_mode = self._map_extraction_mode(extraction, chart_type, payload)
                if confidence < 0.5:
                    continue

                # 优先使用 chart_data，回退到 extraction.data
                structured_data = None
                raw_data = chart_data if chart_data else extraction.get("data")
                if raw_data and isinstance(raw_data, dict) and raw_data:
                    structured_data = json.dumps(raw_data, ensure_ascii=False)

                rows.append(
                    ExtractionResult(
                        job_id=job_id,
                        source_type="asset",
                        source_id=figure_db_id,
                        field_name=self._visual_field_name(extraction, payload),
                        content=content or "未在当前图片解析内容中找到明确证据",
                        evidence=evidence or ("无原文证据（fallback模式）" if extraction_is_fallback else str(figure_id)),
                        confidence=confidence,
                        figure_id=str(figure_id),
                        caption=figure_caption or None,
                        notes=notes,
                        structured_data=structured_data,
                        parse_status="success" if content and not extraction_is_fallback else "partial" if content else "failed",
                        extraction_mode=extraction_mode,
                    )
                )

        existing_fields = {(row.source_type, row.field_name) for row in rows}
        for metric in final_results.get("not_found_metrics", []) or []:
            if ("text", metric) in existing_fields:
                continue
            rows.append(
                ExtractionResult(
                    job_id=job_id,
                    source_type="text",
                    source_id=None,
                    field_name=str(metric),
                    content="未在当前论文解析内容中找到明确证据",
                    evidence="",
                    confidence=0.1,
                    parse_status="failed",
                    notes="该指标在论文全文、图片和表格中均未找到可靠证据",
                    extraction_mode="not_found",
                )
            )
        return rows

    def _field_name(self, item: dict) -> str:
        field = str(item.get("field") or item.get("field_name") or "").strip()
        metric = str(item.get("metric") or "unknown").strip()
        if field and field.lower() not in GENERIC_METRIC_NAMES:
            return self._normalize_field(field)
        value = self._stringify(item.get("value", ""))
        return self._derive_field_from_text(metric, value)

    def _visual_field_name(self, extraction: dict, payload: dict) -> str:
        field = str(extraction.get("field") or extraction.get("field_name") or "").strip()
        metric = str(extraction.get("metric") or "unknown").strip()
        if field and field.lower() not in GENERIC_METRIC_NAMES:
            return self._normalize_field(field)
        if metric and metric.lower() not in GENERIC_METRIC_NAMES:
            return self._normalize_field(metric)
        content = self._stringify(extraction.get("qualitative") or extraction.get("data") or "")
        figure_type = self._stringify(payload.get("figure_type") or "")
        derived = self._derive_field_from_text("visual_evidence", content or figure_type)
        return derived if derived != "visual_evidence" else "可见图像证据"

    def _derive_field_from_text(self, metric: str, value: str) -> str:
        compact = " ".join((value or "").split())
        if not compact:
            return self._normalize_field(metric)
        if "hydrogel" in compact.lower() and ("10–40" in compact or "10-40" in compact or "直径" in compact):
            return "水凝胶微腔直径"
        if "Clostridium" in compact or "Shewanella" in compact:
            return "菌株组成"
        if "hexanoic" in compact.lower() or "己酸" in compact:
            return "己酸产量"
        if "OmpF" in compact or "AI-2" in compact:
            return "OmpF/AI-2结构信息"
        if "SEM" in compact or "显微" in compact or "杆状" in compact:
            return "显微结构观察"
        return self._normalize_field(metric)

    def _normalize_field(self, value: str) -> str:
        return re.sub(r"\s+", "_", value.strip())[:80] or "unknown"

    def _valid_text_result(self, value: str, evidence: str) -> bool:
        if not value.strip() or self._is_negative_result(value):
            return False
        if not evidence.strip() or self._is_negative_result(evidence):
            return False
        return True

    def _valid_visual_result(self, extraction: dict, content: str, evidence: str, notes: str | None) -> bool:
        if str(extraction.get("success", True)).lower() in {"false", "0", "no"}:
            return False
        if not content.strip():
            return False
        if self._is_negative_result(content) or self._is_negative_result(notes or ""):
            return False
        if not evidence.strip() or self._is_negative_result(evidence):
            return False
        data = extraction.get("data")
        has_data = isinstance(data, dict) and bool(data)
        has_positive_visual_words = any(
            marker in content
            for marker in ("显示", "可见", "标注", "位于", "呈现", "结构", "数值", "趋势", "柱", "曲线", "OmpF", "AI-2")
        )
        return has_data or has_positive_visual_words

    def _is_negative_result(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker.lower() in lowered for marker in NEGATIVE_RESULT_MARKERS)

    def _figure_ids(self, figures: list[DocumentAsset]) -> dict[str, int]:
        out: dict[str, int] = {}
        for figure in figures:
            label = f"Figure {figure.id}"
            if figure.metadata_json:
                try:
                    label = str(json.loads(figure.metadata_json).get("figure_label") or label)
                except Exception:
                    pass
            out[f"{label} [asset:{figure.id}]"] = figure.id
            out[label] = figure.id
            out[str(figure.id)] = figure.id
        return out

    def _figure_captions(self, figures: list[DocumentAsset]) -> dict[str, str]:
        out: dict[str, str] = {}
        for figure in figures:
            label = f"Figure {figure.id}"
            caption = ""
            if figure.metadata_json:
                try:
                    metadata = json.loads(figure.metadata_json)
                    label = str(metadata.get("figure_label") or label)
                    caption = str(metadata.get("caption") or "")
                except Exception:
                    pass
            out[f"{label} [asset:{figure.id}]"] = caption
            out[label] = caption
        return out

    def _table_structured_data(self, table: DocumentAsset) -> str | None:
        markdown = table.markdown or table.text_content or ""
        if not markdown.strip():
            return None
        rows = []
        for line in markdown.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
                continue
            rows.append(cells)
        if len(rows) < 2:
            return None
        return json.dumps(rows, ensure_ascii=False)

    def _detect_table_source(self, metric: str, value: str, evidence: str, tables: list[DocumentAsset]) -> tuple[str, int | None]:
        for table in tables:
            content = table.markdown or table.text_content or table.ocr_text or ""
            for candidate in (evidence, value):
                snippet = self._long_snippet(candidate)
                if snippet and snippet in content:
                    return "asset", table.id
            if metric and metric.lower() in content.lower():
                return "asset", table.id
        return "text", None

    def _long_snippet(self, text: str) -> str:
        compact = " ".join((text or "").split())
        return compact[:20] if len(compact) >= 20 else ""

    def _stringify(self, value) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _map_extraction_mode(self, extraction: dict, chart_type: str, payload: dict) -> str:
        """根据图表类型和提取模式映射 extraction_mode"""
        mode = str(extraction.get("mode", ""))

        # 优先使用 extraction 中的 mode
        if "coordinate_extraction" in mode:
            return "chart_coordinate_extraction"
        elif "bar_chart" in mode:
            return "chart_bar_extraction"
        elif "heatmap" in mode:
            return "chart_heatmap_extraction"
        elif "table_image" in mode:
            return "chart_table_extraction"
        elif "visual_descriptive" in mode or "non_data" in mode:
            return "visual_descriptive"

        # 根据 chart_type 推断
        if chart_type in (
            "line_plot",
            "biphasic_time_series",
            "multi_line_plot",
            "scatter_plot",
            "spectrum_curve",
            "bar_or_line_with_errorbar",
            "generic_coordinate_plot",
            "dual_axis_plot",
        ):
            return "chart_coordinate_extraction"
        elif chart_type in ("bar_chart", "grouped_bar"):
            return "chart_bar_extraction"
        elif chart_type in ("heatmap", "heatmap_matrix", "2d_field_map"):
            return "chart_heatmap_extraction"
        elif chart_type == "table_image":
            return "chart_table_extraction"
        elif chart_type in ("non_data_image", "microscopy_quant", "schematic", "schematic_or_photo"):
            return "visual_descriptive"

        # 默认使用通用视觉分析
        return "visual_analysis"
