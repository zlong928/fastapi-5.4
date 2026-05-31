from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: app_now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        onupdate=lambda: app_now(),
        nullable=False,
    )

    # 软删除字段
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    paper: Mapped[Document] = relationship("Document")
    results: Mapped[list[ExtractionResult]] = relationship(
        "ExtractionResult",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("extraction_jobs.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    figure_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extraction_mode: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: app_now(), nullable=False)

    # 软删除字段
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[ExtractionJob] = relationship("ExtractionJob", back_populates="results")
