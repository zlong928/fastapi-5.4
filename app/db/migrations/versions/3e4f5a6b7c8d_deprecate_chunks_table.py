"""Deprecate legacy chunks table

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


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
            token_select = f"c.{token_column}" if token_column is not None else "NULL"
            embedding_select = f"c.{embedding_column}" if embedding_column is not None else "NULL"
            op.execute(
                sa.text(
                    f"""
                    INSERT INTO document_chunks (
                        document_id,
                        chunk_index,
                        chunk_type,
                        text,
                        cleaned_text,
                        token_count,
                        embedding_json,
                        created_at
                    )
                    SELECT
                        c.document_id,
                        c.chunk_index,
                        'body',
                        c.{text_column},
                        c.{text_column},
                        {token_select},
                        {embedding_select},
                        COALESCE(c.created_at, CURRENT_TIMESTAMP)
                    FROM chunks c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM document_chunks dc
                        WHERE dc.document_id = c.document_id
                          AND dc.chunk_index = c.chunk_index
                    )
                    """
                )
            )

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
