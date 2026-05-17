"""add vec_document_chunks virtual table

Revision ID: 5a6b7c8d9e0f
Revises: 4f5a6b7c8d9e
Create Date: 2026-05-17 13:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlite_vec
import sqlite3

from alembic import op
from app.core.config import EMBEDDING_DIM

revision: str = "5a6b7c8d9e0f"
down_revision: str | None = "4f5a6b7c8d9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    raw = conn.connection  # type: ignore[union-attr]
    raw.enable_load_extension(True)
    sqlite_vec.load(raw)
    raw.enable_load_extension(False)

    op.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_document_chunks USING vec0("
        f"  chunk_id INTEGER PRIMARY KEY,"
        f"  embedding FLOAT[{EMBEDDING_DIM}]"
        f")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vec_document_chunks")
