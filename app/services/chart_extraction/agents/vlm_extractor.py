"""VLM-based chart extraction agent.

Single VLM call: reads a chart image, outputs structured data with
axes, series, and data points. Naming follows app.services.agent.types conventions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.services.agent.llm_client import LLMClient
from app.services.extraction.llm_config import build_vlm_config

logger = logging.getLogger(__name__)


VLM_EXTRACTION_PROMPT = """You are a scientific chart data extraction expert.
Analyze the chart image and extract ALL visible data.

Output JSON format (English, must match this schema exactly):
{
  "chart_type": "line_plot | bar_chart | scatter_plot | spectrum_curve | rheology | microscopy | heatmap | other",
  "confidence": 0.0-1.0,
  "is_simple_chart": true,
  "axes": {
    "x": {"label": "Time", "unit": "hours", "scale": "linear | log10", "range_min": 0, "range_max": 100},
    "y": {"label": "Viscosity", "unit": "mPa·s", "scale": "log10", "range_min": 1, "range_max": 10000},
    "y2": {"label": "Shear Stress", "unit": "Pa", "scale": "linear", "range_min": 0, "range_max": 50}
  },
  "series": [
    {
      "name": "G' (Storage Modulus)",
      "color_name": "red | green | blue | black | orange | brown | gray | purple | pink | yellow",
      "marker_style": "filled_circle | open_circle | filled_triangle | open_triangle | cross | square | none",
      "axis": "y | y2",
      "data_points": [
        {"x": 0.01, "y": 5000.0},
        {"x": 0.1, "y": 4800.0}
      ]
    }
  ],
  "notes": ""
}

Rules:
1. Report ALL visible series. If a curve exists but you cannot read exact values,
   report approximate values and lower the per-series confidence to 0.3.
2. Distinguish marker styles carefully. For rheology charts:
   - Filled markers = G' (storage modulus)
   - Open/unfilled markers = G'' (loss modulus) or η*
   This is critical for correct series identification.
3. For log-scale axes, report actual values (not log10-transformed).
   Example: if the axis tick says 10^2, report x: 100.0
4. Extract 8-12 points per curve to capture the full shape.
   More points for curves with complex shapes, fewer for straight lines.
5. For bar charts, report each bar's value individually.
6. For dual-axis charts, set axis="y" for left-axis series, axis="y2" for right-axis series.
7. Read axis labels and units directly from the chart.
8. If you cannot determine a value, output null in the data point.
9. Set confidence=1.0 when you are certain, 0.5 when approximate, 0.1 when guessing.
10. The y2 axis is optional. If the chart has only one Y-axis, omit y2 entirely.
11. Set is_simple_chart=true when ALL of: single series, linear axes, clear axis labels,
    readable tick values, no dual y-axis. Set false otherwise.
12. Report range_min and range_max for each axis based on visible tick range.
    For log scale, report the actual min/max data values (not log10-transformed).
"""


@dataclass
class VlmExtractionResult:
    """VLM extraction result. Fields match the JSON schema above."""
    chart_type: str = ""
    confidence: float = 0.0
    axes: dict = field(default_factory=dict)
    series: list[dict] = field(default_factory=list)
    notes: str = ""
    raw_json: dict = field(default_factory=dict)
    image_path: str = ""
    error: str = ""
    is_simple_chart: bool = False


class VlmExtractor:
    """Single VLM call: reads a chart and outputs structured data.

    This replaces the 15 specialized CV extractors + classifier + legend agent.
    One call handles classification, axis reading, series identification,
    and data point extraction.
    """

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient(build_vlm_config())

    def extract(self, image_path: str, caption: str = "") -> VlmExtractionResult:
        """Extract structured data from chart image. Single VLM call."""
        image_b64 = self._image_to_data_url(image_path)
        if not image_b64:
            return VlmExtractionResult(
                image_path=image_path,
                error=f"Image not found or unreadable: {image_path}",
            )

        user_text = "Extract all data from this scientific chart."
        if caption:
            user_text += f"\nFigure caption: {caption[:500]}"

        try:
            payload = self.client.chat_json(
                messages=[
                    {"role": "system", "content": VLM_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": image_b64}},
                        ],
                    },
                ],
                phase="vlm_extraction",
            )
        except Exception as exc:
            logger.exception("VLM extraction failed image=%s", image_path)
            return VlmExtractionResult(
                image_path=image_path,
                error=f"VLM call failed: {exc}",
            )

        return self._parse_response(payload, image_path)

    def _parse_response(self, payload: dict, image_path: str) -> VlmExtractionResult:
        """Validate and parse VLM JSON response into VlmExtractionResult."""
        chart_type = str(payload.get("chart_type", "other")).strip().lower()
        confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.0))))
        is_simple_chart = bool(payload.get("is_simple_chart", False))
        axes = payload.get("axes", {})
        series_raw = payload.get("series", [])
        notes = str(payload.get("notes", ""))

        # Validate series structure
        validated_series = []
        for s in series_raw:
            if not isinstance(s, dict):
                continue
            points = s.get("data_points", [])
            if not points:
                continue
            validated_series.append({
                "name": str(s.get("name", f"series_{len(validated_series)}")),
                "color_name": str(s.get("color_name", "unknown")),
                "marker_style": str(s.get("marker_style", "none")),
                "axis": str(s.get("axis", "y")),
                "data_points": points,
            })

        return VlmExtractionResult(
            chart_type=chart_type,
            confidence=confidence,
            is_simple_chart=is_simple_chart,
            axes=axes,
            series=validated_series,
            notes=notes,
            raw_json=payload,
            image_path=image_path,
        )

    @staticmethod
    def _image_to_data_url(image_path: str) -> str | None:
        """Load image and return as base64 data URL."""
        try:
            import base64
            with open(image_path, "rb") as f:
                raw = f.read()
            import mimetypes
            mime = mimetypes.guess_type(image_path)[0] or "image/png"
            return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        except Exception:
            return None
