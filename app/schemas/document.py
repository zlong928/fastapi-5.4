from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DocumentProcessingMode(str, Enum):
    AUTO = "auto"
    PLAIN_TEXT = "plain_text"
    PDF_TEXT = "pdf_text"
    SCANNED_PDF_OCR = "scanned_pdf_ocr"
    IMAGE_OCR = "image_ocr"
    MARKDOWN_NOTES = "markdown_notes"
    TABLE_IMAGE_OCR = "table_image_ocr"
    BASIC_FILE_PARSER = "basic_file_parser"


class DocumentEventRead(BaseModel):
    """文档事件的读取模式。"""
    id: int
    document_id: int
    user_id: int
    event_type: str
    message: str
    event_metadata: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedDocumentEvents(BaseModel):
    total: int
    page: int
    size: int
    items: list[DocumentEventRead]


class TagRead(BaseModel):
    id: int
    user_id: int
    name: str
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: Optional[str] = Field(default=None, max_length=32)


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    color: Optional[str] = Field(default=None, max_length=32)


class CollectionRead(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None


class BookmarkCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    collection_name: Optional[str] = Field(default=None, max_length=255)
    tag_ids: list[int] = Field(default_factory=list, max_length=50)
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO


class BookmarkCreateResponse(BaseModel):
    document_id: int
    status: str
    processing_status: str
    source_type: str = "bookmark"
    source_url: Optional[str] = None
    message: str


class DocumentRead(BaseModel):
    """文档的完整读取模式，包含事件。"""
    id: int
    user_id: int
    title: str
    original_filename: str
    stored_filename: str
    original_file_path: str
    file_size: int
    mime_type: str
    source_type: str
    source_url: Optional[str] = None
    site_name: Optional[str] = None
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO
    processing_strategy: Optional[str] = None
    parsed_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    parse_quality_json: Optional[str] = None
    references_text: Optional[str] = None
    collection_name: Optional[str] = None
    content_hash: Optional[str] = None
    content_summary: Optional[str] = None
    chunk_count: int = 0
    status: str
    processing_status: str
    error_message: Optional[str] = None
    fail_reason: Optional[str] = None
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None
    events: list[DocumentEventRead] = Field(default_factory=list)
    tags: list[TagRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentListItem(BaseModel):
    """文档列表项（简化版本）。"""
    id: int
    title: str
    source_type: str
    source_url: Optional[str] = None
    site_name: Optional[str] = None
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO
    processing_strategy: Optional[str] = None
    status: str
    processing_status: str
    file_size: int
    original_filename: str
    error_message: Optional[str] = None
    fail_reason: Optional[str] = None
    processing_error: Optional[str] = None
    latest_parse_job_status: Optional[str] = None
    collection_name: Optional[str] = None
    content_hash: Optional[str] = None
    content_summary: Optional[str] = None
    chunk_count: int = 0
    page_count: Optional[int] = None
    asset_counts: dict[str, int] = Field(default_factory=dict)
    claim_count: int = 0
    created_at: datetime
    updated_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None
    tags: list[TagRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    """创建文档时的输入模式。"""
    title: Optional[str] = None
    mime_type: str
    source_type: str = Field(
        pattern="^(pdf|markdown|txt|image|docx|epub|bookmark|note|diary)$",
        description="File type: pdf, markdown, txt, image, docx, epub, bookmark, note, or diary"
    )
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO
    file_size: int = Field(ge=0, description="File size in bytes")


class DocumentUpdate(BaseModel):
    """更新文档时的输入模式（当前仅支持修改标题）。"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    collection_name: Optional[str] = Field(None, max_length=255)

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """上传后的响应模式。"""
    document_id: int
    status: str
    processing_status: str
    parse_job_id: int
    job_id: Optional[str] = None
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO
    message: str

    class Config:
        from_attributes = True


class DocumentBatchUploadItem(BaseModel):
    filename: str
    ok: bool
    document_id: Optional[int] = None
    parse_job_id: Optional[int] = None
    job_id: Optional[str] = None
    status: Optional[str] = None
    processing_mode: Optional[DocumentProcessingMode] = None
    error: Optional[str] = None


class ParseJobRead(BaseModel):
    """Compatibility shape for latest_parse_job, now backed by JobRun."""

    id: int
    document_id: int
    user_id: int
    status: str
    job_type: str
    job_id: Optional[str] = None
    metadata_json: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentChunkRead(BaseModel):
    id: int
    document_id: int
    parse_job_id: Optional[int] = None
    chunk_index: int
    chunk_type: str
    text: str
    cleaned_text: str
    token_count: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    metadata_json: Optional[str] = None
    vector_id: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    embedded_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentAssetRead(BaseModel):
    id: int
    document_id: int
    parse_job_id: Optional[int] = None
    asset_type: str
    asset_index: Optional[int] = None
    label: Optional[str] = None
    caption: Optional[str] = None
    page_number: Optional[int] = None
    file_path: Optional[str] = None
    mime_type: Optional[str] = None
    ocr_text: Optional[str] = None
    markdown: Optional[str] = None
    text_content: Optional[str] = None
    summary: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class DocumentClaimRead(BaseModel):
    id: int
    document_id: int
    claim_text: str
    claim_type: str
    source_type: str
    source_id: Optional[int] = None
    page_number: Optional[int] = None
    evidence_text: str
    confidence: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class DocumentListResponse(BaseModel):
    """文档列表响应模式。"""
    total: int
    page: int = 1
    size: int = 20
    items: list[DocumentListItem]


class DocumentDetailResponse(BaseModel):
    """文档详情页响应模式。"""
    id: int
    user_id: int
    title: str
    original_filename: str
    source_type: str
    source_url: Optional[str] = None
    site_name: Optional[str] = None
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.AUTO
    processing_strategy: Optional[str] = None
    status: str
    processing_status: str
    file_size: int
    mime_type: str
    parsed_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    parse_quality_json: Optional[str] = None
    references_text: Optional[str] = None
    collection_name: Optional[str] = None
    content_hash: Optional[str] = None
    content_summary: Optional[str] = None
    chunk_count: int = 0
    page_count: Optional[int] = None
    metadata: dict = Field(default_factory=dict)
    evidence_counts: dict[str, int] = Field(default_factory=dict)
    error_message: Optional[str] = None
    fail_reason: Optional[str] = None
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None
    latest_parse_job: Optional[ParseJobRead] = None
    events: list[DocumentEventRead] = Field(default_factory=list)
    tags: list[TagRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentSearchResult(BaseModel):
    id: int
    title: str
    source_type: str
    source_url: Optional[str] = None
    site_name: Optional[str] = None
    status: str
    snippet: str
    matched_field: str
    score: float = 0.0
    parsed_at: Optional[datetime] = None


class DocumentSearchResponse(BaseModel):
    query: str
    total: int
    items: list[DocumentSearchResult]


class KgEntityRead(BaseModel):
    id: int
    document_id: int
    chunk_id: Optional[int] = None
    name: str
    entity_type: str
    normalized_name: str

    class Config:
        from_attributes = True


class KgRelationRead(BaseModel):
    id: int
    document_id: int
    chunk_id: int
    subject_text: str
    predicate: str
    object_text: str
    evidence_text: str
    confidence: int

    class Config:
        from_attributes = True


class DocumentKgResponse(BaseModel):
    document_id: int
    entities: list[KgEntityRead]
    relations: list[KgRelationRead]


# ── Chunk-level search schemas ──────────────────────────────────────────────

class ChunkSearchHit(BaseModel):
    chunk_id: int
    id: str
    document_id: int
    document_title: str
    filename: str
    chunk_index: int
    chunk_type: str
    text: str
    score: float
    metadata: dict = Field(default_factory=dict)
    source: Optional[str] = None
    start_index: Optional[int] = None
    hash: Optional[str] = None
    page_start: int | None = None
    page_end: int | None = None


class DocumentProcessingStatusResponse(BaseModel):
    document_id: int
    status: str
    processing_status: str
    error: Optional[str] = None
    processing_error: Optional[str] = None
    collection_name: Optional[str] = None
    source_url: Optional[str] = None
    site_name: Optional[str] = None
    hash: Optional[str] = None
    content_summary: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class ChunkSearchResponse(BaseModel):
    query: str
    total: int
    items: list[ChunkSearchHit]


class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


class BatchDeleteResponse(BaseModel):
    success_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)
    errors: dict[int, str] = Field(default_factory=dict)


class BatchTagRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=100)
    tag_ids: list[int] = Field(min_length=1, max_length=50)


class BatchTagResponse(BaseModel):
    document_ids: list[int]
    tag_ids: list[int]
    assigned_count: int


class FileTypeCount(BaseModel):
    file_type: str
    count: int
    ratio: float


class StatusCount(BaseModel):
    status: str
    count: int


class DashboardStatsResponse(BaseModel):
    total_documents: int
    done_documents: int
    failed_documents: int
    parse_success_rate: float
    recent_7_days_documents: int
    file_type_distribution: list[FileTypeCount]
    status_distribution: list[StatusCount]
