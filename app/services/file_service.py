from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException, UploadFile, status

from ..core.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE_BYTES


@dataclass(slots=True)
class FileAnalysis:#封装文件分析结果
    file_name: str
    file_size: int
    file_type: str
    total_lines: int
    error_count: int
    warn_count: int
    processing_time_ms: float


class FileService:
    def validate_upload(self, upload: UploadFile) -> str:
        file_name = Path(upload.filename or "").name
        suffix = Path(file_name).suffix.lower().lstrip(".")
        if not file_name or not suffix:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name is required.")
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {suffix}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
            )
        return file_name

    async def save_upload(self, upload: UploadFile, destination: Path) -> tuple[str, int, str]:
        file_name = self.validate_upload(upload)
        raw = await upload.read()
        if len(raw) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the configured size limit of {MAX_UPLOAD_SIZE_BYTES} bytes.",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        file_type = destination.suffix.lower().lstrip(".")
        return file_name, len(raw), file_type

    def analyze_file(self, path: Path) -> FileAnalysis:
        started = perf_counter()
        content = path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        error_count = sum(1 for line in lines if "ERROR" in line)
        warn_count = sum(1 for line in lines if "WARN" in line)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        return FileAnalysis(
            file_name=path.name,
            file_size=path.stat().st_size,
            file_type=path.suffix.lower().lstrip("."),
            total_lines=len(lines),
            error_count=error_count,
            warn_count=warn_count,
            processing_time_ms=elapsed_ms,
        )
