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


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing("document_chunks", sa.Column("embedding_json", sa.Text(), nullable=True))
    _add_column_if_missing("document_chunks", sa.Column("embedding_model", sa.String(length=100), nullable=True))
    _add_column_if_missing("document_chunks", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    _add_column_if_missing("document_chunks", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "embedded_at")
    op.drop_column("document_chunks", "embedding_dim")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding_json")
