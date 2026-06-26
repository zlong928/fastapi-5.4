"""FigureExtractionPipeline: LLM + CV numerical extraction from data charts.

The core problem this solves: CSV exports show meaningless x/y axis labels
("x_value", "y_value") instead of real physical units and numerical scales.

This pipeline:
1. Receives a chart image + its context (caption, nearby text, classification hint)
2. Uses the LLM vision capability to read the chart
3. Extracts: axis labels, units, scales (linear/log), data series
4. Produces numerical data points with real physical units
5. Describes error bars when present
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.agent.llm_client import LLMClient


@dataclass
class AxisInfo:
    """Calibrated axis information with real physical meaning."""

    label: str = ""  # e.g., "Shear rate"
    unit: str = ""  # e.g., "s⁻¹"
    scale: str = "linear"  # "linear" | "log10" | "log"
    range_min: float | None = None  # physical min value
    range_max: float | None = None  # physical max value
    tick_values: list[float] = field(default_factory=list)  # observed tick values
    calibration_confidence: float = 0.0  # 0-1 how confident we are in axis calibration


@dataclass
class ExtractedPoint:
    """A single data point with physical meaning."""

    x_value: float
    y_value: float
    x_unit: str = ""
    y_unit: str = ""
    series_name: str = ""  # e.g., "G' (storage modulus)", "η* (complex viscosity)"
    error_bar: str = ""  # e.g., "±0.5 (SD)" or "" if no error bar


@dataclass
class FigureExtractionResult:
    """Complete extraction result for one figure."""

    figure_label: str  # "Figure 1"
    chart_type: str  # "line_plot" | "bar_chart" | "scatter" | "rheology" | ...
    x_axis: AxisInfo = field(default_factory=AxisInfo)
    y_axis: AxisInfo = field(default_factory=AxisInfo)
    y2_axis: AxisInfo | None = None  # second y-axis (dual-axis charts)
    series: list[str] = field(default_factory=list)  # series names
    data_points: list[ExtractedPoint] = field(default_factory=list)
    overall_description: str = ""  # human-readable summary
    extraction_confidence: float = 0.0  # 0-1
    raw_llm_response: str = ""  # for debugging


FIGURE_EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting numerical data from scientific charts.
Your task is to look at a chart image and extract EVERYTHING with physical meaning.

## CRITICAL RULES

### Axis Labels and Units
- Read the EXACT axis labels from the chart. Never guess "x" or "y".
- Extract the REAL physical units: "s⁻¹", "mPa·s", "Pa", "°C", "mg/L", "%", "nm", etc.
- If a unit is not explicitly shown, infer it from the axis label context
  (e.g., "Temperature" → "°C", "Time" → "s" or "min" or "h").
- Use proper Unicode: "µm" not "um", "s⁻¹" not "s^-1", "mPa·s" not "mPa s".

### Axis Scale
- Determine if each axis is "linear", "log10", or "log" (natural log).
- Log axes: tick marks are at powers of 10 (0.01, 0.1, 1, 10, 100, ...).
- Linear axes: tick marks are evenly spaced.
- Look at the tick mark labels to determine the scale.

### Error Bars
- Describe error bars precisely: "±2.3 (SD, n=3)" or "±0.5 (SEM)" or "none".
- If error bars are visible, note their meaning from the caption or legend.
- Include the error bar description for each data series.

### Data Series
- Name each series with physical meaning: e.g., "G' (storage modulus)",
  "η* (complex viscosity)", "Control group", "Treated sample".
- Do NOT use generic names like "Series 1", "Y1", "Line A".

### Data Points
- Extract the actual numerical values from the chart.
- For line/scatter plots: read points along the curve at representative positions.
- For bar charts: read the bar heights and category labels.
- Values must use the REAL physical units from the axes — NOT normalized/pixel values.
- For log-scale axes: the value is the ACTUAL physical quantity, not the log.

## Output Format
Return a JSON object:
```json
{
  "chart_type": "line_plot|bar_chart|scatter_plot|rheology_flow_curve|rheology_strain_sweep|heatmap|spectrum|microscopy|schematic|other",
  "x_axis": {
    "label": "Shear rate",
    "unit": "s⁻¹",
    "scale": "log10",
    "range_min": 0.01,
    "range_max": 1000,
    "tick_values": [0.01, 0.1, 1, 10, 100, 1000],
    "calibration_confidence": 0.9
  },
  "y_axis": {
    "label": "Viscosity",
    "unit": "mPa·s",
    "scale": "log10",
    "range_min": 1,
    "range_max": 10000,
    "tick_values": [1, 10, 100, 1000, 10000],
    "calibration_confidence": 0.85
  },
  "y2_axis": null,
  "series": ["G' (storage modulus)", "G'' (loss modulus)"],
  "data_points": [
    {
      "x_value": 0.1,
      "y_value": 4500,
      "x_unit": "s⁻¹",
      "y_unit": "mPa·s",
      "series_name": "G' (storage modulus)",
      "error_bar": "±200 (SD)"
    }
  ],
  "overall_description": "Log-log plot of viscosity vs shear rate showing shear thinning behavior...",
  "extraction_confidence": 0.85
}
```

If the image is NOT a data chart (e.g., microscopy, photo, schematic), set:
- chart_type: "microscopy" or "schematic"
- x_axis and y_axis with empty strings
- data_points: []
- overall_description: describe what you see
"""


