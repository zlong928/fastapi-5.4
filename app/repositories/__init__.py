"""Repository layer — encapsulates all database access.

Repositories provide a consistent interface for data access,
eliminating scattered ``db.query()`` calls in routes and services.
Each repository wraps a SQLAlchemy ``Session`` and exposes
domain-specific query methods.
"""

from app.repositories.base import BaseRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository

__all__ = [
    "BaseRepository",
    "DocumentRepository",
    "ExtractionRepository",
]
