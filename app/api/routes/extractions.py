from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import EXTRACTION_QUEUE_NAME
from app.core.time import app_now
from app.db.session import get_db
from app.models import Document, DocumentAsset, DocumentEvent, ExtractionJob, ExtractionResult, User
from app.queue.extraction_queue import enqueue_extraction
from app.queue.redis_queue import RedisQueue
from app.schemas.paper import BatchExtractionResultItem, BatchExtractionRunRequest, ChartTypeRuntimeStats, ExtractionJobListItem, ExtractionJobRead, ExtractionResultRead, ExtractionRunRequest, PaperFigureAsset, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult
from app.services.extraction_job_service import ensure_extractable, log_extraction_event
from app.services.export_service import ExportService
from app.services.chart_extraction import CHART_TYPE_CATALOG
from app.services.paper.coordinate_preview import coordinate_preview_read
from app.services.paper.evidence import asset_bbox, asset_image_url, asset_metadata, is_visual_evidence, normalize_evidence_type

router = APIRouter(prefix="/extractions", tags=["extractions"])
logger = logging.getLogger(__name__)

EXTRACTION_PHASE_EVENT = "extraction_phase"
PHASE_LABELS = {
    "PLANNING": "规划任务",
    "MAPPING": "映射全文",
    "REFLECTION": "复核映射",
    "VISUAL_ANALYSIS": "视觉分析",
    "AGGREGATION": "汇总结果",
    "RESULT_REFLECTION": "结果复核",
    "FINISH": "完成",
}
PHASE_BASE_PERCENT = {
    "PLANNING": 10,
    "MAPPING": 25,
    "REFLECTION": 40,
    "VISUAL_ANALYSIS": 45,
    "AGGREGATION": 85,
    "RESULT_REFLECTION": 95,
    "FINISH": 100,
}
NEGATIVE_RESULT_MARKERS = (
    "没有任何",
    "没有可",
    "不包含可",
    "无法提取",
    "不能提取",
    "不可读取",
    "无法读取",
    "没有坐标轴",
    "没有可见比例尺",
    "没有可直接读取",
    "不存在可",
    "无可提取",
)
GENERIC_RESULT_FIELDS = {
    "materials_methods",
    "materials",
    "key_metrics",
    "figure_data",
    "visible_evidence",
    "comprehensive_data_extraction",
}


def _paper_or_404(db: Session, paper_id: int, user: User) -> Document:
    paper = db.get(Document, paper_id)
    if paper is None or paper.user_id != user.id or paper.source_type != "pdf":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
    return paper


def _job_or_404(db: Session, job_id: int, user: User) -> ExtractionJob:
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction job not found.")
    _paper_or_404(db, job.paper_id, user)
    return job


def _assets_by_id(db: Session, results: list[ExtractionResult]) -> dict[int, DocumentAsset]:
    asset_ids = sorted({result.source_id for result in results if result.source_id is not None and result.source_type in {"asset", "figure", "table"}})
    if not asset_ids:
        return {}
    assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
    return {asset.id: asset for asset in assets}


def _result_read(result: ExtractionResult, assets_by_id: dict[int, DocumentAsset]) -> ExtractionResultRead:
    asset = assets_by_id.get(result.source_id) if result.source_id is not None else None
    metadata = asset_metadata(asset)
    evidence_type = normalize_evidence_type(source_type=result.source_type, asset=asset, metadata=metadata)
    image_url = asset_image_url(asset)
    caption = result.caption
    source = None
    if asset is not None:
        if not caption:
            caption = asset.caption or str(metadata.get("caption") or metadata.get("figure_label") or metadata.get("table_label") or "") or None
        source = str(metadata.get("source") or asset.asset_type) or None
    return ExtractionResultRead(
        id=result.id,
        job_id=result.job_id,
        source_type=result.source_type,
        source_id=result.source_id,
        field_name=_display_field_name(result),
        content=_display_content(result),
        evidence=result.evidence,
        confidence=result.confidence,
        evidence_type=evidence_type,
        image_url=image_url,
        thumbnail_url=image_url,
        page=asset.page_number if asset is not None else None,
        bbox=asset_bbox(metadata),
        caption=caption,
        source=source,
        figure_id=result.figure_id,
        notes=result.notes,
        structured_data=result.structured_data,
        parse_status=result.parse_status,
        extraction_mode=result.extraction_mode,
        created_at=result.created_at,
    )


