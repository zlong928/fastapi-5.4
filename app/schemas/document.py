from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
    parsed_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    parse_quality_json: Optional[str] = None
    references_text: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None
    events: list[DocumentEventRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentListItem(BaseModel):
    """文档列表项（简化版本）。"""
    id: int
    title: str
    source_type: str
    status: str
    file_size: int
    created_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    """创建文档时的输入模式。"""
    title: Optional[str] = None
    mime_type: str
    source_type: str = Field(
        pattern="^(pdf|markdown|txt|image)$",
        description="File type: pdf, markdown, txt, or image"
    )
    file_size: int = Field(gt=0, description="File size in bytes")


class DocumentUpdate(BaseModel):
    """更新文档时的输入模式（当前仅支持修改标题）。"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """上传后的响应模式。"""
    id: int
    user_id: int
    title: str
    original_filename: str
    source_type: str
    status: str
    file_size: int
    created_at: datetime
    uploaded_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """文档列表响应模式。"""
    total: int
    items: list[DocumentListItem]


class DocumentDetailResponse(BaseModel):
    """文档详情页响应模式。"""
    id: int
    user_id: int
    title: str
    original_filename: str
    source_type: str
    status: str
    file_size: int
    mime_type: str
    parsed_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    parse_quality_json: Optional[str] = None
    references_text: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    uploaded_at: datetime
    parsed_at: Optional[datetime] = None
    events: list[DocumentEventRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class DocumentSearchResult(BaseModel):
    id: int
    title: str
    source_type: str
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
