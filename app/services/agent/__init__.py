# Agent module: export all public types and classes
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.agent.types import (
    ImageType,
    VisualCategory,
    ExtractionPoint,
    FigureExtractionPlan,
    ExtractionTask,
    ExtractionMap,
    FigureInfo,
    TableInfo,
    PaperData,
    SupervisorState,
    ChartMetadata,
    CaptionBinding,
    EXTRACTION_POINT_FIELDS,
    EXTRACTION_POINT_SCHEMA_VERSION,
    extraction_point_to_dict,
    extraction_point_from_dict,
)
from app.services.agent.quality_agent import (
    check_quality,
    check_batch_quality,
    summarize_quality_from_points,
    annotate_points_quality,
)
from app.services.agent.point_exporter import (
    export_points_csv,
    extract_points_to_db_format,
    merge_points_into_extraction_result,
    extract_points_csv_table,
    extract_points_json,
)

if TYPE_CHECKING:
    from app.services.agent.caption_agent import CaptionAlignmentAgent
    from app.services.agent.classifier_agent import FigureTypeClassifierAgent
    from app.services.agent.morphology_agent import MorphologyAgent
    from app.services.agent.protein_agent import ProteinAgent


def __getattr__(name: str):
    """Lazy import to break circular dependencies."""
    if name == "CaptionAlignmentAgent":
        from app.services.agent.caption_agent import CaptionAlignmentAgent
        return CaptionAlignmentAgent
    elif name == "FigureTypeClassifierAgent":
        from app.services.agent.classifier_agent import FigureTypeClassifierAgent
        return FigureTypeClassifierAgent
    elif name == "image_type_to_visual_category":
        from app.services.agent.classifier_agent import image_type_to_visual_category
        return image_type_to_visual_category
    elif name == "MorphologyAgent":
        from app.services.agent.morphology_agent import MorphologyAgent
        return MorphologyAgent
    elif name == "ProteinAgent":
        from app.services.agent.protein_agent import ProteinAgent
        return ProteinAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ImageType",
    "VisualCategory",
    "ExtractionPoint",
    "FigureExtractionPlan",
    "ExtractionTask",
    "ExtractionMap",
    "FigureInfo",
    "TableInfo",
    "PaperData",
    "SupervisorState",
    "ChartMetadata",
    "CaptionBinding",
    "EXTRACTION_POINT_FIELDS",
    "EXTRACTION_POINT_SCHEMA_VERSION",
    "extraction_point_to_dict",
    "extraction_point_from_dict",
    "CaptionAlignmentAgent",
    "FigureTypeClassifierAgent",
    "image_type_to_visual_category",
    "MorphologyAgent",
    "ProteinAgent",
    "check_quality",
    "check_batch_quality",
    "summarize_quality_from_points",
    "annotate_points_quality",
    "export_points_csv",
    "extract_points_to_db_format",
    "merge_points_into_extraction_result",
    "extract_points_csv_table",
    "extract_points_json",
]