class FigureExtractionPipeline:
    """Extract numerical data from a chart figure using LLM vision."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def extract(
        self,
        *,
        image_path: str,
        figure_label: str = "",
        caption: str = "",
        nearby_text: str = "",
        extraction_hint: str = "",
        chart_type_hint: str = "",
    ) -> FigureExtractionResult:
        """Extract numerical data from a chart image.

        Args:
            image_path: Path to the chart image file.
            figure_label: e.g., "Figure 1".
            caption: The figure caption text.
            nearby_text: Text surrounding the figure in the paper.
            extraction_hint: Hint from ClassificationPipeline about what to extract.
            chart_type_hint: Chart type hint from upstream routing.

        Returns:
            ``FigureExtractionResult`` with calibrated axes and data points.
        """
        image_data_url = self.client.image_data_url(image_path)
        if image_data_url is None:
            return FigureExtractionResult(
                figure_label=figure_label,
                chart_type="error",
                overall_description=f"Cannot read image: {image_path}",
                extraction_confidence=0.0,
            )

        user_content = self._build_user_prompt(
            figure_label=figure_label,
            caption=caption,
            nearby_text=nearby_text,
            extraction_hint=extraction_hint,
            chart_type_hint=chart_type_hint,
        )

        messages = [
            {"role": "system", "content": FIGURE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ]

        try:
            result = self.client.chat_json(messages, phase="figure_extraction")
        except Exception as exc:
            return FigureExtractionResult(
                figure_label=figure_label,
                chart_type="error",
                overall_description=f"LLM extraction failed: {exc}",
                extraction_confidence=0.0,
            )

        return self._parse_result(result, figure_label)

    def extract_from_asset(
        self,
        db: Any,
        asset: Any,
        prompt: str = "",
        indicator: str = "",
    ):
        """Extract numerical data from a DocumentAsset (figure image in paper)."""
        from app.services.file_storage import FileStorageService

        storage = FileStorageService()
        image_path = storage.get_file_path(asset.file_path)
        caption = str(asset.caption or "")
        figure_label = str(asset.label or "")
        try:
            meta = json.loads(asset.metadata_json or "{}")
        except Exception:
            meta = {}
        chart_type_hint = str(meta.get("chart_type") or meta.get("image_type") or meta.get("figure_type") or "")
        extraction_hint = indicator or prompt
        nearby_text = " ".join(
            str(meta.get(k) or "") for k in ("agent_description", "context", "caption") if meta.get(k)
        )
        return self.extract(
            image_path=str(image_path),
            figure_label=figure_label,
            caption=caption,
            nearby_text=nearby_text,
            extraction_hint=extraction_hint,
            chart_type_hint=chart_type_hint,
        )

    def _build_user_prompt(
        self,
        figure_label: str,
        caption: str,
        nearby_text: str,
        extraction_hint: str,
        chart_type_hint: str,
    ) -> str:
        parts = []
        if figure_label:
            parts.append(f"Figure: {figure_label}")
        if chart_type_hint:
            parts.append(f"Chart type hint: {chart_type_hint}")
        if extraction_hint:
            parts.append(f"Extraction focus: {extraction_hint}")
        if caption:
            parts.append(f"Caption: {caption}")
        if nearby_text:
            parts.append(f"Nearby text: {nearby_text[:500]}")
        parts.append(
            "\nExtract all numerical data from this chart with proper axis labels, "
            "units, scales, error bars, and series names. Return valid JSON only."
        )
        return "\n".join(parts)

    def _parse_result(
        self, result: dict, figure_label: str
    ) -> FigureExtractionResult:
        chart_type = str(result.get("chart_type") or "other")

        # Parse x_axis
        x_raw = result.get("x_axis") or {}
        x_axis = AxisInfo(
            label=str(x_raw.get("label") or ""),
            unit=str(x_raw.get("unit") or ""),
            scale=str(x_raw.get("scale") or "linear"),
            range_min=self._as_float(x_raw.get("range_min")),
            range_max=self._as_float(x_raw.get("range_max")),
            tick_values=[
                float(v)
                for v in (x_raw.get("tick_values") or [])
                if isinstance(v, (int, float))
            ],
            calibration_confidence=self._as_float(
                x_raw.get("calibration_confidence"), 0.0
            ),
        )

        # Parse y_axis
        y_raw = result.get("y_axis") or {}
        y_axis = AxisInfo(
            label=str(y_raw.get("label") or ""),
            unit=str(y_raw.get("unit") or ""),
            scale=str(y_raw.get("scale") or "linear"),
            range_min=self._as_float(y_raw.get("range_min")),
            range_max=self._as_float(y_raw.get("range_max")),
            tick_values=[
                float(v)
                for v in (y_raw.get("tick_values") or [])
                if isinstance(v, (int, float))
            ],
            calibration_confidence=self._as_float(
                y_raw.get("calibration_confidence"), 0.0
            ),
        )

        # Parse optional y2_axis
        y2_raw = result.get("y2_axis")
        y2_axis = None
        if isinstance(y2_raw, dict) and y2_raw:
            y2_axis = AxisInfo(
                label=str(y2_raw.get("label") or ""),
                unit=str(y2_raw.get("unit") or ""),
                scale=str(y2_raw.get("scale") or "linear"),
                range_min=self._as_float(y2_raw.get("range_min")),
                range_max=self._as_float(y2_raw.get("range_max")),
            )

        # Parse series names
        series_raw = result.get("series") or []
        series = [
            str(s) for s in series_raw if isinstance(s, str) and s.strip()
        ]

        # Parse data points
        data_points: list[ExtractedPoint] = []
        for dp in result.get("data_points") or []:
            if not isinstance(dp, dict):
                continue
            x_val = self._as_float(dp.get("x_value"))
            y_val = self._as_float(dp.get("y_value"))
            if x_val is None or y_val is None:
                continue
            data_points.append(
                ExtractedPoint(
                    x_value=x_val,
                    y_value=y_val,
                    x_unit=str(dp.get("x_unit") or x_axis.unit),
                    y_unit=str(dp.get("y_unit") or y_axis.unit),
                    series_name=str(dp.get("series_name") or ""),
                    error_bar=str(dp.get("error_bar") or ""),
                )
            )

        return FigureExtractionResult(
            figure_label=figure_label,
            chart_type=chart_type,
            x_axis=x_axis,
            y_axis=y_axis,
            y2_axis=y2_axis,
            series=series,
            data_points=data_points,
            overall_description=str(
                result.get("overall_description") or ""
            ),
            extraction_confidence=self._as_float(
                result.get("extraction_confidence"), 0.0
            ),
            raw_llm_response=json.dumps(result, ensure_ascii=False),
        )

    @staticmethod
    def _as_float(value: Any, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
