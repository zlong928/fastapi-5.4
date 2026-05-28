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
    notes: Optional[str] = None
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
