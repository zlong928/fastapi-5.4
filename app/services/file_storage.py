import re
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath

from app.core import config

ALLOWED_STORED_EXTENSIONS = {"pdf", "md", "markdown", "txt", "docx", "epub", "png", "jpg", "jpeg", "webp"}


class FileStorageService:
    """文件存储服务，处理文件的安全存储和获取。"""

    def __init__(self, upload_dir: str | None = None):
        """初始化文件存储服务。

        Args:
            upload_dir: 上传目录，默认从配置读取
        """
        self.upload_dir = Path(upload_dir or config.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_original_filename(filename: str) -> str:
        normalized = filename.replace("\\", "/")
        raw_name = Path(normalized).name.strip()
        if not raw_name or raw_name in {".", ".."}:
            raise ValueError("File name is invalid.")
        if any(unicodedata.category(character).startswith("C") for character in raw_name):
            raise ValueError("File name contains unsupported control characters.")

        stem, separator, extension = raw_name.rpartition(".")
        if not separator or not stem or not extension:
            raise ValueError("File must have an extension.")
        if not re.fullmatch(r"[A-Za-z0-9]+", extension):
            raise ValueError("File extension is invalid.")

        safe_stem = re.sub(r"[\x00-\x1f<>:\"|?*]+", "", stem)
        safe_stem = re.sub(r"\s+", " ", safe_stem).strip(". ")
        safe_extension = extension.lower()
        if not safe_stem or not safe_extension:
            raise ValueError("File name is invalid after sanitization.")
        return f"{safe_stem[:180]}.{safe_extension}"

    def _validate_magic_bytes(self, content: bytes, extension: str) -> None:
        """验证文件内容的真实魔数是否与扩展名匹配"""
        if extension == "pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF file: magic bytes mismatch.")
        elif extension == "png":
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid PNG file: magic bytes mismatch.")
        elif extension in {"jpg", "jpeg"}:
            if not content.startswith(b"\xff\xd8\xff"):
                raise ValueError("Invalid JPEG file: magic bytes mismatch.")
        elif extension == "webp":
            if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
                raise ValueError("Invalid WebP file: magic bytes mismatch.")
        elif extension in {"txt", "md", "markdown"}:
            if b"\x00" in content:
                raise ValueError(f"Invalid {extension} file: binary content detected.")
        elif extension in {"docx", "epub"}:
            if not content.startswith(b"PK\x03\x04"):
                raise ValueError(f"Invalid {extension} file: zip container magic bytes mismatch.")

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
        normalized_extension = file_extension.lower().lstrip(".")
        if normalized_extension not in ALLOWED_STORED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file extension: {file_extension}. "
                f"Only pdf, md, markdown, txt, docx, epub, png, jpg, jpeg, and webp are allowed."
            )

        # 验证文件真实内容魔数
        self._validate_magic_bytes(file_content, normalized_extension)

        safe_filename = self.safe_original_filename(original_filename)
        safe_stem = Path(safe_filename).stem

        # 生成按年月分层的目录路径
        now = datetime.now()
        dir_path = self.upload_dir / str(user_id) / f"{now.year:04d}" / f"{now.month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)

        try:
            dir_path.resolve().relative_to(self.upload_dir.resolve())
        except ValueError:
            raise ValueError("Upload path must stay inside the configured upload directory.")

        stored_filename = self._available_filename(dir_path, safe_stem, normalized_extension)
        file_path = dir_path / stored_filename

        # 写入文件
        try:
            file_path.write_bytes(file_content)
        except IOError as e:
            raise IOError(f"Failed to write file: {e}")

        # 返回相对路径和存储的文件名
        relative_path = file_path.relative_to(self.upload_dir).as_posix()
        return relative_path, stored_filename

    def _available_filename(self, directory: Path, stem: str, extension: str) -> str:
        candidate = f"{stem}.{extension}"
        counter = 1
        while (directory / candidate).exists():
            candidate = f"{stem}-{counter}.{extension}"
            counter += 1
        return candidate

    def get_file_path(self, relative_path: str) -> Path:
        """获取文件的完整路径。

        Args:
            relative_path: 相对路径

        Returns:
            Path: 完整的文件路径

        Raises:
            ValueError: 如果路径包含危险的遍历符号
        """
        normalized_path = PurePosixPath(relative_path)
        # 防止路径穿越攻击；允许文件名中普通的连续点，例如 foo..bar.txt。
        if (
            "\\" in relative_path
            or normalized_path.is_absolute()
            or not normalized_path.parts
            or any(part in {"", ".", ".."} for part in normalized_path.parts)
        ):
            raise ValueError(f"Invalid path: {relative_path}")

        file_path = self.upload_dir / normalized_path.as_posix()

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
