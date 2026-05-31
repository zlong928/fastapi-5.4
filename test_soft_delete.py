"""
Test script for soft delete functionality.
"""
import sys
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Document, User
from app.services.soft_delete_service import SoftDeleteService


def test_soft_delete():
    """Test soft delete functionality."""
    db: Session = SessionLocal()

    try:
        # Get a test user
        user = db.query(User).first()
        if not user:
            print("❌ No users found in database")
            return False

        print(f"✅ Found test user: {user.username} (id={user.id})")

        # Get a test document
        document = db.query(Document).filter(
            Document.user_id == user.id,
            Document.is_deleted == False
        ).first()

        if not document:
            print("❌ No active documents found for user")
            return False

        print(f"✅ Found test document: {document.title} (id={document.id})")

        # Test 1: Soft delete
        print("\n--- Test 1: Soft Delete ---")
        SoftDeleteService.soft_delete(db, document, deleted_by_user_id=user.id)

        db.refresh(document)
        assert document.is_deleted == True, "Document should be marked as deleted"
        assert document.deleted_at is not None, "deleted_at should be set"
        assert document.deleted_by == user.id, "deleted_by should be set"
        print(f"✅ Document soft deleted successfully")
        print(f"   - is_deleted: {document.is_deleted}")
        print(f"   - deleted_at: {document.deleted_at}")
        print(f"   - deleted_by: {document.deleted_by}")

        # Test 2: Query excludes soft-deleted documents
        print("\n--- Test 2: Query Filtering ---")
        active_docs = db.query(Document).filter(
            Document.user_id == user.id,
            Document.is_deleted == False
        ).count()

        deleted_docs = db.query(Document).filter(
            Document.user_id == user.id,
            Document.is_deleted == True
        ).count()

        print(f"✅ Active documents: {active_docs}")
        print(f"✅ Deleted documents: {deleted_docs}")

        # Test 3: Get deleted documents
        print("\n--- Test 3: Get Deleted Documents ---")
        deleted_list = SoftDeleteService.get_deleted_documents(db, user.id, limit=10)
        print(f"✅ Retrieved {len(deleted_list)} deleted documents")

        # Test 4: Restore
        print("\n--- Test 4: Restore Document ---")
        SoftDeleteService.restore(db, document)

        db.refresh(document)
        assert document.is_deleted == False, "Document should be restored"
        assert document.deleted_at is None, "deleted_at should be cleared"
        assert document.deleted_by is None, "deleted_by should be cleared"
        print(f"✅ Document restored successfully")
        print(f"   - is_deleted: {document.is_deleted}")
        print(f"   - deleted_at: {document.deleted_at}")
        print(f"   - deleted_by: {document.deleted_by}")

        # Test 5: Batch operations
        print("\n--- Test 5: Batch Operations ---")
        test_docs = db.query(Document).filter(
            Document.user_id == user.id,
            Document.is_deleted == False
        ).limit(3).all()

        if len(test_docs) >= 2:
            doc_ids = [doc.id for doc in test_docs[:2]]

            # Batch soft delete
            count = SoftDeleteService.batch_soft_delete_documents(
                db, doc_ids, user.id, user.id
            )
            print(f"✅ Batch soft deleted {count} documents")

            # Batch restore
            count = SoftDeleteService.batch_restore_documents(
                db, doc_ids, user.id
            )
            print(f"✅ Batch restored {count} documents")
        else:
            print("⚠️  Not enough documents for batch test")

        print("\n" + "="*50)
        print("✅ All soft delete tests passed!")
        print("="*50)
        return True

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = test_soft_delete()
    sys.exit(0 if success else 1)
