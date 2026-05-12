from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class DocumentEvent(Base):
    """文档事件日志，记录文档生命周期中的重要事件。"""
    
    __tablename__ = "document_events"

    # 主键和外键
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # 事件信息
    event_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # uploaded, parse_started, parse_succeeded, parse_failed, retry_started, deleted
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    event_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 格式

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # 关系
    document: Mapped[Document] = relationship("Document", back_populates="events")
    user: Mapped[User] = relationship("User")
