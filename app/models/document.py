from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.tag import DocumentTag
    from app.models.document_event import DocumentEvent
    from app.models.document_asset import DocumentAsset
    from app.models.document_chunk import DocumentChunk
    from app.models.kg_entity import KgEntity
    from app.models.kg_relation import KgRelation
    from app.models.job_run import JobRun
    from app.models.parse_job import ParseJob
    from app.models.user import User


class Document(Base):
    """文档模型，存储用户上传的文件及其解析结果。"""
    
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_documents_user_file_hash"),
        Index("ix_documents_user_file_hash", "user_id", "file_hash"),
    )

    # 主键和外键
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # 基本信息
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # pdf, markdown, txt
    processing_mode: Mapped[str] = mapped_column(String(50), default="auto", nullable=False)
    processing_strategy: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 解析结果
    parsed_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_quality_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    references_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    collection_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    content_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 状态管理
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    # Document.status describes the business document lifecycle.
    # JobRun.status describes execution of background work such as parsing.
    # pending -> processing -> done/failed -> deleted
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fail_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        onupdate=lambda: app_now(),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        nullable=False,
    )
    parsed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # 关系
    user: Mapped[User] = relationship("User", back_populates="documents")
    tag_links: Mapped[list[DocumentTag]] = relationship(
        "DocumentTag",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    events: Mapped[list[DocumentEvent]] = relationship(
        "DocumentEvent",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    assets: Mapped[list[DocumentAsset]] = relationship(
        "DocumentAsset",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    parse_jobs: Mapped[list[ParseJob]] = relationship(
        "ParseJob",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    job_runs: Mapped[list[JobRun]] = relationship(
        "JobRun",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    kg_entities: Mapped[list[KgEntity]] = relationship(
        "KgEntity",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    kg_relations: Mapped[list[KgRelation]] = relationship(
        "KgRelation",
        back_populates="document",
        cascade="all, delete-orphan",
    )
