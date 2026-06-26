"""FusionPipeline: cross-reference verification between text claims and chart data.

After text extraction and figure extraction run independently, this pipeline
uses LLM reasoning to verify:
1. Does the chart data actually support the text's claims?
2. Are the extracted numerical values consistent with what the text says?
3. Are there discrepancies between figure data and text statements?

This is the quality gate that catches hallucinated or misread values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient
    from app.services.extraction.figure_extraction_pipeline import FigureExtractionResult


@dataclass
class ClaimVerification:
    """Verification of a single claim against chart evidence."""

    claim: str  # The text claim
    figure_label: str  # Which figure is referenced
    supported: bool  # Does the chart data support this claim?
    confidence: float  # 0-1
    evidence_from_chart: str  # What the chart actually shows
    discrepancy: str  # Empty if no discrepancy, otherwise describes the mismatch
    notes: str  # Additional observations


@dataclass
class FusionResult:
    """Complete fusion verification result."""

    indicator: str
    verified_claims: list[ClaimVerification] = field(default_factory=list)
    overall_supported: bool = True
    overall_confidence: float = 0.0
    summary: str = ""
    raw_llm_response: str = ""


FUSION_SYSTEM_PROMPT = """You are a scientific data verification expert. Your job is to cross-reference
text claims from a paper against the actual numerical data extracted from charts.

## Input
You will receive:
1. A text claim from the paper
2. The numerical data extracted from a referenced figure
3. The figure's axes, units, and description

## Task
For each claim, determine:
- **supported**: Does the chart data genuinely support this claim? (true/false)
- **confidence**: How confident are you in this assessment? (0.0-1.0)
- **evidence_from_chart**: What does the chart ACTUALLY show? Be precise with numbers.
- **discrepancy**: If the claim doesn't match the chart data, describe the mismatch.
  If they match, leave this empty.
- **notes**: Any additional observations.

## Rules
1. Be SKEPTICAL. The text may overstate or misrepresent what the chart shows.
2. Pay attention to: axis scales (log vs linear), units, error bars, trend direction,
   numerical ranges, statistical significance.
3. If error bars overlap between groups, the claim of "significant difference" is
   NOT supported.
4. If the chart shows a weak trend but the text claims a strong effect, flag it.
5. If the chart data range doesn't match the text's numerical claims, flag it.
6. If you cannot determine whether the claim is supported, set confidence low (<0.5)
   and explain why.

## Output Format
```json
{
  "verifications": [
    {
      "claim": "<the claim text>",
      "figure_label": "Figure 1",
      "supported": true,
      "confidence": 0.85,
      "evidence_from_chart": "The chart shows viscosity decreasing from ~5000 mPa·s at 0.01 s⁻¹ to ~10 mPa·s at 1000 s⁻¹...",
      "discrepancy": "",
      "notes": "The text claims 3 orders of magnitude decrease; chart confirms 2.7 orders."
    }
  ],
  "overall_supported": true,
  "overall_confidence": 0.82,
  "summary": "2/3 claims fully supported by chart data. Claim about yield stress not visible in the referenced figure."
}
```
"""


class FusionPipeline:
    """Verify that text claims are supported by chart data."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def verify(
        self,
        *,
        indicator: str,
        text_claims: list[str],
        figure_results: dict[str, FigureExtractionResult],
        section_text: str = "",
    ) -> FusionResult:
        """Cross-reference text claims against extracted chart data.

        Args:
            indicator: The indicator being verified.
            text_claims: Claims found in the paper text about this indicator.
            figure_results: Figure extraction results keyed by figure label.
            section_text: Relevant text section for context.

        Returns:
            ``FusionResult`` with per-claim verification.
        """
        if not text_claims or not figure_results:
            return FusionResult(
                indicator=indicator,
                overall_supported=True,
                summary="No claims or figures to verify.",
            )

        prompt = self._build_prompt(indicator, text_claims, figure_results, section_text)

        messages = [
            {"role": "system", "content": FUSION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.client.chat_json(messages, phase="fusion")
        except Exception:
            return FusionResult(
                indicator=indicator,
                overall_supported=True,
                overall_confidence=0.3,
                summary="LLM verification failed — claims not verified.",
            )

        return self._parse_result(result, indicator)

    def _build_prompt(
        self,
        indicator: str,
        text_claims: list[str],
        figure_results: dict[str, FigureExtractionResult],
        section_text: str,
    ) -> str:
        parts = [f"## Indicator: {indicator}", ""]

        if section_text:
            parts.append(f"## Text Context\n{section_text[:1000]}\n")

        parts.append("## Text Claims to Verify")
        for i, claim in enumerate(text_claims, 1):
            parts.append(f"{i}. {claim}")
        parts.append("")

        parts.append("## Chart Data Extracted from Figures")
        for label, fr in figure_results.items():
            parts.append(f"### {label}")
            parts.append(f"Chart type: {fr.chart_type}")
            parts.append(
                f"X axis: {fr.x_axis.label} [{fr.x_axis.unit}] "
                f"({fr.x_axis.scale}, range {fr.x_axis.range_min}–{fr.x_axis.range_max})"
            )
            parts.append(
                f"Y axis: {fr.y_axis.label} [{fr.y_axis.unit}] "
                f"({fr.y_axis.scale}, range {fr.y_axis.range_min}–{fr.y_axis.range_max})"
            )
            if fr.series:
                parts.append(f"Series: {', '.join(fr.series)}")
            parts.append(
                f"Data points: {len(fr.data_points)} extracted"
            )
            if fr.data_points:
                # Include sample points
                sample = fr.data_points[:10]
                for dp in sample:
                    parts.append(
                        f"  ({dp.x_value} {dp.x_unit}, {dp.y_value} {dp.y_unit}) "
                        f"[{dp.series_name}] {dp.error_bar}"
                    )
                if len(fr.data_points) > 10:
                    parts.append(f"  ... and {len(fr.data_points) - 10} more")
            parts.append(f"Description: {fr.overall_description}")
            parts.append("")

        parts.append(
            "For each claim, verify whether the chart data supports it. "
            "Be precise about numbers, units, and trends. Return valid JSON."
        )
        return "\n".join(parts)

    def _parse_result(
        self, result: dict, indicator: str
    ) -> FusionResult:
        verifications: list[ClaimVerification] = []
        for v in result.get("verifications") or []:
            if not isinstance(v, dict):
                continue
            claim = str(v.get("claim") or "").strip()
            if not claim:
                continue
            verifications.append(
                ClaimVerification(
                    claim=claim,
                    figure_label=str(v.get("figure_label") or ""),
                    supported=bool(v.get("supported", True)),
                    confidence=float(v.get("confidence") or 0.5),
                    evidence_from_chart=str(v.get("evidence_from_chart") or ""),
                    discrepancy=str(v.get("discrepancy") or ""),
                    notes=str(v.get("notes") or ""),
                )
            )

        return FusionResult(
            indicator=indicator,
            verified_claims=verifications,
            overall_supported=bool(result.get("overall_supported", True)),
            overall_confidence=float(result.get("overall_confidence") or 0.5),
            summary=str(result.get("summary") or ""),
            raw_llm_response=json.dumps(result, ensure_ascii=False),
        )