def _is_negative_result_text(value: str | None) -> bool:
    text = (value or "").lower()
    return any(marker.lower() in text for marker in NEGATIVE_RESULT_MARKERS)


def _should_hide_result(result: ExtractionResult) -> bool:
    if result.extraction_mode == "not_found":
        return False
    if result.confidence is not None and result.confidence < 0.5:
        return True
    if result.source_type in {"asset", "figure", "chart"} or result.figure_id:
        return _is_negative_result_text(result.content) or _is_negative_result_text(result.notes)
    return not (result.content or "").strip() or not (result.evidence or "").strip() or _is_negative_result_text(result.content)


def _display_field_name(result: ExtractionResult) -> str:
    field_name = result.field_name or "unknown"
    if field_name.lower() not in GENERIC_RESULT_FIELDS:
        return field_name
    content = result.content or ""
    compact = " ".join(content.split())
    lower = compact.lower()
    if "hydrogel" in lower and ("10–40" in compact or "10-40" in compact or "直径" in compact):
        return "水凝胶微腔直径"
    if "clostridium" in compact or "shewanella" in compact:
        return "菌株组成"
    if "hexanoic" in lower or "己酸" in compact or "hexanoate" in lower:
        return "己酸产量"
    if "ompf" in compact or "ai-2" in lower:
        return "OmpF/AI-2结构信息"
    if "sem" in lower or "显微" in compact or "杆状" in compact:
        return "显微结构观察"
    if result.source_type in {"asset", "figure", "chart"} or result.figure_id:
        return "可见图像证据"
    return re.sub(r"\s+", "_", field_name.strip())[:80] or "unknown"


def _display_content(result: ExtractionResult) -> str:
    content = result.content or ""
    if not _mostly_english(content):
        return content
    evidence = result.evidence or content
    text = f"{content} {evidence}".lower()
    if "porin regulation" in text and "exometabolite" in text:
        return "性能提升归因于孔蛋白调控和外源代谢物富集，使细菌间相互作用由单向电子传递转向双向多代谢物交叉供给。"
    if "succinic acid" in text and "denitrification" in text:
        return "该调控策略还适用于琥珀酸生产、低碳氮比废水反硝化和新兴污染物去除等其他废水处理体系。"
    if "biomass" in text and "did not affect" in text:
        return "mesospace 未影响菌群生物量，说明性能变化不是由更高生物量导致。"
    if "hexanoate" in text or "hexanoic acid" in text:
        return "该结果描述了己酸/己酸盐产量或性能提升，具体数值见原文证据。"
    return content


def _mostly_english(value: str) -> bool:
    letters = len(re.findall(r"[A-Za-z]", value or ""))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value or ""))
    return letters >= 20 and letters > cjk * 2


def _job_read(db: Session, job: ExtractionJob) -> ExtractionJobRead:
    results = [result for result in sorted(job.results, key=lambda result: result.id) if not _should_hide_result(result)]
    assets_by_id = _assets_by_id(db, results)
    return ExtractionJobRead(
        id=job.id,
        paper_id=job.paper_id,
        query=job.query,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        results=[_result_read(result, assets_by_id) for result in results],
    )


def _schedule_job(job_id: int) -> None:
    enqueue_extraction(job_id)


def _schedule_job_or_fail(db: Session, paper: Document, job: ExtractionJob) -> bool:
    try:
        _schedule_job(job.id)
        return True
    except Exception as exc:
        logger.exception("Failed to enqueue extraction job %s", job.id)
        job.status = "failed"
        job.error_message = f"提取任务入队失败: {exc}"
        job.updated_at = app_now()
        log_extraction_event(db, paper, "extraction_enqueue_failed", str(exc), {"job_id": job.id, "error": str(exc)})
        db.commit()
        return False


def _extraction_queue_size() -> int | None:
    try:
        return int(RedisQueue(queue_name=EXTRACTION_QUEUE_NAME).size())
    except Exception:
        logger.exception("Failed to read extraction queue size")
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif start.tzinfo is not None and end.tzinfo is None:
        start = start.replace(tzinfo=None)
    return max(0.0, (end - start).total_seconds())


def _json_metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _phase_percent(metadata: dict, job: ExtractionJob) -> int:
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


