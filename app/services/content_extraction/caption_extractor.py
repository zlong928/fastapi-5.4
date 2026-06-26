from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from app.services.content_extraction.models import PropertyRecord
from app.services.content_extraction.prompts import CAPTION_EXTRACTION_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.extraction.classification_pipeline_v2 import IndicatorMapping
    from app.services.markdown_ref_builder import MarkdownDocument

logger = logging.getLogger(__name__)


class CaptionExtractor:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        user_query: str,
    ) -> list[PropertyRecord]:
        image_map = mrf_doc.images_by_label()
        tasks: list[dict] = []
        for mapping in mappings:
            if not mapping.figures:
                continue
            for fig_label in mapping.figures:
                img_ref = image_map.get(fig_label)
                if not img_ref or not img_ref.caption:
                    continue
                tasks.append({
                    "mapping": mapping,
                    "fig_label": fig_label,
                    "img_ref": img_ref,
                })

        if not tasks:
            return []

        records: list[PropertyRecord] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_task = {
                executor.submit(self._extract_single, task, user_query): task
                for task in tasks
            }
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                    if result:
                        records.extend(result)
                except Exception as e:
                    logger.warning(
                        "Caption extraction failed for %s: %s",
                        task["fig_label"], e
                    )
        return records

    def _extract_single(
        self, task: dict, user_query: str
    ) -> list[PropertyRecord]:
        img_ref = task["img_ref"]
        messages = [
            {"role": "system", "content": CAPTION_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    user_query, task["mapping"], img_ref
                ),
            },
        ]
        try:
            result = self.client.chat_json(messages, phase="content_caption_extraction")
            return self._parse_records(result, task["mapping"], task["fig_label"])
        except Exception as exc:
            logger.warning("LLM caption extraction failed: %s", exc)
            return []

    def _build_user_prompt(
        self,
        user_query: str,
        mapping: IndicatorMapping,
        img_ref: object,
    ) -> str:
        from app.services.markdown_ref_builder import MarkdownImageRef
        img = img_ref
        parts = [
            "# 用户的原始提取需求",
            user_query,
            "",
            "# 当前要提取的内容",
            mapping.indicator,
            "",
            "# 提取提示",
            mapping.extraction_hint or "从下面的图表标题中提取相关的属性-值记录。",
            "",
            "# 图表信息",
            f"Label: {img.label or '(unnamed)'}",
            f"Caption: {img.caption}",
            f"Section: {img.section_heading}",
            f"Context before: {img.context_before[:200]}",
            f"Context after: {img.context_after[:200]}",
            "",
            "# 任务",
            f"根据用户需求，从以上图表标题中提取「{mapping.indicator}」相关的结构化属性-值记录。返回JSON格式。",
        ]
        return "\n".join(parts)

    def _parse_records(
        self, result: dict, mapping: IndicatorMapping, fig_label: str
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for raw in result.get("records") or []:
            if not isinstance(raw, dict):
                continue
            records.append(PropertyRecord(
                entity=str(raw.get("entity") or mapping.indicator),
                property_name=str(raw.get("property_name") or ""),
                property_category=str(raw.get("property_category") or ""),
                value_text=str(raw.get("value_text") or ""),
                value_numeric=_safe_float(raw.get("value_numeric")),
                value_unit=str(raw.get("value_unit") or None) or None,
                condition=str(raw.get("condition") or ""),
                method=str(raw.get("method") or ""),
                confidence=float(raw.get("confidence") or 0.5),
                source_type="caption",
                source_ref=fig_label,
                evidence_excerpt=str(raw.get("evidence_excerpt") or ""),
                extraction_method="caption_llm",
            ))
        return records


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
