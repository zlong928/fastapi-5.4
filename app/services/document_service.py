from datetime import datetime
import json
import logging
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE, SUBJECT_TYPE_DOCUMENT
from app.models import Document, DocumentAsset, DocumentEvent, DocumentTag, FileCleanupJob, JobRun, Tag
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.document_processing_modes import select_parser_strategy
from app.services.document_parser import DocumentParserService
from app.services.file_storage import FileStorageService
from app.queue.document_parse_queue import enqueue_document_parse
from app.services.job_run_service import JobRunService

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"
LEGACY_DONE_STATUS = "completed"
DONE_STATUSES = {STATUS_DONE, LEGACY_DONE_STATUS}
ALLOWED_STATUS_TRANSITIONS = {
    STATUS_PENDING: {STATUS_PROCESSING, STATUS_FAILED, STATUS_DELETED},
    STATUS_PROCESSING: {STATUS_DONE, STATUS_FAILED, STATUS_DELETED},
    STATUS_FAILED: {STATUS_PENDING, STATUS_PROCESSING, STATUS_DELETED},
    STATUS_DONE: {STATUS_DELETED},
    LEGACY_DONE_STATUS: {STATUS_DELETED},
    STATUS_DELETED: set(),
}


class DocumentService:
    """文档管理服务，处理所有文档相关的业务逻辑。"""

    def __init__(self, db: Session, file_storage: Optional[FileStorageService] = None):
        """初始化文档服务。

        Args:
            db: SQLAlchemy 数据库会话
            file_storage: 文件存储服务实例
        """
        self.db = db
        self.file_storage = file_storage or FileStorageService()
        self.parser = DocumentParserService()

    def transition_status(self, document: Document, next_status: str, *, reason: str | None = None) -> None:
        """Move a document through the approved lifecycle only."""
        current_status = document.status
        if current_status == next_status:
            return
        allowed_next = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
        if next_status not in allowed_next:
            raise ValueError(f"Invalid document status transition: {current_status} -> {next_status}")
        document.status = next_status
        if next_status == STATUS_FAILED:
            document.error_message = reason
            document.fail_reason = reason
        elif next_status in {STATUS_PENDING, STATUS_PROCESSING, STATUS_DONE}:
            document.error_message = None
            document.fail_reason = None

    def create_document(
        self,
        user_id: int,
        title: str,
        original_filename: str,
        stored_filename: str,
        original_file_path: str,
        file_size: int,
        mime_type: str,
        source_type: str,
        file_hash: str | None = None,
        processing_mode: str = "auto",
    ) -> Document:
        """创建文档记录。

        Args:
            user_id: 用户 ID
            title: 文档标题
            original_filename: 原始文件名
            stored_filename: 存储后的文件名
            original_file_path: 存储的相对路径
            file_size: 文件大小（字节）
            mime_type: MIME 类型
            source_type: 文件类型 (pdf, markdown, txt, image)

        Returns:
            Document: 创建的文档对象
        """
        document = Document(
            user_id=user_id,
            title=title,
            original_filename=original_filename,
            stored_filename=stored_filename,
            original_file_path=original_file_path,
            file_size=file_size,
            file_hash=file_hash,
            mime_type=mime_type,
            source_type=source_type,
            processing_mode=processing_mode,
            processing_strategy=select_parser_strategy(processing_mode, source_type).name,
            status="pending",
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        # 记录上传事件
        self.log_event(document.id, user_id, "uploaded", "文件上传成功")

        return document

    def create_document_with_parse_job(
        self,
        user_id: int,
        title: str,
        original_filename: str,
        stored_filename: str,
        original_file_path: str,
        file_size: int,
        mime_type: str,
        source_type: str,
        file_hash: str | None = None,
        processing_mode: str = "auto",
        job_type: str = "initial_parse",
    ) -> tuple[Document, JobRun]:
        """Create a document, parse job, and audit event in one database transaction."""
        processing_strategy = select_parser_strategy(processing_mode, source_type).name
        document = Document(
            user_id=user_id,
            title=title,
            original_filename=original_filename,
            stored_filename=stored_filename,
            original_file_path=original_file_path,
            file_size=file_size,
            file_hash=file_hash,
            mime_type=mime_type,
            source_type=source_type,
            processing_mode=processing_mode,
            processing_strategy=processing_strategy,
            status="pending",
        )

        try:
            self.db.add(document)
            self.db.flush()

            job_run = JobRunService(self.db).create_job(
                user_id=user_id,
                kind=JOB_KIND_DOCUMENT_PARSE,
                subject_type=SUBJECT_TYPE_DOCUMENT,
                subject_id=document.id,
                document_id=document.id,
                title=f"Parse {original_filename}",
                file_name=original_filename,
                file_size=file_size,
                file_type=source_type,
                input_data={
                    "processing_mode": processing_mode,
                    "detected_source_type": source_type,
                    "processing_strategy": processing_strategy,
                    "retry": job_type == "retry_parse",
                },
                metadata={
                    "job_type": job_type,
                    "processing_mode": processing_mode,
                    "detected_source_type": source_type,
                    "processing_strategy": processing_strategy,
                },
            )

            event = DocumentEvent(
                document_id=document.id,
                user_id=user_id,
                event_type="uploaded",
                message="Document created and parse job scheduled",
                event_metadata=json.dumps(
                    {
                        "job_run_id": job_run.id,
                        "job_id": job_run.job_id,
                        "file_name": original_filename,
                        "job_type": job_type,
                    },
                    ensure_ascii=False,
                ),
            )
            self.db.add(event)

            self.db.commit()
            self.db.refresh(document)
            self.db.refresh(job_run)
            return document, job_run
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to create document, parse job, and event in one transaction")
            raise

    def create_parse_job(self, document_id: int, job_type: str = "initial_parse") -> JobRun:
        document = self.get_document_by_id(document_id)
        if not document:
            raise ValueError(f"Document not found: {document_id}")
        if document.status == "deleted":
            raise ValueError("Cannot parse a deleted document")
        if job_type == "retry_parse" and document.status != STATUS_FAILED:
            raise ValueError("Only failed documents can be retried")
        if document.status in DONE_STATUSES:
            raise ValueError("Completed documents cannot be reprocessed without an explicit failed retry state")
        if document.status == STATUS_FAILED and job_type != "retry_parse":
            raise ValueError("Failed documents can only be processed through retry")
        active_job = self.get_running_parse_job(document_id)
        if active_job is not None:
            raise ValueError(
                f"Document already has an active parse job: {active_job.id}"
            )

        job_run = JobRunService(self.db).create_job(
            user_id=document.user_id,
            kind=JOB_KIND_DOCUMENT_PARSE,
            subject_type=SUBJECT_TYPE_DOCUMENT,
            subject_id=document.id,
            document_id=document.id,
            title=f"Parse {document.original_filename}",
            file_name=document.original_filename,
            file_size=document.file_size,
            file_type=document.source_type,
            input_data={
                "processing_mode": document.processing_mode,
                "detected_source_type": document.source_type,
                "processing_strategy": document.processing_strategy,
                "retry": job_type == "retry_parse",
            },
            metadata={
                "job_type": job_type,
                "processing_mode": document.processing_mode,
                "detected_source_type": document.source_type,
                "processing_strategy": document.processing_strategy,
            },
        )
        self.transition_status(document, STATUS_PENDING)
        self.log_event(
            document.id,
            document.user_id,
            "parse_queued",
            "解析任务已入队",
            metadata={"job_run_id": job_run.id, "job_id": job_run.job_id},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(job_run)
        self.db.refresh(document)
        return job_run

    def enqueue_parse_document(self, document_id: int, job_type: str = "initial_parse") -> tuple[Document, JobRun]:
        job_run = self.create_parse_job(document_id, job_type=job_type)
        document = self.get_document_by_id(document_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        enqueue_document_parse(document.id, job_run.id)
        return document, job_run

    def enqueue_existing_parse_job(self, document: Document, job: JobRun) -> None:
        enqueue_document_parse(document.id, job.id)

    def parse_document(self, document_id: int) -> Document:
        """Backward-compatible synchronous parse entrypoint."""
        job = self.create_parse_job(document_id)
        pipeline = DocumentParsePipeline(file_storage=self.file_storage)
        return pipeline.run(document_id, job_run_id=job.id)

    def retry_parse(self, document_id: int) -> tuple[Document, JobRun]:
        """重新解析文档。

        Args:
            document_id: 文档 ID

        Returns:
            Document: 重新解析后的文档对象

        Raises:
            ValueError: 如果文档不在失败状态
        """
        document = self.get_document_by_id(document_id)
        if not document:
            raise ValueError(f"Document not found: {document_id}")

        if document.status in {STATUS_PENDING, STATUS_PROCESSING}:
            raise ValueError(
                f"Cannot retry parsing while document status is {document.status}"
            )
        if document.status == STATUS_DELETED:
            raise ValueError("Cannot retry parsing a deleted document")
        if document.status not in {STATUS_FAILED}:
            raise ValueError("Only failed documents can be retried")

        # 清空之前的错误信息
        document.error_message = None
        document.fail_reason = None
        document.parsed_text = None
        document.cleaned_text = None
        document.references_text = None
        document.parse_quality_json = None
        document.parsed_at = None
        self.log_event(document.id, document.user_id, "retry", "已请求重新解析", commit=False)
        self.db.commit()

        return self.enqueue_parse_document(document_id, job_type="retry_parse")

    def hard_delete_document(self, document_id: int) -> int:
        """Hard-delete one document row and enqueue its owned files for cleanup.

        Args:
            document_id: 文档 ID

        Returns:
            int: deleted document ID

        Raises:
            ValueError: 如果文档不存在
        """
        document = self.get_document_by_id(document_id)
        if not document:
            raise ValueError(f"Document not found: {document_id}")

        deleted_id = document.id
        file_paths = self._document_relative_file_paths(document)
        try:
            for relative_path in file_paths:
                self.db.add(
                    FileCleanupJob(
                        user_id=document.user_id,
                        file_path=relative_path,
                    )
                )
            self.db.delete(document)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Failed to hard-delete document %s", deleted_id)
            raise

        return deleted_id

    def soft_delete_document(self, document_id: int) -> Document:
        """Compatibility wrapper for legacy callers; deletion is now hard-delete."""
        deleted_id = self.hard_delete_document(document_id)
        deleted = Document(
            id=deleted_id,
            user_id=0,
            title="",
            original_filename="",
            stored_filename="",
            original_file_path="",
            file_size=0,
            mime_type="application/octet-stream",
            source_type="unknown",
            status=STATUS_DELETED,
        )
        return deleted

    def _document_relative_file_paths(self, document: Document) -> list[str]:
        paths: list[str] = []
        if document.original_file_path:
            paths.append(document.original_file_path)
        for asset in document.assets:
            if asset.file_path:
                paths.append(asset.file_path)

        seen: set[str] = set()
        unique_paths: list[str] = []
        for path in paths:
            normalized_path = path.strip()
            if not normalized_path or normalized_path in seen:
                continue
            seen.add(normalized_path)
            unique_paths.append(normalized_path)
        return unique_paths

    def _delete_relative_file(self, relative_path: str, *, document_id: int) -> None:
        if self._relative_file_is_referenced(relative_path):
            logger.info(
                "Skipped physical file delete because another row still references it",
                extra={"document_id": document_id, "relative_path": relative_path},
            )
            return
        try:
            self.file_storage.delete_file(relative_path)
        except FileNotFoundError:
            logger.warning(
                "Physical file already missing during hard delete",
                extra={"document_id": document_id, "relative_path": relative_path},
            )
            self._remove_empty_parent_dirs(relative_path)
        except ValueError:
            logger.exception(
                "Skipped invalid stored file path during hard delete",
                extra={"document_id": document_id, "relative_path": relative_path},
            )
        except OSError:
            logger.exception(
                "Failed to delete physical file after database hard delete",
                extra={"document_id": document_id, "relative_path": relative_path},
            )
        else:
            self._remove_empty_parent_dirs(relative_path)

    def _relative_file_is_referenced(self, relative_path: str) -> bool:
        return (
            self.db.query(Document.id)
            .filter(Document.original_file_path == relative_path)
            .first()
            is not None
            or self.db.query(DocumentAsset.id)
            .filter(DocumentAsset.file_path == relative_path)
            .first()
            is not None
        )

    def _remove_empty_parent_dirs(self, relative_path: str) -> None:
        try:
            parent = self.file_storage.get_file_path(relative_path).parent
            upload_root = self.file_storage.upload_dir.resolve()
        except ValueError:
            return

        while parent.resolve() != upload_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def get_document_by_id(self, document_id: int) -> Optional[Document]:
        """根据 ID 获取文档。

        Args:
            document_id: 文档 ID

        Returns:
            Document: 文档对象，如果不存在则返回 None
        """
        return self.db.query(Document).filter(Document.id == document_id).first()

    def get_user_document_by_file_hash(self, *, user_id: int, file_hash: str) -> Optional[Document]:
        return (
            self.db.query(Document)
            .filter(Document.user_id == user_id, Document.file_hash == file_hash)
            .first()
        )

    def get_latest_parse_job(self, document_id: int) -> Optional[JobRun]:
        return JobRunService(self.db).latest_document_job(document_id, kind=JOB_KIND_DOCUMENT_PARSE)

    def get_running_parse_job(self, document_id: int) -> Optional[JobRun]:
        return JobRunService(self.db).active_document_job(document_id, kind=JOB_KIND_DOCUMENT_PARSE)

    def mark_parse_enqueue_failed(
        self,
        document_id: int,
        job_run_id: int,
        reason: str,
        exc: Exception | None = None,
    ) -> tuple[Document, JobRun]:
        """Persist that the upload succeeded but the external parse queue did not accept the job."""
        document = self.get_document_by_id(document_id)
        job_run = self.db.get(JobRun, job_run_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        if job_run is None or job_run.document_id != document.id:
            raise ValueError(f"JobRun not found for document: {job_run_id}")

        try:
            document.status = STATUS_FAILED
            document.error_message = reason
            document.fail_reason = reason
            error_type = type(exc).__name__ if exc is not None else "enqueue_failed"
            JobRunService(self.db).mark_failed(
                job_run,
                reason,
                metadata={"error_type": error_type, "stage": "parse_enqueue"},
            )
            self.log_event(
                document.id,
                document.user_id,
                "parse_enqueue_failed",
                reason,
                metadata={"job_run_id": job_run.id, "job_id": job_run.job_id, "error_type": error_type},
                commit=False,
            )
            self.db.commit()
            self.db.refresh(document)
            self.db.refresh(job_run)
            return document, job_run
        except Exception:
            self.db.rollback()
            logger.exception("Failed to record parse enqueue failure for document %s", document_id)
            raise

    def get_user_documents(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        exclude_deleted: bool = True,
        keyword: str | None = None,
        tag_id: int | None = None,
        file_type: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[Document], int]:
        """获取用户的文档列表。

        Args:
            user_id: 用户 ID
            skip: 跳过的记录数
            limit: 返回的最大记录数
            exclude_deleted: 是否排除已删除的文档

        Returns:
            tuple: (文档列表, 总数)
        """
        query = self.db.query(Document).filter(Document.user_id == user_id)

        if exclude_deleted:
            query = query.filter(Document.status != "deleted")
        if keyword:
            pattern = f"%{keyword.strip()}%"
            query = query.filter(
                or_(
                    Document.title.ilike(pattern),
                    Document.original_filename.ilike(pattern),
                    Document.parsed_text.ilike(pattern),
                    Document.cleaned_text.ilike(pattern),
                )
            )
        if tag_id is not None:
            query = query.join(DocumentTag, DocumentTag.document_id == Document.id).filter(DocumentTag.tag_id == tag_id)
        if file_type:
            query = query.filter(Document.source_type == file_type)
        if status:
            if status in DONE_STATUSES:
                query = query.filter(Document.status.in_(DONE_STATUSES))
            else:
                query = query.filter(Document.status == status)
        if start_date:
            query = query.filter(Document.uploaded_at >= start_date)
        if end_date:
            query = query.filter(Document.uploaded_at <= end_date)

        total = query.count()
        sort_columns = {
            "created_at": Document.created_at,
            "uploaded_at": Document.uploaded_at,
            "parsed_at": Document.parsed_at,
            "title": Document.title,
            "file_size": Document.file_size,
            "status": Document.status,
            "source_type": Document.source_type,
        }
        sort_column = sort_columns.get(sort_by, Document.created_at)
        ordering = sort_column.asc() if sort_order.lower() == "asc" else sort_column.desc()
        documents = query.order_by(ordering).offset(skip).limit(limit).all()

        return documents, total

    def batch_delete_documents(self, user_id: int, ids: list[int]) -> tuple[list[int], list[int], dict[int, str]]:
        success_ids: list[int] = []
        failed_ids: list[int] = []
        errors: dict[int, str] = {}
        for document_id in ids:
            try:
                document = self.get_document_by_id(document_id)
                if document is None:
                    raise ValueError("Document not found")
                if document.user_id != user_id:
                    raise PermissionError("Not authorized")
                self.hard_delete_document(document_id)
                success_ids.append(document_id)
            except Exception as exc:
                self.db.rollback()
                failed_ids.append(document_id)
                errors[document_id] = str(exc)
        return success_ids, failed_ids, errors

    def batch_tag_documents(self, user_id: int, document_ids: list[int], tag_ids: list[int]) -> int:
        documents = (
            self.db.query(Document)
            .filter(Document.id.in_(document_ids), Document.user_id == user_id, Document.status != STATUS_DELETED)
            .all()
        )
        tags = self.db.query(Tag).filter(Tag.id.in_(tag_ids), Tag.user_id == user_id).all()
        found_document_ids = {document.id for document in documents}
        found_tag_ids = {tag.id for tag in tags}
        missing_documents = sorted(set(document_ids) - found_document_ids)
        missing_tags = sorted(set(tag_ids) - found_tag_ids)
        if missing_documents:
            raise ValueError(f"Documents not found or not owned: {missing_documents}")
        if missing_tags:
            raise ValueError(f"Tags not found or not owned: {missing_tags}")

        existing_pairs = {
            (link.document_id, link.tag_id)
            for link in self.db.query(DocumentTag)
            .filter(DocumentTag.document_id.in_(document_ids), DocumentTag.tag_id.in_(tag_ids))
            .all()
        }
        assigned_count = 0
        try:
            for document in documents:
                for tag_id in tag_ids:
                    if (document.id, tag_id) in existing_pairs:
                        continue
                    self.db.add(DocumentTag(document_id=document.id, tag_id=tag_id))
                    assigned_count += 1
                self.log_event(
                    document.id,
                    user_id,
                    "batch_tag",
                    "批量标签已更新",
                    metadata={"tag_ids": tag_ids},
                    commit=False,
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return assigned_count

    def log_event(
        self,
        document_id: int,
        user_id: int,
        event_type: str,
        message: str,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> DocumentEvent:
        """记录文档事件。

        Args:
            document_id: 文档 ID
            user_id: 用户 ID
            event_type: 事件类型
            message: 事件消息
            metadata: 事件元数据（字典，会转换为 JSON）

        Returns:
            DocumentEvent: 创建的事件对象
        """
        import json

        metadata_str = None
        if metadata:
            try:
                metadata_str = json.dumps(metadata)
            except (TypeError, ValueError):
                metadata_str = None

        event = DocumentEvent(
            document_id=document_id,
            user_id=user_id,
            event_type=event_type,
            message=message,
            event_metadata=metadata_str,
        )
        self.db.add(event)
        if commit:
            self.db.commit()
            self.db.refresh(event)

        return event
