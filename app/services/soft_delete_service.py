"""
Soft delete service for managing soft delete operations across models.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Type, TypeVar

from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, ExtractionJob, ExtractionResult, User

logger = logging.getLogger(__name__)

T = TypeVar('T', Document, ExtractionJob, ExtractionResult, User)


class SoftDeleteService:
    """Service for handling soft delete operations."""

    @staticmethod
    def soft_delete(
        db: Session,
        instance: T,
        deleted_by_user_id: int | None = None
    ) -> T:
        """
        Soft delete an instance by setting is_deleted=True and deleted_at timestamp.

        Args:
            db: Database session
            instance: Model instance to soft delete
            deleted_by_user_id: ID of user performing the deletion (for Document model)

        Returns:
            The soft-deleted instance
        """
        instance.is_deleted = True
        instance.deleted_at = app_now()

        # Only Document model has deleted_by field
        if isinstance(instance, Document) and deleted_by_user_id is not None:
            instance.deleted_by = deleted_by_user_id

        db.add(instance)
        db.commit()
        db.refresh(instance)

        logger.info(
            f"Soft deleted {instance.__class__.__name__} id={instance.id} "
            f"by user_id={deleted_by_user_id}"
        )

        return instance

    @staticmethod
    def restore(db: Session, instance: T) -> T:
        """
        Restore a soft-deleted instance.

        Args:
            db: Database session
            instance: Model instance to restore

        Returns:
            The restored instance
        """
        if not instance.is_deleted:
            logger.warning(
                f"Attempted to restore non-deleted {instance.__class__.__name__} id={instance.id}"
            )
            return instance

        instance.is_deleted = False
        instance.deleted_at = None

        # Clear deleted_by for Document model
        if isinstance(instance, Document):
            instance.deleted_by = None

        db.add(instance)
        db.commit()
        db.refresh(instance)

        logger.info(f"Restored {instance.__class__.__name__} id={instance.id}")

        return instance

    @staticmethod
    def permanent_delete(db: Session, instance: T) -> None:
        """
        Permanently delete an instance from the database.
        This is irreversible!

        Args:
            db: Database session
            instance: Model instance to permanently delete
        """
        instance_class = instance.__class__.__name__
        instance_id = instance.id

        db.delete(instance)
        db.commit()

        logger.warning(
            f"PERMANENTLY deleted {instance_class} id={instance_id}"
        )

    @staticmethod
    def get_deleted_documents(
        db: Session,
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list[Document]:
        """
        Get soft-deleted documents for a user.

        Args:
            db: Database session
            user_id: User ID
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of soft-deleted documents
        """
        return (
            db.query(Document)
            .filter(Document.user_id == user_id, Document.is_deleted == True)
            .order_by(Document.deleted_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    @staticmethod
    def get_deleted_extraction_jobs(
        db: Session,
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list[ExtractionJob]:
        """
        Get soft-deleted extraction jobs for a user.

        Args:
            db: Database session
            user_id: User ID
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of soft-deleted extraction jobs
        """
        return (
            db.query(ExtractionJob)
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(Document.user_id == user_id, ExtractionJob.is_deleted == True)
            .order_by(ExtractionJob.deleted_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    @staticmethod
    def count_deleted_documents(db: Session, user_id: int) -> int:
        """Count soft-deleted documents for a user."""
        return (
            db.query(Document)
            .filter(Document.user_id == user_id, Document.is_deleted == True)
            .count()
        )

    @staticmethod
    def count_deleted_extraction_jobs(db: Session, user_id: int) -> int:
        """Count soft-deleted extraction jobs for a user."""
        return (
            db.query(ExtractionJob)
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(Document.user_id == user_id, ExtractionJob.is_deleted == True)
            .count()
        )

    @staticmethod
    def batch_soft_delete_documents(
        db: Session,
        document_ids: list[int],
        user_id: int,
        deleted_by_user_id: int
    ) -> int:
        """
        Batch soft delete multiple documents.

        Args:
            db: Database session
            document_ids: List of document IDs to delete
            user_id: Owner user ID (for validation)
            deleted_by_user_id: ID of user performing the deletion

        Returns:
            Number of documents soft deleted
        """
        now = app_now()

        result = (
            db.query(Document)
            .filter(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
                Document.is_deleted == False
            )
            .update(
                {
                    "is_deleted": True,
                    "deleted_at": now,
                    "deleted_by": deleted_by_user_id
                },
                synchronize_session=False
            )
        )

        db.commit()

        logger.info(
            f"Batch soft deleted {result} documents by user_id={deleted_by_user_id}"
        )

        return result

    @staticmethod
    def batch_restore_documents(
        db: Session,
        document_ids: list[int],
        user_id: int
    ) -> int:
        """
        Batch restore multiple documents.

        Args:
            db: Database session
            document_ids: List of document IDs to restore
            user_id: Owner user ID (for validation)

        Returns:
            Number of documents restored
        """
        result = (
            db.query(Document)
            .filter(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
                Document.is_deleted == True
            )
            .update(
                {
                    "is_deleted": False,
                    "deleted_at": None,
                    "deleted_by": None
                },
                synchronize_session=False
            )
        )

        db.commit()

        logger.info(f"Batch restored {result} documents for user_id={user_id}")

        return result
