from datetime import datetime, timezone
import json
import logging
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE, SUBJECT_TYPE_DOCUMENT
from app.models import Document, DocumentEvent, JobRun
from app.services.document_parse_pipeline import DocumentParsePipeline
from app.services.document_processing_modes import select_parser_strategy
from app.services.document_parser import DocumentParserService
from app.services.file_storage import FileStorageService
from app.queue.document_parse_queue import enqueue_document_parse
from app.services.job_run_service import JobRunService

logger = logging.getLogger(__name__)


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
            mime_type=mime_type,
            source_type=source_type,
            processing_mode=processing_mode,
            processing_strategy=select_parser_strategy(processing_mode, source_type).name,
            status="uploaded",
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
            mime_type=mime_type,
            source_type=source_type,
            processing_mode=processing_mode,
            processing_strategy=processing_strategy,
            status="queued",
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
        document.status = "queued"
        document.error_message = None
        self.log_event(
            document.id,
            document.user_id,
            "queued",
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

        if document.status in {"queued", "processing"}:
            raise ValueError(
                f"Cannot retry parsing while document status is {document.status}"
            )
        if document.status == "deleted":
            raise ValueError("Cannot retry parsing a deleted document")

        # 清空之前的错误信息
        document.error_message = None
        document.parsed_text = None
        document.cleaned_text = None
        document.references_text = None
        document.parse_quality_json = None
        document.parsed_at = None
        self.log_event(document.id, document.user_id, "retry_requested", "已请求重新解析", commit=False)
        self.db.commit()

        return self.enqueue_parse_document(document_id, job_type="retry_parse")

    def soft_delete_document(self, document_id: int) -> Document:
        """软删除文档。

        Args:
            document_id: 文档 ID

        Returns:
            Document: 已删除的文档对象

        Raises:
            ValueError: 如果文档不存在
        """
        document = self.get_document_by_id(document_id)
        if not document:
            raise ValueError(f"Document not found: {document_id}")

        document.status = "deleted"
        document.error_message = None
        self.log_event(document.id, document.user_id, "deleted", "文档已删除")
        self.db.commit()
        self.db.refresh(document)

        return document

    def get_document_by_id(self, document_id: int) -> Optional[Document]:
        """根据 ID 获取文档。

        Args:
            document_id: 文档 ID

        Returns:
            Document: 文档对象，如果不存在则返回 None
        """
        return self.db.query(Document).filter(Document.id == document_id).first()

    def get_latest_parse_job(self, document_id: int) -> Optional[JobRun]:
        return JobRunService(self.db).latest_document_job(document_id, kind=JOB_KIND_DOCUMENT_PARSE)

    def get_running_parse_job(self, document_id: int) -> Optional[JobRun]:
        return JobRunService(self.db).active_document_job(document_id, kind=JOB_KIND_DOCUMENT_PARSE)

    def get_user_documents(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        exclude_deleted: bool = True,
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

        total = query.count()
        documents = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

        return documents, total

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
