"""
DEPRECATED — Import from ``app.services.extraction_service`` instead.

This module exists only for backward compatibility. All code should use
``ExtractionService`` from ``app.services.extraction_service``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, ExtractionRun
from app.services.extraction_service_v2_enhanced import (
    ExtractionServiceV2Enhanced as _ExtractionServiceV2Enhanced,
)

logger = logging.getLogger(__name__)


class ExtractionServiceV2:
    """
    DEPRECATED wrapper that delegates to ``ExtractionServiceV2Enhanced``.

    Use ``ExtractionService`` from ``app.services.extraction_service`` instead.
    """

    def __init__(self, client: Any = None, **kwargs: Any) -> None:
        self._impl = _ExtractionServiceV2Enhanced(client=client, **kwargs)

    def run_extraction(
        self,
        *,
        db: Session,
        paper: Document,
        user_query: str,
        indicators: list[str] | None = None,
    ) -> ExtractionRun:
        """Delegate to the enhanced implementation.

        The ``indicators`` parameter is accepted for backward compatibility
        but ignored — the enhanced pipeline uses ``user_query`` directly.
        """
        return self._impl.run_extraction(
            db=db,
            paper=paper,
            user_query=user_query,
            mode="standard",
        )
