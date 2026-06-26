from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from app.services.content_extraction.models import PropertyRecord
from app.services.content_extraction.prompts import SECTION_EXTRACTION_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.extraction.classification_pipeline_v2 import IndicatorMapping
    from app.services.markdown_ref_builder import MarkdownDocument

logger = logging.getLogger(__name__)

MAX_SECTION_CHARS = 4000


class SectionExtractor:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        user_query: str,
    ) -> list[PropertyRecord]:
        tasks: list[dict] = []
        for mapping in mappings:
            if not mapping.sections:
                continue
            for section_title in mapping.sections:
                section_text = mrf_doc.text_by_section(section_title)
                if not section_text:
                    continue
                tasks.append({
                    "mapping": mapping,
                    "section_title": section_title,
                    "section_text": section_text[:MAX_SECTION_CHARS],
                    "section_text_for_evidence": section_text[:MAX_SECTION_CHARS],
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
                        "Section extraction failed for %s: %s",
                        task["section_title"], e
                    )
        return records

    def _extract_single(
        self, task: dict, user_query: str
    ) -> list[PropertyRecord]:
        messages = [
            {"role": "system", "content": SECTION_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    user_query, task["mapping"], task["section_text"]
                ),
            },
        ]
        try:
            result = self.client.chat_json(messages, phase="content_section_extraction")
            return self._parse_records(
                result,
                task["mapping"],
                task["section_title"],
                task["section_text_for_evidence"],
            )
        except Exception as exc:
            logger.warning("LLM section extraction failed: %s", exc)
            return []

    def _build_user_prompt(
        self, user_query: str, mapping: IndicatorMapping, section_text: str
    ) -> str:
        parts = [
            "# 用户的原始提取需求",
            user_query,
            "",
            "# 当前要提取的内容",
            mapping.indicator,
            "",
            "# 提取提示",
            mapping.extraction_hint or "从下面的文本中提取相关的属性-值记录。",
            "",
            "# 段落内容",
            section_text,
            "",
            "# 任务",
            f"根据用户需求，从以上文本中提取「{mapping.indicator}」相关的结构化属性-值记录。返回JSON格式。",
            "",
            "# 输出约束（必须满足）",
            "1. 必须返回JSON对象，含records数组。",
            "2. 每条record必须包含 evidence_excerpt 字段，且为输入段落中的原文片段（尽量>=20字）。",
            "3. 当无法从原文给出可靠证据引用时，不要编造evidence_excerpt。",
        ]
        return "\n".join(parts)

    def _parse_records(
        self,
        result: dict,
        mapping: IndicatorMapping,
        section_title: str,
        section_text: str,
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for raw in result.get("records") or []:
            if not isinstance(raw, dict):
                continue
            evidence_excerpt = str(raw.get("evidence_excerpt") or "").strip()
            if not evidence_excerpt:
                evidence_excerpt = self._build_fallback_evidence_excerpt(
                    section_text=section_text,
                    section_title=section_title,
                    mapping=mapping,
                    property_name=str(raw.get("property_name") or ""),
                    value_text=str(raw.get("value_text") or ""),
                )
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
                source_type="section",
                source_ref=section_title,
                evidence_excerpt=evidence_excerpt,
                extraction_method="section_llm",
            ))
        return records

    def _build_fallback_evidence_excerpt(
        self,
        section_text: str,
        section_title: str,
        mapping: IndicatorMapping,
        property_name: str,
        value_text: str,
    ) -> str:
        normalized_section = section_text or ""
        haystack = normalized_section.lower()
        candidates = [
            value_text,
            property_name,
            mapping.indicator,
            mapping.extraction_hint or "",
            section_title,
        ]
        for token in candidates:
            token = str(token or "").strip()
            if not token:
                continue
            idx = haystack.find(token.lower())
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(normalized_section), idx + len(token) + 60)
                return normalized_section[start:end].strip()

        if normalized_section:
            return normalized_section[:180].strip()
        return ""


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
