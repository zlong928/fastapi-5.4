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
    from app.models.kg_entity import KgEntity


class KgRelation(Base):
    __tablename__ = "kg_relations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id"), index=True, nullable=False)
    subject_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kg_entities.id"), nullable=True)
    object_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kg_entities.id"), nullable=True)
    subject_text: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    predicate: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    object_text: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        nullable=False,
    )

    document: Mapped[Document] = relationship("Document", back_populates="kg_relations")
    chunk: Mapped[DocumentChunk] = relationship("DocumentChunk")
    subject_entity: Mapped[Optional[KgEntity]] = relationship("KgEntity", foreign_keys=[subject_entity_id])
    object_entity: Mapped[Optional[KgEntity]] = relationship("KgEntity", foreign_keys=[object_entity_id])
