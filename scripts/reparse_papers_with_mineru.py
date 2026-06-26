from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func

from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE, SUBJECT_TYPE_DOCUMENT
from app.core.config import ENABLE_MINERU_PARSER
from app.db.session import SessionLocal
from app.models import Document, DocumentAsset, DocumentEvent, JobRun
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.job_run_service import JobRunService

DONE_STATUSES = {"done", "completed", "parsed"}
ACTIVE_STATUSES = {"pending", "processing", "parsing"}
MINERU_SOURCES = {"mineru_chart", "mineru_image"}
LEGACY_VISUAL_SOURCES = {"extracted_image", "rendered_figure_region", "page_visual_snapshot", "fallback_snapshot"}


@dataclass(slots=True)
class Candidate:
    document: Document
    mineru_assets: int
    legacy_visuals: int
    total_visuals: int


def _source_filter(source: str):
    return DocumentAsset.metadata_json.like(f'%"source": "{source}"%')


def _count_sources(db, document_id: int, sources: set[str]) -> int:
    query = db.query(func.count(DocumentAsset.id)).filter(
        DocumentAsset.document_id == document_id,
        DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
    )
    source_predicates = [_source_filter(source) for source in sources]
    if source_predicates:
        from sqlalchemy import or_

        query = query.filter(or_(*source_predicates))
    return int(query.scalar() or 0)


def _visual_count(db, document_id: int) -> int:
    return int(
        db.query(func.count(DocumentAsset.id))
        .filter(
            DocumentAsset.document_id == document_id,
            DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
        )
        .scalar()
        or 0
    )


def _load_candidates(db, args: argparse.Namespace) -> list[Candidate]:
    query = db.query(Document).filter(
        Document.source_type == "pdf",
        Document.is_deleted.is_(False),
    )
    if args.document_id:
        query = query.filter(Document.id.in_(args.document_id))
    elif not args.include_active:
        query = query.filter(Document.status.notin_(ACTIVE_STATUSES))
    if args.status:
        query = query.filter(Document.status.in_(args.status))

    candidates: list[Candidate] = []
    for document in query.order_by(Document.id.asc()).all():
        mineru_assets = _count_sources(db, document.id, MINERU_SOURCES)
        legacy_visuals = _count_sources(db, document.id, LEGACY_VISUAL_SOURCES)
        total_visuals = _visual_count(db, document.id)
        if mineru_assets and not args.force:
            continue
        if args.legacy_only and not legacy_visuals:
            continue
        candidates.append(
            Candidate(
                document=document,
                mineru_assets=mineru_assets,
                legacy_visuals=legacy_visuals,
                total_visuals=total_visuals,
            )
        )
        if args.limit and len(candidates) >= args.limit:
            break
    return candidates


def _create_reparse_job(db, document: Document) -> JobRun:
    job = JobRunService(db).create_job(
        user_id=document.user_id,
        kind=JOB_KIND_DOCUMENT_PARSE,
        subject_type=SUBJECT_TYPE_DOCUMENT,
        subject_id=document.id,
        document_id=document.id,
        title=f"MinerU reparse {document.original_filename}",
        file_name=document.original_filename,
        file_size=document.file_size,
        file_type=document.source_type,
        input_data={
            "processing_mode": document.processing_mode,
            "processing_strategy": document.processing_strategy,
            "require_mineru": True,
        },
        metadata={
            "job_type": "mineru_reparse",
            "require_mineru": True,
            "source": "scripts/reparse_papers_with_mineru.py",
        },
    )
    db.add(
        DocumentEvent(
            document_id=document.id,
            user_id=document.user_id,
            event_type="mineru_reparse_queued",
            message="已请求使用 MinerU 重新解析本地 PDF。",
            event_metadata=json.dumps({"job_run_id": job.id, "job_id": job.job_id}, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(job)
    return job


def _print_plan(candidates: list[Candidate]) -> None:
    print(f"candidate_count={len(candidates)}")
    for candidate in candidates:
        document = candidate.document
        print(
            json.dumps(
                {
                    "document_id": document.id,
                    "title": document.title,
                    "status": document.status,
                    "processing_strategy": document.processing_strategy,
                    "mineru_assets": candidate.mineru_assets,
                    "legacy_visuals": candidate.legacy_visuals,
                    "total_visuals": candidate.total_visuals,
                },
                ensure_ascii=False,
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reparse uploaded PDF papers with the existing DocumentParsePipeline and require MinerU success. "
            "Dry-run by default; pass --run to replace parse outputs."
        )
    )
    parser.add_argument("--run", action="store_true", help="Actually run synchronous MinerU reparsing. Default only prints candidates.")
    parser.add_argument("--document-id", type=int, action="append", help="Limit to one document id. Repeat for multiple ids.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of candidates to process.")
    parser.add_argument("--force", action="store_true", help="Include documents that already have MinerU visual assets.")
    parser.add_argument("--legacy-only", action="store_true", help="Only include documents that currently have legacy visual assets.")
    parser.add_argument("--include-active", action="store_true", help="Allow documents currently in pending/processing/parsing states.")
    parser.add_argument("--status", action="append", help="Limit by document status. Repeat for multiple statuses.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not ENABLE_MINERU_PARSER:
        print("ENABLE_MINERU_PARSER is disabled.", file=sys.stderr)
        return 2
    if not os.getenv("MINERU_API_KEY", "").strip():
        print("MINERU_API_KEY is not configured.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        candidates = _load_candidates(db, args)
        _print_plan(candidates)
        if not args.run:
            print("dry_run=true")
            return 0

    pipeline = DocumentParsePipeline()
    failures = 0
    for candidate in candidates:
        with SessionLocal() as db:
            document = db.get(Document, candidate.document.id)
            if document is None:
                failures += 1
                print(json.dumps({"document_id": candidate.document.id, "status": "missing"}, ensure_ascii=False))
                continue
            job = _create_reparse_job(db, document)
        result = pipeline.run(
            candidate.document.id,
            job_run_id=job.id,
            job_type="mineru_reparse",
            require_mineru=True,
            preserve_outputs_on_failure=True,
        )
        ok = result.status in DONE_STATUSES and result.processing_strategy == "mineru"
        failures += 0 if ok else 1
        print(
            json.dumps(
                {
                    "document_id": result.id,
                    "status": result.status,
                    "processing_strategy": result.processing_strategy,
                    "ok": ok,
                    "fail_reason": result.fail_reason,
                },
                ensure_ascii=False,
            )
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
