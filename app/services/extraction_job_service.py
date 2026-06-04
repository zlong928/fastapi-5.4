from __future__ import annotations

import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.db.session import SessionLocal
from app.models import Document, DocumentAsset, DocumentEvent, ExtractionJob, ExtractionResult
from app.services.agent import AgentResultMapper, CoordinatorAdapter, PaperDataAdapter
from app.services.paper.evidence import asset_metadata

logger = logging.getLogger(__name__)

EXTRACTION_PHASE_EVENT = "extraction_phase"


def ensure_extractable(paper: Document) -> None:
    if paper.status != "done":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文档解析完成后才能开始提取")


def log_extraction_event(db: Session, paper: Document, event_type: str, message: str, metadata: dict | None = None) -> None:
    db.add(
        DocumentEvent(
            document_id=paper.id,
            user_id=paper.user_id,
            event_type=event_type,
            message=message[:500],
            event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )
    )


def log_extraction_phase_event(db: Session, paper: Document, job: ExtractionJob, event: dict, state: dict) -> None:
    phase = str(event.get("phase") or "").upper()
    status = str(event.get("status") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if phase == "VISUAL_ANALYSIS" and status == "start":
        state["figures_total"] = int(data.get("figure_count") or state.get("figures_total") or 0)
        state["figures_done"] = 0
    elif phase == "VISUAL_ANALYSIS" and status == "figure_done":
        state["figures_done"] = int(state.get("figures_done") or 0) + 1
        if not state.get("figures_total"):
            state["figures_total"] = int(data.get("figure_count") or 0)
    elif phase == "VISUAL_ANALYSIS" and status == "done":
        total = int(state.get("figures_total") or len(data.get("visual_results") or []) or 0)
        state["figures_total"] = total
        state["figures_done"] = total

    metadata = {
        "job_id": job.id,
        "phase": phase,
        "status": status,
        "message": str(event.get("message") or ""),
        "figures_done": int(state.get("figures_done") or 0),
        "figures_total": int(state.get("figures_total") or 0),
    }
    log_extraction_event(db, paper, EXTRACTION_PHASE_EVENT, metadata["message"] or phase, metadata)


def run_extraction_job_by_id(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(ExtractionJob, job_id)
        if job is None:
            logger.warning("Extraction job %s disappeared before it could run", job_id)
            return
        paper = db.get(Document, job.paper_id)
        if paper is None:
            logger.warning("Extraction job %s has no paper %s", job_id, job.paper_id)
            return
        run_extraction_job(db, job, paper)


def run_extraction_job(db: Session, job: ExtractionJob, paper: Document) -> ExtractionJob:
    try:
        ensure_extractable(paper)
        job.status = "running"
        job.error_message = None
        job.updated_at = app_now()
        log_extraction_event(db, paper, "extraction_started", "论文 Agent 提取任务开始。", {"job_id": job.id, "query": job.query[:200]})
        db.commit()
        figures, tables = _load_sources(db, paper.id)
        paper_data = PaperDataAdapter().build(paper=paper, figures=figures, tables=tables)
        db.commit()
        progress_state = {"figures_done": 0, "figures_total": 0}

        def _record_phase(event: dict) -> None:
            if event.get("_emitted_via_callback") and event.get("_recorded_by_service"):
                return
            log_extraction_phase_event(db, paper, job, event, progress_state)
            event["_recorded_by_service"] = True
            db.commit()

        final_results, events = CoordinatorAdapter().run(paper=paper_data, user_query=job.query, on_event=_record_phase)
        _backwrite_visual_findings(db, final_results, figures)
        rows = AgentResultMapper().map_results(job_id=job.id, final_results=final_results, figures=figures, tables=tables)
        db.query(ExtractionResult).filter(ExtractionResult.job_id == job.id).delete(synchronize_session=False)
        for row in rows:
            db.add(row)
        job.status = "done"
        job.error_message = None
        job.updated_at = app_now()
        log_extraction_event(db, paper, "extraction_done", "论文 Agent 提取完成。", {"job_id": job.id, "result_count": len(rows), "event_count": len(events)})
        db.commit()
        db.refresh(job)
        return job
    except Exception as exc:
        logger.exception("Extraction job %s failed", job.id)
        db.rollback()
        job = db.get(ExtractionJob, job.id)
        paper = db.get(Document, paper.id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.updated_at = app_now()
        if paper is not None:
            log_extraction_event(db, paper, "extraction_failed", str(exc), {"job_id": job.id if job else None, "error": str(exc)})
        db.commit()
        if job is None:
            raise
        return job


def _load_sources(db: Session, paper_id: int) -> tuple[list[DocumentAsset], list[DocumentAsset]]:
    figure_candidates = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper_id, DocumentAsset.asset_type.in_(["figure", "page_snapshot"]))
        .order_by(DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    figures = [asset for asset in figure_candidates if _is_analyzable_figure(asset)]
    tables = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == paper_id, DocumentAsset.asset_type == "table")
        .order_by(DocumentAsset.asset_index.asc().nullslast(), DocumentAsset.created_at.asc(), DocumentAsset.id.asc())
        .all()
    )
    return figures, tables


def _is_analyzable_figure(asset: DocumentAsset) -> bool:
    if not asset.file_path:
        return False
    if asset.asset_type == "figure":
        return True
    if asset.asset_type == "page_snapshot":
        metadata = asset_metadata(asset)
        source = metadata.get("source", "")
        if source == "fallback_snapshot":
            return False
        return True
    return False


def _backwrite_visual_findings(db: Session, final_results: dict, figures: list[DocumentAsset]) -> None:
    """Write agent's visual analysis findings back to DocumentAsset.metadata_json."""
    by_figure = final_results.get("by_figure") or {}
    if not by_figure:
        return
    figure_map: dict[str, DocumentAsset] = {}
    for asset in figures:
        metadata = asset_metadata(asset)
        label = str(metadata.get("figure_label") or f"Figure {asset.id}")
        figure_map[f"{label} [asset:{asset.id}]"] = asset
        figure_map[label] = asset
        figure_map[str(asset.id)] = asset

    for figure_id, payload in by_figure.items():
        asset = figure_map.get(str(figure_id))
        if asset is None:
            continue
        metadata = asset_metadata(asset)

        if payload.get("error"):
            metadata["agent_analyzed"] = False
            metadata["agent_analysis_error"] = str(payload["error"])[:300]
            metadata["agent_analysis_status"] = "failed"
            asset.metadata_json = json.dumps(metadata, ensure_ascii=False)
            continue

        if str(payload.get("mode", "")).startswith("fallback"):
            metadata["agent_analyzed"] = True
            metadata["agent_analysis_status"] = "fallback"
            metadata["agent_analysis_mode"] = str(payload.get("mode", ""))
            asset.metadata_json = json.dumps(metadata, ensure_ascii=False)
            continue

        agent_figure_type = payload.get("figure_type")
        if agent_figure_type and agent_figure_type != "unknown":
            metadata["figure_type"] = agent_figure_type
            metadata["figure_type_source"] = "agent_visual"
        description = payload.get("overall_description")
        if description:
            metadata["agent_description"] = str(description)[:500]
        extractions = payload.get("extractions") or []
        precise_values = []
        for ext in extractions:
            if ext.get("data") and ext.get("confidence") in ("high", "medium"):
                precise_values.append({"metric": ext.get("metric"), "data": ext["data"], "confidence": ext["confidence"]})
        if precise_values:
            metadata["precise_values_extracted"] = True
            metadata["agent_extracted_values"] = precise_values[:10]
        metadata["agent_analyzed"] = True
        metadata["agent_analysis_status"] = "success"
        metadata["agent_analysis_model"] = str(final_results.get("model_info", {}).get("model") or "unknown")
        if payload.get("retry_count"):
            metadata["agent_retry_count"] = payload["retry_count"]
        if payload.get("failure_diagnosis"):
            metadata["agent_failure_diagnosis"] = payload["failure_diagnosis"]
        asset.metadata_json = json.dumps(metadata, ensure_ascii=False)
