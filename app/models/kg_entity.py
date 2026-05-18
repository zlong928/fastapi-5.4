from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk


class KgEntity(Base):
    __tablename__ = "kg_entities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    chunk_id: Mapped[Optional[int]] = mapped_column(ForeignKey("document_chunks.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), default="term", index=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship("Document", back_populates="kg_entities")
    chunk: Mapped[Optional[DocumentChunk]] = relationship("DocumentChunk")
