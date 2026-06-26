"""Base repository with common CRUD operations."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import func
from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository providing common database operations.

    All domain-specific repositories should inherit from this class.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    @property
    def db(self) -> Session:
        return self._db

    # ── CRUD ──────────────────────────────────────────────────────────

    def get(self, model_class: type[T], ident: Any) -> T | None:
        """Get a single record by primary key."""
        return self._db.get(model_class, ident)

    def get_or_404(self, model_class: type[T], ident: Any, detail: str = "Not found") -> T:
        """Get a record by primary key or raise an exception."""
        instance = self._db.get(model_class, ident)
        if instance is None:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return instance

    def list_all(self, model_class: type[T], **filters: Any) -> list[T]:
        """List records with optional equality filters."""
        query = self._db.query(model_class)
        for attr, value in filters.items():
            if value is not None:
                query = query.filter(getattr(model_class, attr) == value)
        return query.all()

    def count(self, model_class: type[T], **filters: Any) -> int:
        """Count records with optional equality filters."""
        query = self._db.query(func.count(model_class.id))
        for attr, value in filters.items():
            if value is not None:
                query = query.filter(getattr(model_class, attr) == value)
        return query.scalar() or 0

    def add(self, instance: T) -> T:
        """Add a new record and flush."""
        self._db.add(instance)
        self._db.flush()
        return instance

    def delete(self, instance: T) -> None:
        """Delete a record."""
        self._db.delete(instance)

    def flush(self) -> None:
        """Flush pending changes."""
        self._db.flush()

    def commit(self) -> None:
        """Commit the current transaction."""
        self._db.commit()
