from __future__ import annotations

import json
import re

from app.models import DocumentAsset, ExtractionResult


CONFIDENCE_MAP = {"high": 0.85, "medium": 0.65, "low": 0.4, "none": 0.15}


class AgentResultMapper:
    def map_results(self, *, job_id: int, final_results: dict, figures: list[DocumentAsset], tables: list[DocumentAsset]) -> list[ExtractionResult]:
        rows: list[ExtractionResult] = []
        figure_ids = self._figure_ids(figures)
        figure_captions = self._figure_captions(figures)
        table_assets = {table.id: table for table in tables}

        for item in final_results.get("text_only_data", []) or []:
            metric = str(item.get("metric") or "unknown")
            value = self._stringify(item.get("value", ""))
            evidence = self._stringify(item.get("evidence", ""))
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
            extraction_mode = "fallback_caption_only" if is_fallback else "visual_analysis"

            for extraction in payload.get("extractions", []) or []:
                extraction_is_fallback = is_fallback or str(extraction.get("mode", "")).startswith("fallback")
                if extraction_is_fallback:
                    confidence = 0.15
                    extraction_mode = "fallback_caption_only"
                else:
                    confidence = CONFIDENCE_MAP.get(str(extraction.get("confidence", "medium")).lower(), 0.65)
                    extraction_mode = "visual_analysis"

                content = self._stringify(extraction.get("qualitative") or extraction.get("data") or "")
                notes = str(extraction.get("notes") or "") or None
                evidence = overall_desc or figure_caption

                structured_data = None
                raw_data = extraction.get("data")
                if raw_data and isinstance(raw_data, dict) and raw_data:
                    structured_data = json.dumps(raw_data, ensure_ascii=False)

                rows.append(
                    ExtractionResult(
                        job_id=job_id,
                        source_type="asset",
                        source_id=figure_db_id,
                        field_name=str(extraction.get("metric") or "unknown"),
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