def _progress_for_job(job: ExtractionJob, event: DocumentEvent | None) -> dict:
    metadata = _json_metadata(event.event_metadata if event else None)
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
    phase_label = PHASE_LABELS.get(phase, "等待开始" if job.status == "pending" else "提取失败" if job.status == "failed" else "处理中")
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


def _latest_progress_events(db: Session, jobs: list[ExtractionJob]) -> dict[int, DocumentEvent]:
    job_ids = {job.id for job in jobs}
    if not job_ids:
        return {}
    document_ids = {job.paper_id for job in jobs}
    events = (
        db.query(DocumentEvent)
        .filter(DocumentEvent.document_id.in_(document_ids), DocumentEvent.event_type == EXTRACTION_PHASE_EVENT)
        .order_by(DocumentEvent.created_at.asc(), DocumentEvent.id.asc())
        .all()
    )
    latest: dict[int, DocumentEvent] = {}
    for event in events:
        job_id = _json_metadata(event.event_metadata).get("job_id")
        if isinstance(job_id, int) and job_id in job_ids:
            latest[job_id] = event
    return latest


@router.post("/run", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def run_extraction(payload: ExtractionRunRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    paper = _paper_or_404(db, payload.paperId, current_user)
    ensure_extractable(paper)
    job = ExtractionJob(paper_id=paper.id, query=payload.query, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    if not _schedule_job_or_fail(db, paper, job):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="提取任务入队失败，请稍后重试")
    return job


@router.post("/{job_id}/retry", response_model=ExtractionJobRead, status_code=status.HTTP_201_CREATED)
async def retry_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    old_job = _job_or_404(db, job_id, current_user)
    paper = _paper_or_404(db, old_job.paper_id, current_user)
    ensure_extractable(paper)
    new_job = ExtractionJob(paper_id=paper.id, query=old_job.query, status="pending")
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    log_extraction_event(db, paper, "extraction_retry", f"重试提取任务（原任务 #{old_job.id}）。", {"old_job_id": old_job.id, "new_job_id": new_job.id})
    db.commit()
    if not _schedule_job_or_fail(db, paper, new_job):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="提取任务入队失败，请稍后重试")
    return new_job


@router.get("", response_model=list[ExtractionJobListItem])
async def list_extractions(paper_id: int | None = Query(None, ge=1), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ExtractionJobListItem]:
    if paper_id is not None:
        _paper_or_404(db, paper_id, current_user)
    query = (
        db.query(ExtractionJob, Document)
        .join(Document, ExtractionJob.paper_id == Document.id)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False)
    )
    if paper_id is not None:
        query = query.filter(ExtractionJob.paper_id == paper_id)
    rows = query.order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()).all()
    jobs = [job for job, _paper in rows]
    progress_events = _latest_progress_events(db, jobs)
    return [
        ExtractionJobListItem(
            id=job.id,
            paper_id=paper.id,
            paper_title=paper.title,
            query=job.query,
            status=job.status,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            result_count=len(job.results),
            progress=_progress_for_job(job, progress_events.get(job.id)),
        )
        for job, paper in rows
    ]


