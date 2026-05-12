from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base):
    """文本块模型，为未来 RAG / AI 问答预留。当前只保存结构，不填充向量。"""
    
    __tablename__ = "chunks"

    # 主键和外键
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)

    # 块信息
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    # 向量化信息（未来使用）
    embedding: Mapped[Optional[bytes]] = mapped_column(nullable=True)  # 序列化的向量
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 关系
    document: Mapped[Document] = relationship("Document", back_populates="chunks")
