"""Extraction progress service — progress calculation and phase tracking.

Consolidates the progress/phase logic previously scattered across routes
and read services.
"""

from __future__ import annotations

from app.models import DocumentEvent, ExtractionJob
from app.services.extraction.constants import (
    EXTRACTION_PHASE_EVENT,
    PHASE_BASE_PERCENT,
    PHASE_LABELS,
)
from app.utils.json import json_loads_object_or_empty


def progress_for_job(job: ExtractionJob, event: DocumentEvent | None) -> dict:
    """Calculate extraction progress for a job based on its latest event."""
    metadata = json_loads_object_or_empty(event.event_metadata if event else None)
    phase = str(metadata.get("phase") or ("FINISH" if job.status == "done" else "")).upper()
    if job.status == "pending":
        phase = phase or "PENDING"
        percent = 0
    else:
        percent = _phase_percent(metadata, job)
    status_value = "failed" if job.status == "failed" else str(metadata.get("status") or job.status)
    if job.status == "failed" and not phase:
        phase = "FAILED"
        percent = 0
    phase_label = PHASE_LABELS.get(
        phase,
        "等待开始" if job.status == "pending" else "提取失败" if job.status == "failed" else "处理中",
    )
    return {
        "phase": phase,
        "phase_label": phase_label,
        "status": status_value,
        "percent": percent,
        "message": str(metadata.get("message") or job.error_message or phase_label),
        "updated_at": event.created_at if event else job.updated_at,
        "figures_done": int(metadata.get("figures_done") or 0),
        "figures_total": int(metadata.get("figures_total") or 0),
    }


def _phase_percent(metadata: dict, job: ExtractionJob) -> int:
    """Calculate the percentage progress for a given phase."""
    if job.status == "done":
        return 100
    phase = str(metadata.get("phase") or "").upper()
    if phase == "VISUAL_ANALYSIS":
        base = 45
        total = int(metadata.get("figures_total") or 0)
        done = int(metadata.get("figures_done") or 0)
        if total > 0:
            return min(75, base + round((min(done, total) / total) * 30))
        return base
    return int(PHASE_BASE_PERCENT.get(phase, 0 if job.status == "pending" else 10))
