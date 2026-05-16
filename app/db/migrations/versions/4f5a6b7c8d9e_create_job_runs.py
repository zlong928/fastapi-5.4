"""Create job_runs

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f5a6b7c8d9e"
down_revision: Union[str, Sequence[str], None] = "3e4f5a6b7c8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "job_runs" not in table_names:
        op.create_table(
            "job_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(length=80), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("subject_type", sa.String(length=80), nullable=True),
            sa.Column("subject_id", sa.Integer(), nullable=True),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("file_name", sa.String(length=255), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("file_type", sa.String(length=80), nullable=True),
            sa.Column("input_json", sa.Text(), nullable=True),
            sa.Column("output_json", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("worker_name", sa.String(length=120), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_job_runs_id"), "job_runs", ["id"], unique=False)
        op.create_index(op.f("ix_job_runs_job_id"), "job_runs", ["job_id"], unique=True)
        op.create_index(op.f("ix_job_runs_user_id"), "job_runs", ["user_id"], unique=False)
        op.create_index(op.f("ix_job_runs_kind"), "job_runs", ["kind"], unique=False)
        op.create_index(op.f("ix_job_runs_status"), "job_runs", ["status"], unique=False)
        op.create_index(op.f("ix_job_runs_document_id"), "job_runs", ["document_id"], unique=False)
        op.create_index("ix_job_runs_user_updated_at", "job_runs", ["user_id", "updated_at"], unique=False)
        op.create_index("ix_job_runs_user_status", "job_runs", ["user_id", "status"], unique=False)
        op.create_index("ix_job_runs_kind_status", "job_runs", ["kind", "status"], unique=False)
        op.create_index("ix_job_runs_subject", "job_runs", ["subject_type", "subject_id"], unique=False)
        op.create_index("ix_job_runs_status_created_at", "job_runs", ["status", "created_at"], unique=False)

    if "tasks" in table_names:
        op.execute(
            sa.text(
                """
                INSERT INTO job_runs (
                    job_id, user_id, kind, status, progress, subject_type, title,
                    file_name, file_size, file_type, metadata_json, error_message,
                    queued_at, finished_at, created_at, updated_at, is_visible
                )
                SELECT
                    t.task_id,
                    t.user_id,
                    'basic_file_processing',
                    CASE t.status
                        WHEN 'processing' THEN 'running'
                        WHEN 'success' THEN 'succeeded'
                        ELSE t.status
                    END,
                    CASE
                        WHEN t.status IN ('success', 'failed') THEN 100
                        WHEN t.status = 'processing' THEN 50
                        ELSE 0
                    END,
                    'file',
                    'Process ' || t.file_name,
                    t.file_name,
                    t.file_size,
                    t.file_type,
                    json_object('storage_path', t.storage_path, 'result_path', t.result_path, 'legacy_source', 'tasks'),
                    t.error,
                    t.created_at,
                    CASE WHEN t.status IN ('success', 'failed') THEN t.updated_at ELSE NULL END,
                    t.created_at,
                    t.updated_at,
                    1
                FROM tasks t
                WHERE NOT EXISTS (
                    SELECT 1 FROM job_runs jr WHERE jr.job_id = t.task_id
                )
                """
            )
        )

    if "parse_jobs" in table_names:
        op.execute(
            sa.text(
                """
                INSERT INTO job_runs (
                    job_id, user_id, kind, status, progress, subject_type, subject_id,
                    document_id, title, file_name, file_size, file_type, input_json,
                    metadata_json, error_message, queued_at, started_at, finished_at,
                    created_at, updated_at, is_visible
                )
                SELECT
                    'parse-' || p.id,
                    p.user_id,
                    'document_parse',
                    CASE p.status
                        WHEN 'processing' THEN 'running'
                        ELSE p.status
                    END,
                    CASE
                        WHEN p.status IN ('succeeded', 'failed') THEN 100
                        WHEN p.status IN ('running', 'processing') THEN 50
                        ELSE 0
                    END,
                    'document',
                    p.document_id,
                    p.document_id,
                    'Parse ' || COALESCE(d.original_filename, 'document ' || p.document_id),
                    d.original_filename,
                    d.file_size,
                    d.source_type,
                    json_object(
                        'processing_mode', d.processing_mode,
                        'processing_strategy', d.processing_strategy,
                        'job_type', p.job_type
                    ),
                    json_patch(COALESCE(p.metadata_json, '{}'), json_object('legacy_parse_job_id', p.id, 'legacy_source', 'parse_jobs')),
                    p.error_message,
                    p.created_at,
                    p.started_at,
                    p.finished_at,
                    p.created_at,
                    COALESCE(p.updated_at, p.created_at),
                    1
                FROM parse_jobs p
                LEFT JOIN documents d ON d.id = p.document_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM job_runs jr WHERE jr.job_id = 'parse-' || p.id
                )
                """
            )
        )


def downgrade() -> None:
    op.drop_index("ix_job_runs_status_created_at", table_name="job_runs")
    op.drop_index("ix_job_runs_subject", table_name="job_runs")
    op.drop_index("ix_job_runs_kind_status", table_name="job_runs")
    op.drop_index("ix_job_runs_user_status", table_name="job_runs")
    op.drop_index("ix_job_runs_user_updated_at", table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_document_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_status"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_kind"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_user_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_job_id"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_id"), table_name="job_runs")
    op.drop_table("job_runs")
