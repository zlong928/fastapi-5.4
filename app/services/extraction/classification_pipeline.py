"""ClassificationPipeline: LLM reads indicator list, maps indicators to figures/sections.

Given a user query (list of indicators to extract) and the structured Markdown
document (from MRFBuilder), the LLM produces a mapping:

    indicator → which figures contain relevant data
    indicator → which text sections discuss this indicator
    indicator → which tables contain relevant values

This mapping drives the routing decisions for downstream extraction pipelines.
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

    indicator: str  # e.g., "零剪切粘度"
    indicator_keywords: list[str] = field(default_factory=list)  # search keywords
    figures: list[str] = field(default_factory=list)  # ["Figure 1", "Figure 3"]
    sections: list[str] = field(default_factory=list)  # ["Results", "Discussion"]
    tables: list[str] = field(default_factory=list)  # ["Table 2"]
    extraction_hint: str = ""  # LLM's advice for the extractor
    priority: str = "high"  # high | medium | low


CLASSIFICATION_SYSTEM_PROMPT = """You are a scientific paper analysis expert. Your task is to map a list of
indicators (things to extract from a paper) to the specific figures, sections,
and tables where they can be found.

## Input
You will receive:
1. A JSON summary of the paper's structure (sections, figures with captions, tables)
2. A list of indicators to find

## Output
Return a JSON object with a single key "mappings" containing a list of objects:
```json
{
  "mappings": [
    {
      "indicator": "<name of the indicator>",
      "indicator_keywords": ["<keyword1>", "<keyword2>"],
      "figures": ["Figure 1", "Figure 3"],
      "sections": ["Results and Discussion"],
      "tables": ["Table 2"],
      "extraction_hint": "<how to extract this from the figures: e.g., 'read y-axis viscosity values vs x-axis shear rate from log-log plot'>",
      "priority": "high|medium|low"
    }
  ]
}
```

## Rules
1. For each indicator, list ALL figures that MIGHT contain relevant data. Be inclusive.
2. For figures, use the exact figure label as it appears in the paper (e.g., "Figure 1", "Fig. 2a").
3. For sections, use the exact heading text.
4. If you cannot find any source for an indicator, still include it with empty lists.
5. The extraction_hint should describe what to look for in the figure: axis labels,
   curve features, data ranges, units, etc.
6. Priority: "high" = clearly visible data chart, "medium" = might have some data,
   "low" = only schematic/micrograph, no numerical data expected.
7. Consider ALL types of figures: line plots, bar charts, scatter plots,
   heatmaps, flow curves, strain sweeps, microscopy images, schematics.
"""


class ClassificationPipeline:
    """Map indicators to their source locations in the paper."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def classify(
        self,
        doc: MarkdownDocument,
        indicators: list[str],
    ) -> list[IndicatorMapping]:
        """Map each indicator to the figures/sections/tables that contain it.

        Args:
            doc: Structured Markdown document from MRFBuilder.
            indicators: List of indicator names to find (from user query).

        Returns:
            A list of ``IndicatorMapping``, one per indicator.
        """
        if not indicators:
            return []

        doc_summary = doc.to_dict()
        prompt = self._build_prompt(doc_summary, indicators)

        messages = [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.client.chat_json(messages, phase="classification")
        except Exception:
            # If LLM fails, return empty mappings — downstream handles gracefully
            return self._empty_mappings(indicators)

        return self._parse_result(result, indicators)

    def _build_prompt(
        self, doc_summary: dict, indicators: list[str]
    ) -> str:
        parts = [
            "## Paper Structure",
            json.dumps(doc_summary, ensure_ascii=False, indent=2),
            "",
            "## Indicators to Find",
        ]
        for i, indicator in enumerate(indicators, 1):
            parts.append(f"{i}. {indicator}")
        parts.append("")
        parts.append(
            "Map each indicator to the figures, sections, and tables where "
            "its data can be found. Return valid JSON."
        )
        return "\n".join(parts)

    def _parse_result(
        self, result: dict, indicators: list[str]
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
            if indicator.lower() in seen_indicators:
                continue
            seen_indicators.add(indicator.lower())

            mappings.append(
                IndicatorMapping(
                    indicator=indicator,
                    indicator_keywords=[
                        str(k).strip()
                        for k in (raw.get("indicator_keywords") or [])
                        if str(k).strip()
                    ],
                    figures=[
                        str(f).strip()
                        for f in (raw.get("figures") or [])
                        if str(f).strip()
                    ],
                    sections=[
                        str(s).strip()
                        for s in (raw.get("sections") or [])
                        if str(s).strip()
                    ],
                    tables=[
                        str(t).strip()
                        for t in (raw.get("tables") or [])
                        if str(t).strip()
                    ],
                    extraction_hint=str(raw.get("extraction_hint") or ""),
                    priority=str(raw.get("priority") or "medium").lower(),
                )
            )

        # Ensure all requested indicators have a mapping (even if LLM missed some)
        for indicator in indicators:
            key = indicator.strip().lower()
            if key not in seen_indicators:
                mappings.append(
                    IndicatorMapping(
                        indicator=indicator,
                        priority="medium",
                        extraction_hint="LLM could not classify this indicator.",
                    )
                )

        return mappings

    @staticmethod
    def _empty_mappings(indicators: list[str]) -> list[IndicatorMapping]:
        return [
            IndicatorMapping(indicator=indicator, priority="medium")
            for indicator in indicators
        ]
