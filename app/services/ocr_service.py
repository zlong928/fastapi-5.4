from __future__ import annotations

import shutil
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path

from app.core.config import OCR_TIMEOUT_SECONDS


class OcrUnavailableError(RuntimeError):
    pass


class OcrService:
    def ocr_image(self, file_path: Path) -> str:
        if not shutil.which("tesseract"):
            raise OcrUnavailableError("OCR is unavailable: tesseract is not installed.")
        result = subprocess.run(
            ["tesseract", str(file_path), "stdout", "--psm", "6"],
            check=True,
            capture_output=True,
            text=True,
            timeout=OCR_TIMEOUT_SECONDS,
        )
        return result.stdout.strip()

    def ocr_pdf_pages(self, file_path: Path) -> list[str]:
        if not shutil.which("pdftoppm"):
            raise OcrUnavailableError("PDF OCR is unavailable: pdftoppm is not installed.")
        if not shutil.which("tesseract"):
            raise OcrUnavailableError("PDF OCR is unavailable: tesseract is not installed.")

        with TemporaryDirectory() as tmpdir:
            output_prefix = str(Path(tmpdir) / "page")
            subprocess.run(
                ["pdftoppm", "-png", "-r", "200", str(file_path), output_prefix],
                check=True,
                capture_output=True,
                text=True,
                timeout=OCR_TIMEOUT_SECONDS,
            )
            page_images = sorted(Path(tmpdir).glob("page-*.png"))
            return [self.ocr_image(page_image) for page_image in page_images]

    def ocr_pdf_page(self, file_path: Path, page_number: int) -> str:
        if page_number < 1:
            raise ValueError("page_number must be 1-based.")
        if not shutil.which("pdftoppm"):
            raise OcrUnavailableError("PDF OCR is unavailable: pdftoppm is not installed.")
        if not shutil.which("tesseract"):
            raise OcrUnavailableError("PDF OCR is unavailable: tesseract is not installed.")

        with TemporaryDirectory() as tmpdir:
            output_prefix = str(Path(tmpdir) / "page")
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    "200",
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    str(file_path),
                    output_prefix,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=OCR_TIMEOUT_SECONDS,
            )
            page_images = sorted(Path(tmpdir).glob("page-*.png"))
            if not page_images:
                return ""
            return self.ocr_image(page_images[0])
