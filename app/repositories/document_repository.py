"""Document / Paper repository — encapsulates all document-related DB queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, DocumentAsset, DocumentChunk, DocumentEvent, User
from app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class DocumentRepository(BaseRepository[Document]):
    """Repository for Document (paper) operations."""

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Paper lookups ─────────────────────────────────────────────────

    def get_paper_for_user(self, paper_id: int, user: User) -> Document | None:
        """Get a PDF document owned by the given user."""
        paper = self._db.get(Document, paper_id)
        if paper is None or paper.user_id != user.id or paper.source_type != "pdf":
            return None
        return paper

    def get_paper_or_404(self, paper_id: int, user: User) -> Document:
        """Get a paper or raise 404."""
        from fastapi import HTTPException, status
        paper = self.get_paper_for_user(paper_id, user)
        if paper is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found.")
        return paper

    # ── DocumentAssets ────────────────────────────────────────────────

    def get_asset(self, asset_id: int) -> DocumentAsset | None:
        return self._db.get(DocumentAsset, asset_id)

    def get_paper_figure_assets(
        self, paper_id: int, *, include_fallback_snapshots: bool = False
    ) -> list[DocumentAsset]:
        """Get figure/page_snapshot assets for a paper."""
        query = self._db.query(DocumentAsset).filter(
            DocumentAsset.document_id == paper_id,
            DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            DocumentAsset.file_path.isnot(None),
        )
        if not include_fallback_snapshots:
            # Filter out fallback snapshots if needed — caller can post-process
            pass
        return query.all()

    def get_paper_asset_or_404(self, paper_id: int, asset_id: int) -> DocumentAsset:
        """Get an image asset or raise 404."""
        from fastapi import HTTPException, status
        asset = self._db.get(DocumentAsset, asset_id)
        if (
            asset is None
            or asset.document_id != paper_id
            or asset.asset_type not in {"figure", "page_snapshot"}
            or not asset.file_path
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image asset not found.")
        return asset

    def get_assets_by_ids(self, asset_ids: set[int]) -> dict[int, DocumentAsset]:
        """Batch-load assets by their IDs."""
        if not asset_ids:
            return {}
        assets = self._db.query(DocumentAsset).filter(DocumentAsset.id.in_(sorted(asset_ids))).all()
        return {a.id: a for a in assets}

    def get_assets_by_paper_and_type(
        self, paper_id: int, asset_types: tuple[str, ...]
    ) -> list[DocumentAsset]:
        return (
            self._db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == paper_id,
                DocumentAsset.asset_type.in_(asset_types),
            )
            .all()
        )

    def get_figure_and_table_assets(self, paper_id: int) -> list[DocumentAsset]:
        """Get figures and tables for a paper."""
        return self.get_assets_by_paper_and_type(paper_id, ("figure", "page_snapshot", "table"))

    # ── Document Events ───────────────────────────────────────────────

    def get_latest_phase_events(
        self, document_ids: set[int], job_ids: set[int], event_type: str
    ) -> dict[int, DocumentEvent]:
        """Get the latest progress event for each job by parsing event metadata."""
        if not document_ids or not job_ids:
            return {}
        from app.utils.json import json_loads_object_or_empty
        events = (
            self._db.query(DocumentEvent)
            .filter(
                DocumentEvent.document_id.in_(document_ids),
                DocumentEvent.event_type == event_type,
            )
            .order_by(DocumentEvent.created_at.asc(), DocumentEvent.id.asc())
            .all()
        )
        latest: dict[int, DocumentEvent] = {}
        for event in events:
            meta = json_loads_object_or_empty(event.event_metadata)
            job_id = meta.get("job_id") if isinstance(meta, dict) else None
            if isinstance(job_id, int) and job_id in job_ids:
                latest[job_id] = event
        return latest

    def log_event(
        self,
        paper: Document,
        user_id: int,
        event_type: str,
        message: str,
        metadata: dict | None = None,
    ) -> DocumentEvent:
        """Create and persist a document event."""
        import json
        event = DocumentEvent(
            document_id=paper.id,
            user_id=user_id,
            event_type=event_type,
            message=message[:500],
            event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self._db.add(event)
        return event

    def count_active_figures(self, paper_ids: list[int]) -> int:
        """Count figure/page_snapshot assets for a list of paper IDs."""
        if not paper_ids:
            return 0
        return (
            self._db.query(func.count(DocumentAsset.id))
            .filter(
                DocumentAsset.document_id.in_(paper_ids),
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
                DocumentAsset.file_path.isnot(None),
            )
            .scalar()
            or 0
        )

    # ── Chunks ────────────────────────────────────────────────────────

    def get_chunks_for_paper(self, paper_id: int) -> list[DocumentChunk]:
        return (
            self._db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == paper_id)
            .order_by(DocumentChunk.page_start.asc().nullslast(), DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
            .all()
        )
