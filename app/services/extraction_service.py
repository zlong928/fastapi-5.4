"""Unified extraction service — the single canonical entry point for structured extraction.

This module consolidates ExtractionServiceV2 and ExtractionServiceV2Enhanced.
The enhanced version with parallel processing and user-query-first design
is the canonical implementation.

Usage:
    >>> service = ExtractionService()
    >>> run = service.run_extraction(db=db, paper=paper, user_query=query, mode="standard")
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, ExtractionRun
from app.services.extraction_service_v2_enhanced import (
    ExtractionServiceV2Enhanced,
)

logger = logging.getLogger(__name__)


class ExtractionService:
    """Unified extraction orchestrator.

    Delegates to ``ExtractionServiceV2Enhanced``, which provides:
    - User-query-first system prompt design
    - Parallel figure processing (from old Agent system)
    - Ensure all figures coverage
    - Flexible extraction modes (quick / standard / deep)
    """

    def __init__(self, **kwargs: Any) -> None:
        self._impl = ExtractionServiceV2Enhanced(**kwargs)

    def run_extraction(
        self,
        *,
        db: Session,
        paper: Document,
        user_query: str,
        mode: str = "standard",
    ) -> ExtractionRun:
        """Run the full extraction pipeline.

        Args:
            db: Database session.
            paper: Document record (must have status='done').
            user_query: User's natural language extraction request.
            mode: 'quick' | 'standard' | 'deep'

        Returns:
            Completed ExtractionRun with items and evidence persisted.
        """
        return self._impl.run_extraction(
            db=db,
            paper=paper,
            user_query=user_query,
            mode=mode,
        )
