from app.services.chart_extraction.axis_calibration import (
    apply_transform,
    axis_calibration_from_ocr,
    dedupe_ticks,
    infer_axis_labels_from_ocr,
    infer_axis_transform,
    linear_transform_from_ticks,
    ocr_numeric_tokens,
    parse_numeric_token,
)
from app.services.chart_extraction.batch import (
    MinerUImageBatchResult,
    process_mineru_image_batch,
    process_mineru_image_record,
    sample_points,
    write_overlay,
)
from app.services.chart_extraction.contracts import AxisContract, Contract, SeriesContract
from app.services.chart_extraction.cv import RawExtraction, RawPixel
from app.services.chart_extraction.cv.verifier import CvVerifier, VerificationReport
from app.services.chart_extraction.io import (
    COORDINATE_CSV_FIELDS,
    RHEOLOGY_STEP_TIME_SWEEP_CSV_FIELDS,
    SUMMARY_CSV_FIELDS,
    load_image_records,
    write_coordinate_csv,
    write_quality_audit_csv,
    write_summary_csv,
)
from app.services.chart_extraction.models import ImageRecord
from app.services.chart_extraction.multi_agent_orchestrator import (
    AgentExtractionResult,
    MultiAgentOrchestrator,
)
from app.services.chart_extraction.agents.vlm_extractor import VlmExtractionResult, VlmExtractor
from app.services.chart_extraction.numerical_validator import (
    NumericalValidator,
    ValidationIssue,
    ValidationResult,
)
from app.services.chart_extraction.plot_geometry import detect_plot_area
from app.services.chart_extraction.quality import (
    annotate_quality,
    image_status_from_rows,
    summarize_quality,
)
from app.services.chart_extraction.schema_validator import SchemaValidator
from app.services.chart_extraction.visual_marks import (
    classify_mark_color,
    component_points,
)

# Legacy stubs — removed from the VLM-centric pipeline but still referenced by production code
CHART_TYPE_CATALOG: list = []
def chart_recipe_catalog() -> list:
    return []

__all__ = [
    "CHART_TYPE_CATALOG",
    "COORDINATE_CSV_FIELDS",
    "RHEOLOGY_STEP_TIME_SWEEP_CSV_FIELDS",
    "SUMMARY_CSV_FIELDS",
    "chart_recipe_catalog",
    "AgentExtractionResult",
    "AxisContract",
    "Contract",
    "CvVerifier",
    "ImageRecord",
    "MinerUImageBatchResult",
    "MultiAgentOrchestrator",
    "NumericalValidator",
    "RawExtraction",
    "RawPixel",
    "SchemaValidator",
    "SeriesContract",
    "ValidationIssue",
    "ValidationResult",
    "VerificationReport",
    "VlmExtractionResult",
    "VlmExtractor",
    "annotate_quality",
    "apply_transform",
    "axis_calibration_from_ocr",
    "classify_mark_color",
    "component_points",
    "dedupe_ticks",
    "detect_plot_area",

    "image_status_from_rows",
    "infer_axis_labels_from_ocr",
    "infer_axis_transform",
    "linear_transform_from_ticks",
    "load_image_records",
    "ocr_numeric_tokens",
    "parse_numeric_token",
    "process_mineru_image_batch",
    "process_mineru_image_record",
    "sample_points",
    "summarize_quality",
    "write_coordinate_csv",
    "write_overlay",
    "write_quality_audit_csv",
    "write_summary_csv",
]
