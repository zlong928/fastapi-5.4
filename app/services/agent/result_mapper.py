from __future__ import annotations

import json

from app.models import DocumentAsset, ExtractionResult


CONFIDENCE_MAP = {"high": 0.85, "medium": 0.65, "low": 0.4}


class AgentResultMapper:
    def map_results(self, *, job_id: int, final_results: dict, figures: list[DocumentAsset], tables: list[DocumentAsset]) -> list[ExtractionResult]:
        rows: list[ExtractionResult] = []
        figure_ids = self._figure_ids(figures)

        for item in final_results.get("text_only_data", []) or []:
            metric = str(item.get("metric") or "unknown")
            value = self._stringify(item.get("value", ""))
            evidence = self._stringify(item.get("evidence", ""))
            source_type, source_id = self._detect_table_source(metric, value, evidence, tables)
            rows.append(ExtractionResult(job_id=job_id, source_type=source_type, source_id=source_id, field_name=metric, content=value or "未在当前论文解析内容中找到明确证据", evidence=evidence, confidence=0.7 if value else 0.3))

        for figure_id, payload in (final_results.get("by_figure", {}) or {}).items():
            figure_db_id = figure_ids.get(str(figure_id))
            evidence = " ".join(part for part in [str(figure_id), self._stringify(payload.get("overall_description", ""))] if part)
            for extraction in payload.get("extractions", []) or []:
                confidence = CONFIDENCE_MAP.get(str(extraction.get("confidence", "medium")).lower(), 0.65)
                content = self._stringify(extraction.get("qualitative") or extraction.get("data") or "")
                rows.append(
                    ExtractionResult(
                        job_id=job_id,
                        source_type="asset",
                        source_id=figure_db_id,
                        field_name=str(extraction.get("metric") or "unknown"),
                        content=content or "未在当前图片解析内容中找到明确证据",
                        evidence=evidence,
                        confidence=confidence,
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
                    confidence=0.3,
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
