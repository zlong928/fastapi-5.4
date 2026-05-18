from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base


FILE_CLEANUP_STATUS_PENDING = "pending"
FILE_CLEANUP_STATUS_PROCESSING = "processing"
FILE_CLEANUP_STATUS_DONE = "done"
FILE_CLEANUP_STATUS_FAILED = "failed"
FILE_CLEANUP_REASON_DOCUMENT_DELETED = "document_deleted"


class FileCleanupJob(Base):
    __tablename__ = "file_cleanup_jobs"
    __table_args__ = (
        Index("ix_file_cleanup_jobs_status_next_run_at", "status", "next_run_at"),
        Index("ix_file_cleanup_jobs_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), default=FILE_CLEANUP_REASON_DOCUMENT_DELETED, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=FILE_CLEANUP_STATUS_PENDING, index=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        nullable=False,
        index=True,
    )
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

    user = relationship("User")
