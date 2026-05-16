"""Add document processing MVP tables

Revision ID: 9b1f1d2c3a4b
Revises: 718ab8e21e73
Create Date: 2026-05-12 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b1f1d2c3a4b"
down_revision: Union[str, Sequence[str], None] = "718ab8e21e73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("cleaned_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("parse_quality_json", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("references_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("processing_mode", sa.String(length=50), nullable=False, server_default="auto"))
    op.add_column("documents", sa.Column("processing_strategy", sa.String(length=100), nullable=True))

    op.create_table(
        "parse_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_parse_jobs_document_id"), "parse_jobs", ["document_id"], unique=False)
    op.create_index(op.f("ix_parse_jobs_id"), "parse_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_parse_jobs_status"), "parse_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_parse_jobs_user_id"), "parse_jobs", ["user_id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("parse_job_id", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=50), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["parse_job_id"], ["parse_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_chunks_chunk_type"), "document_chunks", ["chunk_type"], unique=False)
    op.create_index(op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_chunks_id"), "document_chunks", ["id"], unique=False)
    op.create_index(op.f("ix_document_chunks_parse_job_id"), "document_chunks", ["parse_job_id"], unique=False)

    op.create_table(
        "document_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("parse_job_id", sa.Integer(), nullable=True),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["parse_job_id"], ["parse_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_assets_asset_type"), "document_assets", ["asset_type"], unique=False)
    op.create_index(op.f("ix_document_assets_document_id"), "document_assets", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_assets_id"), "document_assets", ["id"], unique=False)
    op.create_index(op.f("ix_document_assets_parse_job_id"), "document_assets", ["parse_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_assets_parse_job_id"), table_name="document_assets")
    op.drop_index(op.f("ix_document_assets_id"), table_name="document_assets")
    op.drop_index(op.f("ix_document_assets_document_id"), table_name="document_assets")
    op.drop_index(op.f("ix_document_assets_asset_type"), table_name="document_assets")
    op.drop_table("document_assets")

    op.drop_index(op.f("ix_document_chunks_parse_job_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_chunk_type"), table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index(op.f("ix_parse_jobs_user_id"), table_name="parse_jobs")
    op.drop_index(op.f("ix_parse_jobs_status"), table_name="parse_jobs")
    op.drop_index(op.f("ix_parse_jobs_id"), table_name="parse_jobs")
    op.drop_index(op.f("ix_parse_jobs_document_id"), table_name="parse_jobs")
    op.drop_table("parse_jobs")

    op.drop_column("documents", "references_text")
    op.drop_column("documents", "parse_quality_json")
    op.drop_column("documents", "cleaned_text")
