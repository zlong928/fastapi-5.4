"""
New extraction API endpoints (v2) — thin layer over repositories and services.

Routes delegate to:
- ``ExtractionRepository`` for data access
- ``ExtractionServiceV2`` for running pipelines
- ``csv_exporter`` for CSV export
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import ExtractionItem, ExtractionRun
from app.repositories.extraction_repository import ExtractionRepository
from app.services.extraction.csv_exporter import export_items_to_csv
from app.services.extraction_service_v2 import ExtractionServiceV2

router = APIRouter(prefix="/extractions-v2", tags=["extractions-v2"])

# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------


@router.post("/run")
def create_extraction_run(
    *,
    db: Session = Depends(get_db),
    paper_id: int = Query(..., description="Document ID of the paper"),
    query: str = Query(..., description="What to extract (indicators)"),
    indicators: str | None = Query(
        None, description="Comma-separated indicator names (optional; parsed from query if omitted)"
    ),
):
    """Create and run a new extraction against a paper."""
    from app.models import Document

    paper = db.get(Document, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.status != "done":
        raise HTTPException(status_code=400, detail="Paper must be fully parsed before extraction")

    service = ExtractionServiceV2()
    run = service.run_extraction(
        db=db,
        paper=paper,
        user_query=query,
        indicators=indicators.split(",") if indicators else None,
    )

    return {
        "id": run.id,
        "paper_id": run.paper_id,
        "status": run.status,
        "phase": run.phase,
        "summary": run.summary,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/runs")
def list_extraction_runs(
    *,
    db: Session = Depends(get_db),
    paper_id: int = Query(..., description="Filter by paper/document ID"),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List extraction runs for a paper."""
    repo = ExtractionRepository(db)
    total, runs = repo.get_runs_for_paper(
        paper_id=paper_id, status=status, limit=limit, offset=offset
    )
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "runs": [
            {
                "id": r.id,
                "paper_id": r.paper_id,
                "query": r.user_query[:200],
                "status": r.status,
                "phase": r.phase,
                "summary": r.summary,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ],
    }


@router.get("/runs/{run_id}")
def get_extraction_run(run_id: int, db: Session = Depends(get_db)):
    """Get a single extraction run with summary."""
    repo = ExtractionRepository(db)
    run = repo.get_run(run_id)
    if run is None or run.is_deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    item_count = repo.get_item_count_for_run(run.id)

    return {
        "id": run.id,
        "paper_id": run.paper_id,
        "query": run.user_query,
        "status": run.status,
        "phase": run.phase,
        "classification": run.classification_json,
        "routing": run.routing_json,
        "summary": run.summary,
        "error_message": run.error_message,
        "error_phase": run.error_phase,
        "item_count": item_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/items")
def list_extraction_items(
    run_id: int,
    *,
    db: Session = Depends(get_db),
    source_type: str | None = Query(None, description="Filter: figure | table | text | fusion"),
    verified: bool | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    """List all items for an extraction run."""
    repo = ExtractionRepository(db)
    run = repo.get_run(run_id)
    if run is None or run.is_deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    total, items = repo.get_items_for_run(
        run_id=run_id, source_type=source_type, verified=verified, limit=limit, offset=offset
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_item_dict(item) for item in items],
    }


@router.get("/items/{item_id}")
def get_extraction_item(item_id: int, db: Session = Depends(get_db)):
    """Get a single extraction item with its evidence."""
    repo = ExtractionRepository(db)
    item = db.get(ExtractionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    evidence = repo.get_evidence_for_item(item.id)

    result = _item_dict(item)
    result["evidence"] = [
        {
            "id": e.id,
            "source_type": e.source_type,
            "source_id": e.source_id,
            "source_label": e.source_label,
            "excerpt": e.excerpt,
            "excerpt_context": e.excerpt_context,
            "page_number": e.page_number,
            "relevance": e.relevance,
        }
        for e in evidence
    ]
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/export/csv")
def export_run_csv(
    run_id: int,
    *,
    db: Session = Depends(get_db),
    include_data_points: bool = Query(True),
):
    """Export an extraction run as CSV with proper physical column headers."""
    repo = ExtractionRepository(db)
    run = repo.get_run(run_id)
    if run is None or run.is_deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    items = repo.get_all_items_for_run(run_id)
    item_dicts = [_item_dict(item) for item in items]
    csv_content = export_items_to_csv(item_dicts, include_data_points=include_data_points)

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=extraction-run-{run_id}.csv"},
    )


# ---------------------------------------------------------------------------
# Item CSV export
# ---------------------------------------------------------------------------


@router.get("/items/{item_id}/csv")
def export_item_csv(
    item_id: int,
    *,
    db: Session = Depends(get_db),
):
    """Export a single extraction item as a coordinate CSV with semantic headers."""
    from app.services.chart_extraction.io import write_coordinate_csv
    from io import StringIO
    import csv

    item = db.get(ExtractionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if not item.data_points_json:
        raise HTTPException(status_code=400, detail="Item has no data points")

    try:
        import json
        points = json.loads(item.data_points_json) if isinstance(item.data_points_json, str) else (item.data_points_json or [])
    except Exception:
        points = []
    if not points:
        raise HTTPException(status_code=400, detail="Item data points are empty")

    # Build rows in write_coordinate_csv format
    rows = []
    for pt in points:
        if not isinstance(pt, dict):
            continue
        rows.append({
            "indicator": item.indicator,
            "series_name": pt.get("series_name", item.series_name or ""),
            "x_value": pt.get("x_value"),
            "x_unit": pt.get("x_unit", item.x_axis_unit or ""),
            "y_value": pt.get("y_value"),
            "y_unit": pt.get("y_unit", item.y_axis_unit or ""),
            "x_axis_label": item.x_axis_label or "",
            "y_axis_label": item.y_axis_label or "",
            "x_scale": item.x_axis_scale or "linear",
            "y_scale": item.y_axis_scale or "linear",
        })

    # Write CSV to string
    output = StringIO()
    from app.services.chart_extraction.io import write_coordinate_csv
    from pathlib import Path
    # Use a temp path; we just want the string output
    import tempfile
    import os
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig')
    try:
        write_coordinate_csv(Path(tmp.name), rows)
        tmp.close()
        with open(tmp.name, encoding='utf-8-sig') as f:
            csv_text = f.read()
    finally:
        os.unlink(tmp.name)

    label = item.figure_label or item.indicator or f"item-{item.id}"
    label = label.replace(" ", "_")
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={label}_coordinates.csv"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item_dict(item: ExtractionItem) -> dict:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "indicator": item.indicator,
        "value_text": item.value_text,
        "value_numeric": item.value_numeric,
        "value_unit": item.value_unit,
        "value_error": item.value_error,
        "source_type": item.source_type,
        "extraction_method": item.extraction_method,
        "figure_label": item.figure_label,
        "x_axis_label": item.x_axis_label,
        "x_axis_unit": item.x_axis_unit,
        "x_axis_scale": item.x_axis_scale,
        "y_axis_label": item.y_axis_label,
        "y_axis_unit": item.y_axis_unit,
        "y_axis_scale": item.y_axis_scale,
        "series_name": item.series_name,
        "series_index": item.series_index,
        "data_points_json": item.data_points_json,
        "confidence": item.confidence,
        "confidence_breakdown": item.confidence_breakdown,
        "verified": item.verified,
        "verification_notes": item.verification_notes,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
