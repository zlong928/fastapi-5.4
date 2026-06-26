"""New structured extraction pipeline (v2).

Replaces the old agent-based coordinator with a deterministic, auditable pipeline:
1. ClassificationPipeline —— LLM reads indicators, maps them to figures/sections
2. FigureExtractionPipeline —— LLM + CV for numerical extraction from charts
3. FusionPipeline —— LLM verification that chart data supports text claims
"""

from app.services.extraction.classification_pipeline import (
    ClassificationPipeline,
    IndicatorMapping,
)
from app.services.extraction.figure_extraction_pipeline import (
    FigureExtractionPipeline,
    FigureExtractionResult,
    AxisInfo,
    ExtractedPoint,
)
from app.services.extraction.fusion_pipeline import (
    FusionPipeline,
    FusionResult,
)

__all__ = [
    "ClassificationPipeline",
    "IndicatorMapping",
    "FigureExtractionPipeline",
    "FigureExtractionResult",
    "AxisInfo",
    "ExtractedPoint",
    "FusionPipeline",
    "FusionResult",
]
