import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core import config


class FileStorageService:
    """文件存储服务，处理文件的安全存储和获取。"""

    def __init__(self, upload_dir: str | None = None):
        """初始化文件存储服务。

        Args:
            upload_dir: 上传目录，默认从配置读取
        """
        self.upload_dir = Path(upload_dir or config.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def store_file(
        self,
        user_id: int,
        original_filename: str,
        file_content: bytes,
        file_extension: str,
    ) -> tuple[str, str]:
        """安全地存储文件。

        Args:
            user_id: 用户 ID
            original_filename: 原始文件名（用于日志）
            file_content: 文件内容
            file_extension: 文件扩展名（无点）

        Returns:
            tuple: (相对路径, 存储的文件名)

        Raises:
            ValueError: 如果文件扩展名无效
        """
        # 验证扩展名
        if file_extension.lower() not in ("pdf", "md", "txt", "png", "jpg", "jpeg", "webp"):
            raise ValueError(
                f"Unsupported file extension: {file_extension}. "
                f"Only pdf, md, txt, png, jpg, jpeg, webp are allowed."
            )

        # 生成安全的文件名
        stored_filename = f"{uuid4()}.{file_extension.lower()}"

        # 生成按年月分层的目录路径
        now = datetime.now()
        dir_path = self.upload_dir / str(user_id) / f"{now.year:04d}" / f"{now.month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)

        # 完整的文件路径
        file_path = dir_path / stored_filename

        # 写入文件
        try:
            file_path.write_bytes(file_content)
        except IOError as e:
            raise IOError(f"Failed to write file: {e}")

        # 返回相对路径和存储的文件名
        relative_path = file_path.relative_to(self.upload_dir).as_posix()
        return relative_path, stored_filename

    def get_file_path(self, relative_path: str) -> Path:
        """获取文件的完整路径。

        Args:
            relative_path: 相对路径

        Returns:
            Path: 完整的文件路径

        Raises:
            ValueError: 如果路径包含危险的遍历符号
        """
        # 防止路径穿越攻击
        if ".." in relative_path or relative_path.startswith("/"):
            raise ValueError(f"Invalid path: {relative_path}")

        file_path = self.upload_dir / relative_path

        # 验证路径在上传目录内
        try:
            file_path.resolve().relative_to(self.upload_dir.resolve())
        except ValueError:
            raise ValueError(f"Path traversal detected: {relative_path}")

        return file_path

    def read_file(self, relative_path: str) -> bytes:
        """读取文件内容。

        Args:
            relative_path: 相对路径

        Returns:
            bytes: 文件内容

        Raises:
            ValueError: 如果路径无效
            FileNotFoundError: 如果文件不存在
        """
        file_path = self.get_file_path(relative_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        return file_path.read_bytes()

    def delete_file(self, relative_path: str) -> None:
        """删除文件。

        Args:
            relative_path: 相对路径

        Raises:
            ValueError: 如果路径无效
            FileNotFoundError: 如果文件不存在
        """
        file_path = self.get_file_path(relative_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        file_path.unlink()

    def file_exists(self, relative_path: str) -> bool:
        """检查文件是否存在。

        Args:
            relative_path: 相对路径

        Returns:
            bool: 文件是否存在
        """
        try:
            file_path = self.get_file_path(relative_path)
            return file_path.exists()
        except ValueError:
            return False
