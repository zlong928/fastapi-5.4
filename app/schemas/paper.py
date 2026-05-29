from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PaperUploadResponse(BaseModel):
    id: int
    title: str
    status: str


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


class StructuredFigureResult(BaseModel):
    figure_id: Optional[str] = None
    caption: Optional[str] = None
    image_url: Optional[str] = None
    metric: str
    value: str
    evidence: str
    confidence: Optional[str] = None
    notes: Optional[str] = None


class StructuredTableResult(BaseModel):
    table_id: Optional[str] = None
    structured_data: Optional[str] = None
    parse_status: Optional[str] = None
    metric: str
    value: str
    evidence: str
    notes: Optional[str] = None


class StructuredTextResult(BaseModel):
    metric: str
    value: str
    evidence: str
    confidence: Optional[str] = None


class PaperFigureAsset(BaseModel):
    id: int
    figure_label: str
    caption: Optional[str] = None
    image_url: Optional[str] = None
    page: Optional[int] = None
    source: Optional[str] = None
    asset_type: str


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
    created_at: datetime
    updated_at: datetime