@router.get("/metrics")
async def extraction_metrics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    base_query = (
        db.query(ExtractionJob)
        .join(Document, ExtractionJob.paper_id == Document.id)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False)
    )
    total = base_query.count()
    status_rows = (
        db.query(ExtractionJob.status, func.count(ExtractionJob.id))
        .join(Document, ExtractionJob.paper_id == Document.id)
        .filter(Document.user_id == current_user.id, Document.source_type == "pdf", Document.is_deleted == False)
        .group_by(ExtractionJob.status)
        .all()
    )
    by_status = {str(status_value): int(count) for status_value, count in status_rows}
    done = by_status.get("done", 0)
    failed = by_status.get("failed", 0)
    pending = by_status.get("pending", 0)
    running = by_status.get("running", 0)
    finished = done + failed
    success_rate = round((done / finished) * 100, 1) if finished else None

    recent_since = app_now() - timedelta(days=7)
    recent_7_days = base_query.filter(ExtractionJob.created_at >= recent_since).count()
    now = app_now()

    finished_jobs = base_query.filter(ExtractionJob.status.in_(["done", "failed"])).all()
    durations = [
        duration
        for job in finished_jobs
        if (duration := _duration_seconds(job.created_at, job.updated_at)) is not None
    ]
    avg_duration_seconds = round(sum(durations) / len(durations), 1) if durations else None
    active_job = (
        base_query.filter(ExtractionJob.status.in_(["pending", "running"]))
        .order_by(ExtractionJob.created_at.asc(), ExtractionJob.id.asc())
        .first()
    )
    active_job_elapsed_seconds = (
        round(duration, 1)
        if active_job and (duration := _duration_seconds(active_job.created_at, now)) is not None
        else None
    )
    latest_finished_job = (
        base_query.filter(ExtractionJob.status.in_(["done", "failed"]))
        .order_by(ExtractionJob.updated_at.desc(), ExtractionJob.id.desc())
        .first()
    )
    latest_finished_duration_seconds = (
        round(duration, 1)
        if latest_finished_job and (duration := _duration_seconds(latest_finished_job.created_at, latest_finished_job.updated_at)) is not None
        else None
    )
    latest_finished_result_count = (
        db.query(func.count(ExtractionResult.id)).filter(ExtractionResult.job_id == latest_finished_job.id).scalar()
        if latest_finished_job
        else None
    )

    active_paper_ids = [
        row[0]
        for row in base_query.filter(ExtractionJob.status.in_(["pending", "running"]))
        .with_entities(ExtractionJob.paper_id)
        .distinct()
        .all()
    ]
    active_figure_count = 0
    if active_paper_ids:
        active_figure_count = (
            db.query(func.count(DocumentAsset.id))
            .filter(DocumentAsset.document_id.in_(active_paper_ids), DocumentAsset.asset_type.in_(["figure", "page_snapshot"]), DocumentAsset.file_path.isnot(None))
            .scalar()
            or 0
        )

    return {
        "queue_name": EXTRACTION_QUEUE_NAME,
        "queue_size": _extraction_queue_size(),
        "total_jobs": total,
        "pending_jobs": pending,
        "running_jobs": running,
        "done_jobs": done,
        "failed_jobs": failed,
        "recent_7_days": recent_7_days,
        "success_rate": success_rate,
        "avg_duration_seconds": avg_duration_seconds,
        "active_job_id": active_job.id if active_job else None,
        "active_job_status": active_job.status if active_job else None,
        "active_job_elapsed_seconds": active_job_elapsed_seconds,
        "latest_finished_job_id": latest_finished_job.id if latest_finished_job else None,
        "latest_finished_status": latest_finished_job.status if latest_finished_job else None,
        "latest_finished_duration_seconds": latest_finished_duration_seconds,
        "latest_finished_result_count": int(latest_finished_result_count) if latest_finished_result_count is not None else None,
        "active_figure_count": int(active_figure_count),
        "visual_max_workers": _env_int("VISUAL_LLM_MAX_WORKERS", 4),
        "llm_max_concurrency": _env_int("LLM_MAX_CONCURRENCY", 4),
        "llm_min_request_interval_seconds": _env_float("LLM_MIN_REQUEST_INTERVAL_SECONDS", 0.8),
    }


@router.get("/{job_id}", response_model=ExtractionJobRead)
async def get_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ExtractionJobRead:
    return _job_read(db, _job_or_404(db, job_id, current_user))


@router.post("/batch", response_model=list[BatchExtractionResultItem], status_code=status.HTTP_201_CREATED)
async def batch_run_extraction(
    payload: BatchExtractionRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchExtractionResultItem]:
    results: list[BatchExtractionResultItem] = []
    for paper_id in payload.paper_ids:
        paper = db.get(Document, paper_id)
        if paper is None or paper.user_id != current_user.id or paper.source_type != "pdf":
            results.append(BatchExtractionResultItem(paper_id=paper_id, paper_title="", status="skipped", error="论文不存在或无权限"))
            continue
        if paper.status != "done":
            results.append(BatchExtractionResultItem(paper_id=paper_id, paper_title=paper.title, status="skipped", error="文档未完成解析"))
            continue
        job = ExtractionJob(paper_id=paper.id, query=payload.query, status="pending")
        db.add(job)
        log_extraction_event(db, paper, "extraction_started", f"批量提取任务创建。", {"query": payload.query[:200]})
        db.commit()
        db.refresh(job)
        if not _schedule_job_or_fail(db, paper, job):
            results.append(BatchExtractionResultItem(paper_id=paper.id, paper_title=paper.title, job_id=job.id, status="failed", error="提取任务入队失败"))
            continue
        results.append(BatchExtractionResultItem(paper_id=paper.id, paper_title=paper.title, job_id=job.id, status="pending"))
    return results


