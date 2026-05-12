"""Add embeddings to document chunks

Revision ID: 1c2d3e4f5a6b
Revises: 9b1f1d2c3a4b
Create Date: 2026-05-12 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c2d3e4f5a6b"
down_revision: Union[str, Sequence[str], None] = "9b1f1d2c3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding_json", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(length=100), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "embedded_at")
    op.drop_column("document_chunks", "embedding_dim")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding_json")
