"""New Classification Pipeline with user-query-first prompt design.

Replaces the old hardcoded system prompt with a flexible, user-centric approach.
The user's query is the core instruction; the system prompt only defines tool capabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.markdown_ref_builder import MarkdownDocument


@dataclass
class IndicatorMapping:
    """One indicator mapped to its source references."""

    indicator: str
    indicator_keywords: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    extraction_hint: str = ""
    priority: str = "high"


# ✅ 新设计：系统提示词只定义"工具能力"，不预设"如何提取"
CLASSIFICATION_SYSTEM_PROMPT = """你是一个智能数据提取路由器。

## 你的能力
- 分析Markdown格式的科学论文结构
- 识别论文中的图表(figures)、章节(sections)、表格(tables)
- 根据用户需求，将提取任务映射到具体的数据源位置

## 输出格式
返回JSON对象，包含一个mappings数组：
```json
{
  "mappings": [
    {
      "indicator": "<用户要提取的内容，保持原始表达>",
      "indicator_keywords": ["<相关的搜索关键词>"],
      "figures": ["Figure 1", "Figure 3"],
      "sections": ["Results", "Discussion"],
      "tables": ["Table 2"],
      "extraction_hint": "<给后续提取器的建议：如何从这些源中提取数据>",
      "priority": "high|medium|low"
    }
  ]
}
```

## 工作原则
1. **严格遵循用户的原始表达**：用户怎么说，你就怎么理解
   - 如果用户说"提取零剪切粘度和误差"，就要同时找数值和误差
   - 如果用户说"快速提取关键数据"，就只找最明显的
   - 如果用户说"详细分析所有流变学性能"，就要全面覆盖

2. **保持灵活**：用户可能用自然语言描述，也可能列举具体名词，都要支持

3. **不要过度解释**：用户说什么就是什么，不要自作主张添加或删除内容

4. **Be inclusive**：当不确定某个图表是否相关时，宁可包含进去（标记为low priority）

## Priority 说明
- high: 明确包含相关数据的图表/章节（如数据图表、性能曲线）
- medium: 可能包含相关信息（如综合图、对比图）
- low: 仅供参考（如示意图、结构图、显微镜照片）

## 重要
- 对于figures，使用论文中的原始标签（如"Figure 1", "Fig. 2a"）
- 对于sections，使用原始章节标题
- 如果找不到任何数据源，仍然包含该indicator，但各列表为空
"""


class ClassificationPipeline:
    """Map user requests to source locations in the paper."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(
        self,
        doc: MarkdownDocument,
        user_query: str,
    ) -> list[IndicatorMapping]:
        """Map user's extraction request to figures/sections/tables.

        Args:
            doc: Structured Markdown document from MRFBuilder.
            user_query: User's complete, unmodified extraction request.

        Returns:
            A list of ``IndicatorMapping``.
        """
        if not user_query or not user_query.strip():
            return []

        doc_summary = doc.to_dict()
        prompt = self._build_user_prompt(doc_summary, user_query)

        messages = [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        result = self.client.chat_json(messages, phase="classification")

        return self._parse_result(result, user_query)

    def _build_user_prompt(self, doc_summary: dict, user_query: str) -> str:
        """Build user message with user_query as the primary content."""
        parts = [
            "# 用户的提取需求（这是核心任务，严格遵循）",
            user_query,
            "",
            "# 论文结构信息",
            json.dumps(doc_summary, ensure_ascii=False, indent=2),
            "",
            "# 你的任务",
            "根据用户的需求，分析论文结构，找到每个要提取的内容对应的数据源位置。",
            "返回valid JSON格式的mappings，确保每个mapping的indicator字段保持用户的原始表达。",
        ]
        return "\n".join(parts)

    def _parse_result(
        self, result: dict, user_query: str
    ) -> list[IndicatorMapping]:
        raw_mappings = result.get("mappings") or []
        if not isinstance(raw_mappings, list):
            raw_mappings = []

        mappings: list[IndicatorMapping] = []
        seen_indicators: set[str] = set()

        for raw in raw_mappings:
            if not isinstance(raw, dict):
                continue
            indicator = str(raw.get("indicator") or "").strip()
            if not indicator:
                continue
            if indicator in seen_indicators:
                continue
            seen_indicators.add(indicator)

            mappings.append(
                IndicatorMapping(
                    indicator=indicator,
                    indicator_keywords=self._parse_keywords(raw.get("indicator_keywords")),
                    figures=self._parse_string_list(raw.get("figures")),
                    sections=self._parse_string_list(raw.get("sections")),
                    tables=self._parse_string_list(raw.get("tables")),
                    extraction_hint=str(raw.get("extraction_hint") or ""),
                    priority=str(raw.get("priority") or "high"),
                )
            )

        return mappings

    def _parse_keywords(self, value: any) -> list[str]:
        if isinstance(value, list):
            return [str(k).strip() for k in value if str(k).strip()]
        return []

    def _parse_string_list(self, value: any) -> list[str]:
        if isinstance(value, list):
            return [str(s).strip() for s in value if str(s).strip()]
        return []
