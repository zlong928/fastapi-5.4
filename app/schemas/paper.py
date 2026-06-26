from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PaperListItem(BaseModel):
    id: int
    title: str
    status: str
    parse_error: Optional[str] = None
    progress_label: str = "等待"
    asset_counts: dict[str, int] = Field(default_factory=dict)
    uploaded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CoordinatePreviewRead(BaseModel):
    image_type: str = ""
    status: str = ""
    row_count: int = 0
    data_quality: str = ""
    sample_limit: int = 15
    csv_url: Optional[str] = None
    overlay_path: Optional[str] = None
    summary_csv_path: Optional[str] = None
    quality_audit_csv_path: Optional[str] = None
    run_manifest_path: Optional[str] = None
    selected_extractor: str = ""
    reason: str = ""
    chart_type_hint: str = ""
    targets: list[str] = Field(default_factory=list)
    request_id: str = ""
    triggered_at: Optional[datetime] = None
    semantic_binding: str = ""
    review_status: str = ""
    review_notes: str = ""
    extraction_method: str = ""
    text_evidence_refs: list[str] = Field(default_factory=list)
    semantic_columns: list[str] = Field(default_factory=list)


class CoordinatePreviewRunRequest(BaseModel):
    chart_type: str = Field(default="auto", max_length=80)
    targets: list[str] = Field(default_factory=list, max_length=12)
    sample_limit: int = Field(default=120, ge=1, le=500)
    force_regenerate: bool = False


class PaperFigureRead(BaseModel):
    id: int
    paper_id: int
    asset_type: str
    image_path: str
    figure_label: str
    caption: str
    page: Optional[int] = None
    source: Optional[str] = None
    fallback: bool = False
    visual_role: Optional[str] = None
    evidence_type: str = "unknown"
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    bbox: Optional[list[float]] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None
    analysis_status: Optional[str] = None
    analysis_error: Optional[str] = None
    coordinate_preview: Optional[CoordinatePreviewRead] = None
    created_at: datetime


class PaperTableRead(BaseModel):
    id: int
    paper_id: int
    table_label: str
    content: str
    page: Optional[int] = None
    parse_status: str = "partial"
    source: str = "text_candidate"
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExtractionResultRead(BaseModel):
    id: int
    job_id: int
    source_type: str
    source_id: Optional[int] = None
    field_name: str
    content: str
    evidence: str
    confidence: Optional[float] = None
    evidence_type: str = "unknown"
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None
    caption: Optional[str] = None
    source: Optional[str] = None
    figure_id: Optional[str] = None
    notes: Optional[str] = None
    structured_data: Optional[str] = None
    parse_status: Optional[str] = None
    extraction_mode: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExtractionJobRead(BaseModel):
    id: int
    paper_id: int
    query: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    results: list[ExtractionResultRead] = Field(default_factory=list)
    progress: Optional[dict] = None

    class Config:
        from_attributes = True


class ExtractionJobListItem(BaseModel):
    id: int
    paper_id: int
    paper_title: str
    query: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    result_count: int = 0
    progress: Optional[dict] = None


class PaperAskRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=2000)


class PaperAskEvidence(BaseModel):
    document_id: int
    source_type: str
    source_id: int
    asset_type: Optional[str] = None
    asset_id: Optional[int] = None
    label: Optional[str] = None
    page_number: Optional[int] = None
    reason: str


class PaperAskResponse(BaseModel):
    answer: str
    evidence: list[PaperAskEvidence] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class PaperDetailResponse(BaseModel):
    id: int
    user_id: int
    title: str
    file_path: str
    status: str
    parse_error: Optional[str] = None
    text_content: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    figures: list[PaperFigureRead] = Field(default_factory=list)
    tables: list[PaperTableRead] = Field(default_factory=list)
    latest_extraction_job: Optional[ExtractionJobRead] = None


class ExtractionRunRequest(BaseModel):
    paperId: int
    query: str = Field(min_length=1, max_length=2000)
    assetId: Optional[int] = None


class BatchExtractionRunRequest(BaseModel):
    paper_ids: list[int] = Field(min_length=1, max_length=50)
    query: str = Field(min_length=1, max_length=2000)


