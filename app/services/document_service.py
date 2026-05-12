from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Document, DocumentEvent
from app.services.document_parser import DocumentParserService
from app.services.file_storage import FileStorageService


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
            source_type: 文件类型 (pdf, markdown, txt)

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
            status="pending",
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        # 记录上传事件
        self.log_event(document.id, user_id, "uploaded", "文件上传成功")

        return document

    def parse_document(self, document_id: int) -> Document:
        """解析文档。

        Args:
            document_id: 文档 ID

        Returns:
            Document: 解析后的文档对象

        Raises:
            ValueError: 如果文档不存在或状态无效
        """
        document = self.get_document_by_id(document_id)
        if not document:
            raise ValueError(f"Document not found: {document_id}")

        # 更新状态为处理中
        document.status = "processing"
        self.log_event(document.id, document.user_id, "parse_started", "开始解析")
        self.db.commit()

        try:
            # 读取文件
            file_content = self.file_storage.read_file(document.original_file_path)

            # 解析文件
            # 需要临时文件来解析（pyp pdf 需要文件路径）
            from tempfile import NamedTemporaryFile

            with NamedTemporaryFile(suffix=f".{document.source_type}", delete=False) as tmp:
                tmp.write(file_content)
                tmp.flush()
                parsed_text = self.parser.parse(tmp.name, document.source_type)

            # 保存解析结果
            document.parsed_text = parsed_text
            document.status = "parsed"
            document.parsed_at = datetime.now(timezone.utc)
            self.log_event(
                document.id,
                document.user_id,
                "parse_succeeded",
                "解析成功",
                metadata={"char_count": len(parsed_text)},
            )
            self.db.commit()
            self.db.refresh(document)

        except Exception as e:
            # 保存错误信息
            error_message = str(e)
            document.status = "failed"
            document.error_message = error_message
            self.log_event(
                document.id,
                document.user_id,
                "parse_failed",
                f"解析失败：{error_message}",
            )
            self.db.commit()
            self.db.refresh(document)

        return document

    def retry_parse(self, document_id: int) -> Document:
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

        if document.status != "failed":
            raise ValueError(
                f"Cannot retry parsing: document status is {document.status}, "
                f"expected 'failed'"
            )

        # 清空之前的错误信息
        document.error_message = None
        document.parsed_text = None
        self.log_event(document.id, document.user_id, "retry_started", "开始重新解析")
        self.db.commit()

        # 重新解析
        return self.parse_document(document_id)

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
            metadata=metadata_str,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        return event
