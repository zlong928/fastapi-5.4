from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants.jobs import JOB_STATUS_QUEUED
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class JobRun(Base):
    """One execution of an asynchronous background job.

    JobRun stores lifecycle state, progress, timing, input/output summaries,
    and errors. It should not store large business outputs such as full
    extracted text, PDF files, or translated documents; those belong to
    domain tables such as Document, DocumentChunk, or future translation tables.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_user_updated_at", "user_id", "updated_at"),
        Index("ix_job_runs_user_status", "user_id", "status"),
        Index("ix_job_runs_kind_status", "kind", "status"),
        Index("ix_job_runs_subject", "subject_type", "subject_id"),
        Index("ix_job_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False, default=lambda: f"job_{uuid4().hex}")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=JOB_STATUS_QUEUED, index=True, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subject_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    subject_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"), index=True, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    input_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    worker_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="job_runs")
    document: Mapped[Optional[Document]] = relationship("Document", back_populates="job_runs")