class BatchExtractionResultItem(BaseModel):
    paper_id: int
    paper_title: str
    job_id: Optional[int] = None
    status: str
    error: Optional[str] = None


class PaperStatisticsResponse(BaseModel):
    total_papers: int = 0
    parsed_papers: int = 0
    failed_papers: int = 0
    processing_papers: int = 0
    total_extractions: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    total_figures: int = 0
    total_tables: int = 0
    avg_confidence: Optional[float] = None
    recent_7_days_papers: int = 0
    recent_7_days_extractions: int = 0


class ChartTypeCatalogItem(BaseModel):
    image_type: str
    label: str
    suitable_for_csv: bool
    processing_chain: str
    typical_content: list[str] = Field(default_factory=list)
    coordinate_output: str = ""
    binding_requirements: list[str] = Field(default_factory=list)
    requires_review: bool = False


class ChartRecipePanelRead(BaseModel):
    panel_id: str
    y_top_px: float
    y_bottom_px: float
    y_axis_label: str
    y_axis_unit: str = ""


class ChartRecipeCatalogItem(BaseModel):
    recipe_id: str
    image_type: str
    filename_prefixes: list[str] = Field(default_factory=list)
    caption_hints: list[str] = Field(default_factory=list)
    x_axis_label: str
    x_axis_unit: str = ""
    x_axis_type: str = "linear"
    y_axis_type: str = "linear"
    axis_calibration_method: str = ""
    known_x_axis_calibrated: bool = False
    known_y_axis_calibrated: bool = False
    y_right_axis_type: str = ""
    source_path: str = ""
    panels: list[ChartRecipePanelRead] = Field(default_factory=list)


class ChartTypeRuntimeStats(BaseModel):
    image_type: str
    total: int = 0
    accepted: int = 0
    review_required: int = 0
    skipped: int = 0
    failed: int = 0
    row_count: int = 0


class StructuredFigureResult(BaseModel):
    id: int
    figure_id: Optional[str] = None
    caption: Optional[str] = None
    image_url: Optional[str] = None
    page: Optional[int] = None
    evidence_type: str = "unknown"
    source: Optional[str] = None
    metric: str
    value: str
    evidence: str
    confidence: Optional[str] = None
    notes: Optional[str] = None
    image_type: Optional[str] = None
    review_status: Optional[str] = None
    extraction_method: Optional[str] = None
    data_points: list[dict] = Field(default_factory=list)
    text_evidence_refs: list[str] = Field(default_factory=list)
    x_axis_label: Optional[str] = None
    x_axis_unit: Optional[str] = None
    x_axis_scale: Optional[str] = None
    y_axis_label: Optional[str] = None
    y_axis_unit: Optional[str] = None
    y_axis_scale: Optional[str] = None
    series_name: Optional[str] = None


class StructuredTableResult(BaseModel):
    id: int
    table_id: Optional[str] = None
    structured_data: Optional[str] = None
    parse_status: Optional[str] = None
    page: Optional[int] = None
    evidence_type: str = "table"
    source: Optional[str] = None
    metric: str
    value: str
    evidence: str
    notes: Optional[str] = None


class StructuredTextResult(BaseModel):
    id: int
    metric: str
    value: str
    evidence: str
    page: Optional[int] = None
    evidence_type: str = "text"
    source: Optional[str] = None
    confidence: Optional[str] = None


class PaperFigureAsset(BaseModel):
    id: int
    figure_label: str
    caption: Optional[str] = None
    image_url: Optional[str] = None
    page: Optional[int] = None
    source: Optional[str] = None
    evidence_type: str = "unknown"
    asset_type: str
    coordinate_capable: bool = False
    coordinate_preview: Optional[CoordinatePreviewRead] = None


class StructuredExtractionResponse(BaseModel):
    paper_id: int
    title: str
    task: str
    status: str
    error_message: Optional[str] = None
    summary: dict
    figure_results: list[StructuredFigureResult] = Field(default_factory=list)
    table_results: list[StructuredTableResult] = Field(default_factory=list)
    text_results: list[StructuredTextResult] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    paper_figures: list[PaperFigureAsset] = Field(default_factory=list)
    chart_type_stats: list[ChartTypeRuntimeStats] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
