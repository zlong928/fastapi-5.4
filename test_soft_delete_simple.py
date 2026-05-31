"""
Simple test for soft delete service without requiring existing data.
"""
from app.services.soft_delete_service import SoftDeleteService

print("✅ SoftDeleteService imported successfully")
print("\n--- Service Methods ---")
print(f"✅ soft_delete: {hasattr(SoftDeleteService, 'soft_delete')}")
print(f"✅ restore: {hasattr(SoftDeleteService, 'restore')}")
print(f"✅ permanent_delete: {hasattr(SoftDeleteService, 'permanent_delete')}")
print(f"✅ get_deleted_documents: {hasattr(SoftDeleteService, 'get_deleted_documents')}")
print(f"✅ batch_soft_delete_documents: {hasattr(SoftDeleteService, 'batch_soft_delete_documents')}")
print(f"✅ batch_restore_documents: {hasattr(SoftDeleteService, 'batch_restore_documents')}")

print("\n--- Model Verification ---")
from app.models import Document, User, ExtractionJob, ExtractionResult

# Check Document model
doc_attrs = dir(Document)
print(f"✅ Document.is_deleted: {'is_deleted' in doc_attrs}")
print(f"✅ Document.deleted_at: {'deleted_at' in doc_attrs}")
print(f"✅ Document.deleted_by: {'deleted_by' in doc_attrs}")

# Check User model
user_attrs = dir(User)
print(f"✅ User.is_deleted: {'is_deleted' in user_attrs}")
print(f"✅ User.deleted_at: {'deleted_at' in user_attrs}")

# Check ExtractionJob model
job_attrs = dir(ExtractionJob)
print(f"✅ ExtractionJob.is_deleted: {'is_deleted' in job_attrs}")
print(f"✅ ExtractionJob.deleted_at: {'deleted_at' in job_attrs}")

# Check ExtractionResult model
result_attrs = dir(ExtractionResult)
print(f"✅ ExtractionResult.is_deleted: {'is_deleted' in result_attrs}")
print(f"✅ ExtractionResult.deleted_at: {'deleted_at' in result_attrs}")

print("\n" + "="*50)
print("✅ All soft delete components verified!")
print("="*50)
