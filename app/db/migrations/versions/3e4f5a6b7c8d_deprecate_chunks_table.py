"""Deprecate legacy chunks table

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-05-13 00:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


revision: str = "3e4f5a6b7c8d"
down_revision: Union[str, Sequence[str], None] = "2d3e4f5a6b7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "chunks" not in table_names:
        return

    if "document_chunks" in table_names:
        chunk_columns = {column["name"] for column in inspector.get_columns("chunks")}
        text_column = "chunk_text" if "chunk_text" in chunk_columns else "content" if "content" in chunk_columns else None
        embedding_column = "embedding" if "embedding" in chunk_columns else None
        token_column = "token_count" if "token_count" in chunk_columns else None

        if text_column is not None:
            session = Session(bind=bind)
            chunks = sa.Table("chunks", sa.MetaData(), autoload_with=bind)
            document_chunks = sa.Table("document_chunks", sa.MetaData(), autoload_with=bind)
            existing_pairs = {
                (row.document_id, row.chunk_index)
                for row in session.query(document_chunks.c.document_id, document_chunks.c.chunk_index).all()
            }
            rows_to_insert = []
            for chunk in session.query(*chunks.c).all():
                if (chunk.document_id, chunk.chunk_index) in existing_pairs:
                    continue
                rows_to_insert.append(
                    {
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        "chunk_type": "body",
                        "text": getattr(chunk, text_column),
                        "cleaned_text": getattr(chunk, text_column),
                        "token_count": getattr(chunk, token_column) if token_column is not None else None,
                        "embedding_json": (
                            getattr(chunk, embedding_column)
                            if embedding_column is not None and isinstance(getattr(chunk, embedding_column), str)
                            else None
                        ),
                        "created_at": getattr(chunk, "created_at", None) or datetime.now(timezone.utc),
                    }
                )
            if rows_to_insert:
                op.bulk_insert(document_chunks, rows_to_insert)

    index_names = {index["name"] for index in inspector.get_indexes("chunks")}
    if op.f("ix_chunks_document_id") in index_names:
        op.drop_index(op.f("ix_chunks_document_id"), table_name="chunks")
    op.drop_table("chunks")


def downgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"], unique=False)
