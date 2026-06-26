from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from app.services.content_extraction.models import PropertyRecord
from app.services.content_extraction.prompts import TABLE_EXTRACTION_SYSTEM_PROMPT

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.extraction.classification_pipeline_v2 import IndicatorMapping
    from app.services.markdown_ref_builder import MarkdownDocument, MarkdownTable

logger = logging.getLogger(__name__)


class TableExtractor:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        mrf_doc: MarkdownDocument,
        mappings: list[IndicatorMapping],
        user_query: str,
    ) -> list[PropertyRecord]:
        table_map = mrf_doc.tables_by_label()
        tasks: list[dict] = []
        for mapping in mappings:
            if not mapping.tables:
                continue
            for table_label in mapping.tables:
                table = table_map.get(table_label)
                if not table:
                    continue
                tasks.append({
                    "mapping": mapping,
                    "table": table,
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
                        "Table extraction failed for %s: %s",
                        task["table"].label, e
                    )
        return records

    def _extract_single(
        self, task: dict, user_query: str
    ) -> list[PropertyRecord]:
        table: MarkdownTable = task["table"]
        table_md = self._table_to_markdown(table)

        messages = [
            {"role": "system", "content": TABLE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    user_query, task["mapping"], table_md, table
                ),
            },
        ]
        try:
            result = self.client.chat_json(messages, phase="content_table_extraction")
            records = self._parse_records(result, task["mapping"], table)
            if records:
                return records
        except Exception as exc:
            logger.warning("LLM table extraction failed, trying structured fallback: %s", exc)

        return self._fallback_parse(table, task["mapping"])

    def _table_to_markdown(self, table: MarkdownTable) -> str:
        lines: list[str] = []
        header = "| " + " | ".join(table.headers) + " |"
        lines.append(header)
        separator = "| " + " | ".join("---" for _ in table.headers) + " |"
        lines.append(separator)
        for row in table.rows:
            padded = row + [""] * max(0, len(table.headers) - len(row))
            lines.append("| " + " | ".join(padded[:len(table.headers)]) + " |")
        return "\n".join(lines)

    def _build_user_prompt(
        self,
        user_query: str,
        mapping: IndicatorMapping,
        table_md: str,
        table: MarkdownTable,
    ) -> str:
        parts = [
            "# 用户的原始提取需求",
            user_query,
            "",
            "# 当前要提取的内容",
            mapping.indicator,
            "",
            "# 提取提示",
            mapping.extraction_hint or "从下面的表格中提取相关的属性-值记录。注意理解表格结构。",
            "",
            "# 表格",
            f"Table: {table.label or '(unnamed)'}",
            f"Caption: {table.caption or ''}",
            "",
            table_md,
            "",
            "# 任务",
            f"根据用户需求，从以上表格中提取「{mapping.indicator}」相关的结构化属性-值记录。返回JSON格式。",
        ]
        return "\n".join(parts)

    def _parse_records(
        self, result: dict, mapping: IndicatorMapping, table: MarkdownTable
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
                source_type="table",
                source_ref=table.label or "(table)",
                evidence_excerpt=str(raw.get("evidence_excerpt") or ""),
                extraction_method="table_llm",
            ))
        return records

    def _fallback_parse(
        self, table: MarkdownTable, mapping: IndicatorMapping
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        headers = table.headers
        if not headers:
            return records

        is_transposed = self._detect_transposed(table)
        if is_transposed:
            records = self._parse_transposed(table, mapping, headers)
        else:
            records = self._parse_standard(table, mapping, headers)
        return records

    def _detect_transposed(self, table: MarkdownTable) -> bool:
        if not table.rows:
            return False
        first_col_values = [
            row[0].strip().lower() if row else "" for row in table.rows
        ]
        property_keywords = {"viscosity", "modulus", "temperature", "concentration", "time", "value", "parameter", "property"}
        match_count = sum(
            1 for val in first_col_values
            if any(kw in val for kw in property_keywords)
        )
        return match_count >= len(table.rows) * 0.5 and len(table.rows) > 1

    def _parse_standard(
        self, table: MarkdownTable, mapping: IndicatorMapping, headers: list[str]
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for row in table.rows:
            if not row:
                continue
            entity = row[0] if len(row) > 0 else ""
            for col_idx in range(1, min(len(row), len(headers))):
                cell_value = row[col_idx].strip()
                if not cell_value or cell_value in ("-", "—", "N/A", "n/a"):
                    continue
                prop_name = headers[col_idx] if col_idx < len(headers) else f"Column {col_idx}"
                records.append(PropertyRecord(
                    entity=entity or mapping.indicator,
                    property_name=prop_name,
                    property_category="",
                    value_text=cell_value,
                    confidence=0.6,
                    source_type="table",
                    source_ref=table.label or "(table)",
                    evidence_excerpt=f"{entity} | {prop_name} | {cell_value}",
                    extraction_method="table_fallback",
                ))
        return records

    def _parse_transposed(
        self, table: MarkdownTable, mapping: IndicatorMapping, headers: list[str]
    ) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        for col_idx in range(1, min(len(headers), len(table.rows[0]) if table.rows else 1)):
            entity = headers[col_idx] if col_idx < len(headers) else f"Column {col_idx}"
            for row in table.rows:
                if not row or not row[0].strip():
                    continue
                prop_name = row[0].strip()
                cell_value = row[col_idx].strip() if col_idx < len(row) else ""
                if not cell_value or cell_value in ("-", "—", "N/A", "n/a"):
                    continue
                records.append(PropertyRecord(
                    entity=entity or mapping.indicator,
                    property_name=prop_name,
                    property_category="",
                    value_text=cell_value,
                    confidence=0.6,
                    source_type="table",
                    source_ref=table.label or "(table)",
                    evidence_excerpt=f"{entity} | {prop_name} | {cell_value}",
                    extraction_method="table_fallback",
                ))
        return records


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
