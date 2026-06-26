"""批量图片提取任务模型"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class BatchExtractionJob(Base):
    """批量图片提取任务"""
    __tablename__ = "batch_extraction_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # 任务状态: pending, processing, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True, nullable=False)

    # 进度信息
    total_images: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_images: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: app_now(), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        onupdate=lambda: app_now(),
        nullable=False,
    )

    # 关系
    document: Mapped[Document] = relationship("Document")
    user: Mapped[User] = relationship("User")
    items: Mapped[list[BatchExtractionItem]] = relationship(
        "BatchExtractionItem",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class BatchExtractionItem(Base):
    """批量提取任务中的单个图片项"""
    __tablename__ = "batch_extraction_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("batch_extraction_jobs.id"), index=True, nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("document_assets.id"), index=True, nullable=False)

    # 状态: pending, processing, success, skipped, failed
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True, nullable=False)

    # 提取结果
    image_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csv_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # 跳过或失败原因
    skip_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: app_now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    job: Mapped[BatchExtractionJob] = relationship("BatchExtractionJob", back_populates="items")
