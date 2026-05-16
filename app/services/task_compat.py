from __future__ import annotations

from datetime import datetime

from app.models import JobRun
from app.schemas.response import TaskDetail


def job_run_to_task_detail(job_run: JobRun) -> TaskDetail:
    """Map JobRun to the legacy /tasks response shape used by the frontend."""

    return TaskDetail(
        task_id=job_run.job_id,
        task_kind=job_run.kind,
        document_id=job_run.document_id,
        file_name=job_run.file_name or (job_run.document.original_filename if job_run.document else None) or job_run.title or _fallback_name(job_run),
        file_size=job_run.file_size or (job_run.document.file_size if job_run.document else None) or 0,
        file_type=job_run.file_type or (job_run.document.source_type if job_run.document else None) or job_run.subject_type or "job",
        status=job_run.status,
        progress=job_run.progress,
        error=job_run.error_message,
        storage_path=None,
        result_path=_metadata_path(job_run.metadata_json, "result_path"),
        created_at=job_run.created_at,
        updated_at=job_run.updated_at,
        completed_at=job_run.finished_at,
        metadata_json=job_run.metadata_json,
    )


def _metadata_path(metadata_json: str | None, key: str) -> str | None:
    if not metadata_json:
        return None
    import json

    try:
        parsed = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    value = parsed.get(key) if isinstance(parsed, dict) else None
    return value if isinstance(value, str) else None


def _fallback_name(job_run: JobRun) -> str:
    if job_run.document_id is not None:
        return f"Document {job_run.document_id}"
    return job_run.kind