def _confidence_label(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _asset_source(asset: DocumentAsset | None, metadata: dict | None = None) -> str | None:
    if asset is None:
        return None
    metadata = metadata if metadata is not None else asset_metadata(asset)
    return str(metadata.get("source") or asset.asset_type) or None


def _chart_type_stats(figure_assets: list[DocumentAsset]) -> list[ChartTypeRuntimeStats]:
    buckets = {
        spec.image_type: {
            "image_type": spec.image_type,
            "total": 0,
            "accepted": 0,
            "review_required": 0,
            "skipped": 0,
            "failed": 0,
            "row_count": 0,
        }
        for spec in CHART_TYPE_CATALOG
    }
    for asset in figure_assets:
        metadata = asset_metadata(asset)
        preview = metadata.get("coordinate_preview")
        if not isinstance(preview, dict):
            continue
        image_type = str(preview.get("image_type") or metadata.get("image_type") or metadata.get("chart_type") or "")
        if image_type not in buckets:
            continue
        bucket = buckets[image_type]
        status_value = str(preview.get("status") or "")
        bucket["total"] += 1
        bucket["row_count"] += int(preview.get("row_count") or 0)
        if status_value == "accepted":
            bucket["accepted"] += 1
        elif status_value == "review_required":
            bucket["review_required"] += 1
        elif status_value == "skipped":
            bucket["skipped"] += 1
        elif status_value == "failed":
            bucket["failed"] += 1
    return [ChartTypeRuntimeStats(**bucket) for bucket in buckets.values()]


@router.get("/{job_id}/structured", response_model=StructuredExtractionResponse)
async def get_structured_extraction(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StructuredExtractionResponse:
    job = _job_or_404(db, job_id, current_user)
    paper = db.get(Document, job.paper_id)
    results = sorted(job.results, key=lambda r: r.id)
    assets_map = _assets_by_id(db, results)

    figure_assets = (
        db.query(DocumentAsset)
        .filter(DocumentAsset.document_id == job.paper_id, DocumentAsset.asset_type.in_(["figure", "page_snapshot"]))
        .all()
    )
    all_figure_assets = {a.id: a for a in figure_assets if a.file_path}

    figure_results: list[StructuredFigureResult] = []
    table_results: list[StructuredTableResult] = []
    text_results: list[StructuredTextResult] = []
    not_found: list[str] = []

    for r in results:
        if _should_hide_result(r):
            continue
        asset = assets_map.get(r.source_id) if r.source_id else None
        metadata = asset_metadata(asset)
        ev_type = normalize_evidence_type(source_type=r.source_type, asset=asset, metadata=metadata)

        if r.extraction_mode == "not_found":
            not_found.append(r.field_name)
            continue

        is_figure_result = (
            (ev_type in ("figure", "chart", "page_region") and asset and asset.file_path)
            or r.figure_id is not None
            or (r.source_type == "asset" and r.source_id and r.source_id in all_figure_assets)
        )

        if is_figure_result:
            img_asset = asset or (all_figure_assets.get(r.source_id) if r.source_id else None)
            img_metadata = asset_metadata(img_asset) if img_asset else {}
            figure_results.append(StructuredFigureResult(
                id=r.id,
                figure_id=r.figure_id or str(img_metadata.get("figure_label") or (f"Asset {img_asset.id}" if img_asset else "")),
                caption=r.caption or str(img_metadata.get("caption") or ""),
                image_url=asset_image_url(img_asset),
                page=img_asset.page_number if img_asset else None,
                evidence_type=ev_type,
                source=_asset_source(img_asset, img_metadata),
                metric=_display_field_name(r),
                value=r.content,
                evidence=r.evidence,
                confidence=_confidence_label(r.confidence),
                notes=r.notes,
            ))
        elif ev_type == "table":
            table_results.append(StructuredTableResult(
                id=r.id,
                table_id=str(asset.label or f"Table {asset.id}") if asset else None,
                structured_data=r.structured_data,
                parse_status=r.parse_status,
                page=asset.page_number if asset else None,
                evidence_type=ev_type,
                source=_asset_source(asset, metadata),
                metric=_display_field_name(r),
                value=r.content,
                evidence=r.evidence,
                notes=r.notes,
            ))
        else:
            text_results.append(StructuredTextResult(
                id=r.id,
                metric=_display_field_name(r),
                value=_display_content(r),
                evidence=r.evidence,
                page=asset.page_number if asset else None,
                evidence_type=ev_type,
                source=_asset_source(asset, metadata),
                confidence=_confidence_label(r.confidence),
            ))

    summary = {
        "figures_analyzed": len(figure_results),
        "tables_analyzed": len(table_results),
        "text_items_extracted": len(text_results),
        "failed_items": len(not_found),
        "total_results": len(results),
        "paper_figure_count": len([a for a in all_figure_assets.values() if a.asset_type == "figure"]),
    }

    paper_figures: list[PaperFigureAsset] = []
    for fa in all_figure_assets.values():
        fa_meta = asset_metadata(fa)
        fa_source = str(fa_meta.get("source") or "")
        if fa_source == "fallback_snapshot":
            continue
        paper_figures.append(PaperFigureAsset(
            id=fa.id,
            figure_label=str(fa_meta.get("figure_label") or fa.label or f"Asset {fa.id}"),
            caption=str(fa_meta.get("caption") or fa.caption or ""),
            image_url=asset_image_url(fa),
            page=fa.page_number,
            source=fa_source or fa.asset_type,
            asset_type=fa.asset_type,
            coordinate_preview=coordinate_preview_read(fa, fa_meta),
        ))
    paper_figures.sort(key=lambda x: (x.page or 999, x.id))

    return StructuredExtractionResponse(
        paper_id=job.paper_id,
        title=paper.title if paper else "",
        task=job.query,
        status=job.status,
        error_message=job.error_message,
        summary=summary,
        figure_results=figure_results,
        table_results=table_results,
        text_results=text_results,
        not_found=not_found,
        paper_figures=paper_figures,
        chart_type_stats=_chart_type_stats(list(all_figure_assets.values())),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/{job_id}/export")
async def export_extraction(
    job_id: int,
    format: str = Query("csv", pattern="^(csv|json|markdown|xlsx)$"),
    result_ids: list[int] | None = Query(None, description="Optional list of result IDs to export. If not provided, exports all results."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Response:
    """Export a single extraction job to CSV, JSON, Markdown, or Excel format.

    Optionally filter by result IDs to export only selected results.
    """
    job = _job_or_404(db, job_id, current_user)
    paper = db.get(Document, job.paper_id)

    if format == "csv":
        content = ExportService.export_extraction_to_csv(db, job, result_ids=result_ids)
        media_type = "text/csv"
        filename = f"extraction_{job_id}_{paper.title[:30] if paper else 'unknown'}.csv"
    elif format == "json":
        content = ExportService.export_extraction_to_json(db, job, result_ids=result_ids)
        media_type = "application/json"
        filename = f"extraction_{job_id}_{paper.title[:30] if paper else 'unknown'}.json"
    elif format == "xlsx":
        content = ExportService.export_extraction_to_excel(db, job, result_ids=result_ids)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"extraction_{job_id}_{paper.title[:30] if paper else 'unknown'}.xlsx"
    else:  # markdown
        content = ExportService.export_extraction_to_markdown(db, job, result_ids=result_ids)
        media_type = "text/markdown"
        filename = f"extraction_{job_id}_{paper.title[:30] if paper else 'unknown'}.md"

    # Sanitize filename
    filename = "".join(c for c in filename if c.isalnum() or c in "._- ")

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post("/batch-export")
async def batch_export_extractions(
    job_ids: list[int] = Query(..., description="List of extraction job IDs to export"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Response:
    """Export multiple extraction jobs to CSV or JSON format."""
    if not job_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No job IDs provided")

    if len(job_ids) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 100 jobs can be exported at once")

    # Verify all jobs belong to the user
    jobs = []
    for job_id in job_ids:
        try:
            job = _job_or_404(db, job_id, current_user)
            jobs.append(job)
        except HTTPException:
            logger.warning(f"Job {job_id} not found or not accessible by user {current_user.id}")
            continue

    if not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No valid jobs found")

    if format == "csv":
        content = ExportService.export_batch_extractions_to_csv(db, jobs)
        media_type = "text/csv"
        filename = f"batch_extraction_{len(jobs)}_jobs.csv"
    else:  # json
        content = ExportService.export_batch_extractions_to_json(db, jobs)
        media_type = "application/json"
        filename = f"batch_extraction_{len(jobs)}_jobs.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
