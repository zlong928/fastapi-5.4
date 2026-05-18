"""Create job_runs

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-05-14 00:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


revision: str = "4f5a6b7c8d9e"
down_revision: Union[str, Sequence[str], None] = "3e4f5a6b7c8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table(table_name: str) -> sa.Table:
    return sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())


def _existing_job_ids(session: Session, job_runs: sa.Table) -> set[str]:
    return {row.job_id for row in session.query(job_runs.c.job_id).all()}


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
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

    job_runs = _table("job_runs")
    existing_job_ids = _existing_job_ids(session, job_runs)
    if "tasks" in table_names:
        tasks = _table("tasks")
        task_rows = []
        for task in session.query(*tasks.c).all():
            if task.task_id in existing_job_ids:
                continue
            status = _task_status(task.status)
            task_rows.append(
                {
                    "job_id": task.task_id,
                    "user_id": task.user_id,
                    "kind": "basic_file_processing",
                    "status": status,
                    "progress": _task_progress(task.status),
                    "subject_type": "file",
                    "title": f"Process {task.file_name}",
                    "file_name": task.file_name,
                    "file_size": task.file_size,
                    "file_type": task.file_type,
                    "metadata_json": json.dumps(
                        {
                            "storage_path": task.storage_path,
                            "result_path": task.result_path,
                            "legacy_source": "tasks",
                        }
                    ),
                    "error_message": task.error,
                    "attempt": 0,
                    "max_attempts": 1,
                    "queued_at": task.created_at,
                    "finished_at": task.updated_at if task.status in {"success", "failed"} else None,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "is_visible": True,
                }
            )
            existing_job_ids.add(task.task_id)
        if task_rows:
            op.bulk_insert(job_runs, task_rows)

    if "parse_jobs" in table_names:
        parse_jobs = _table("parse_jobs")
        documents = _table("documents") if "documents" in table_names else None
        documents_by_id = {}
        if documents is not None:
            documents_by_id = {row.id: row for row in session.query(*documents.c).all()}
        parse_job_rows = []
        for parse_job in session.query(*parse_jobs.c).all():
            job_id = f"parse-{parse_job.id}"
            if job_id in existing_job_ids:
                continue
            document = documents_by_id.get(parse_job.document_id)
            metadata = _json_object(parse_job.metadata_json)
            metadata.update({"legacy_parse_job_id": parse_job.id, "legacy_source": "parse_jobs"})
            parse_job_rows.append(
                {
                    "job_id": job_id,
                    "user_id": parse_job.user_id,
                    "kind": "document_parse",
                    "status": _parse_job_status(parse_job.status),
                    "progress": _parse_job_progress(parse_job.status),
                    "subject_type": "document",
                    "subject_id": parse_job.document_id,
                    "document_id": parse_job.document_id,
                    "title": f"Parse {_document_name(document, parse_job.document_id)}",
                    "file_name": getattr(document, "original_filename", None) if document is not None else None,
                    "file_size": getattr(document, "file_size", None) if document is not None else None,
                    "file_type": getattr(document, "source_type", None) if document is not None else None,
                    "input_json": json.dumps(
                        {
                            "processing_mode": getattr(document, "processing_mode", None) if document is not None else None,
                            "processing_strategy": getattr(document, "processing_strategy", None) if document is not None else None,
                            "job_type": parse_job.job_type,
                        }
                    ),
                    "metadata_json": json.dumps(metadata),
                    "error_message": parse_job.error_message,
                    "queued_at": parse_job.created_at,
                    "started_at": parse_job.started_at,
                    "finished_at": parse_job.finished_at,
                    "created_at": parse_job.created_at,
                    "updated_at": parse_job.updated_at or parse_job.created_at,
                    "attempt": 0,
                    "max_attempts": 1,
                    "is_visible": True,
                }
            )
            existing_job_ids.add(job_id)
        if parse_job_rows:
            op.bulk_insert(job_runs, parse_job_rows)


def _task_status(status: str) -> str:
    if status == "processing":
        return "running"
    if status == "success":
        return "succeeded"
    return status


def _task_progress(status: str) -> int:
    if status in {"success", "failed"}:
        return 100
    if status == "processing":
        return 50
    return 0


def _parse_job_status(status: str) -> str:
    return "running" if status == "processing" else status


def _parse_job_progress(status: str) -> int:
    if status in {"succeeded", "failed"}:
        return 100
    if status in {"running", "processing"}:
        return 50
    return 0


def _json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _document_name(document, document_id: int) -> str:
    if document is not None and getattr(document, "original_filename", None):
        return document.original_filename
    return f"document {document_id}"


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
