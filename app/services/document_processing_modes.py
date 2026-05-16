from __future__ import annotations

from dataclasses import dataclass

from app.schemas.document import DocumentProcessingMode


TEXT_TYPES = {"txt", "text"}
PDF_TYPES = {"pdf"}
IMAGE_TYPES = {"image"}
MARKDOWN_TYPES = {"markdown", "md"}
BASIC_FILE_TYPES = {"pdf", "txt", "text", "markdown", "md"}


@dataclass(frozen=True, slots=True)
class ProcessingStrategy:
    name: str
    used_ocr: bool = False
    ocr_fallback_used: bool = False
    ocr_first: bool = False
    preserve_structure: bool = False

    def metadata(self) -> dict[str, bool | str]:
        return {
            "processing_strategy": self.name,
            "used_ocr": self.used_ocr,
            "ocr_fallback_used": self.ocr_fallback_used,
            "ocr_first": self.ocr_first,
            "preserve_structure": self.preserve_structure,
        }


def validate_processing_mode_compatibility(
    processing_mode: DocumentProcessingMode,
    detected_source_type: str,
) -> None:
    source_type = detected_source_type.lower()
    if processing_mode == DocumentProcessingMode.AUTO:
        if source_type in PDF_TYPES | TEXT_TYPES | IMAGE_TYPES | MARKDOWN_TYPES:
            return
    elif processing_mode == DocumentProcessingMode.PLAIN_TEXT:
        if source_type in TEXT_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} requires a text file.")
    elif processing_mode == DocumentProcessingMode.PDF_TEXT:
        if source_type in PDF_TYPES:
            return
        if source_type in IMAGE_TYPES:
            raise ValueError(f"Processing mode {processing_mode.value} is not compatible with image files.")
        raise ValueError(f"Processing mode {processing_mode.value} requires a PDF file.")
    elif processing_mode == DocumentProcessingMode.SCANNED_PDF_OCR:
        if source_type in PDF_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} requires a PDF file.")
    elif processing_mode == DocumentProcessingMode.IMAGE_OCR:
        if source_type in IMAGE_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} requires an image file.")
    elif processing_mode == DocumentProcessingMode.MARKDOWN_NOTES:
        if source_type in MARKDOWN_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} requires a Markdown file.")
    elif processing_mode == DocumentProcessingMode.TABLE_IMAGE_OCR:
        if source_type in IMAGE_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} requires an image file.")
    elif processing_mode == DocumentProcessingMode.BASIC_FILE_PARSER:
        if source_type in BASIC_FILE_TYPES:
            return
        raise ValueError(f"Processing mode {processing_mode.value} supports PDF, text, or Markdown files.")

    raise ValueError(f"Processing mode {processing_mode.value} is not compatible with {detected_source_type} files.")


def select_parser_strategy(processing_mode: str | DocumentProcessingMode, detected_source_type: str) -> ProcessingStrategy:
    mode = DocumentProcessingMode(processing_mode)
    source_type = detected_source_type.lower()
    if mode == DocumentProcessingMode.AUTO:
        if source_type == "pdf":
            return ProcessingStrategy(name="pdf_text_with_ocr_fallback")
        if source_type == "image":
            return ProcessingStrategy(name="image_ocr", used_ocr=True)
        if source_type in {"markdown", "md"}:
            return ProcessingStrategy(name="markdown_structure", preserve_structure=True)
        return ProcessingStrategy(name="plain_text")
    if mode == DocumentProcessingMode.PLAIN_TEXT:
        return ProcessingStrategy(name="plain_text")
    if mode == DocumentProcessingMode.PDF_TEXT:
        return ProcessingStrategy(name="pdf_text_with_ocr_fallback")
    if mode == DocumentProcessingMode.SCANNED_PDF_OCR:
        return ProcessingStrategy(name="ocr_first_pdf", used_ocr=True, ocr_first=True)
    if mode == DocumentProcessingMode.IMAGE_OCR:
        return ProcessingStrategy(name="image_ocr", used_ocr=True)
    if mode == DocumentProcessingMode.MARKDOWN_NOTES:
        return ProcessingStrategy(name="markdown_structure", preserve_structure=True)
    if mode == DocumentProcessingMode.TABLE_IMAGE_OCR:
        return ProcessingStrategy(name="table_image_ocr", used_ocr=True)
    if mode == DocumentProcessingMode.BASIC_FILE_PARSER:
        return ProcessingStrategy(name="basic_file_parser")
    return ProcessingStrategy(name="plain_text")
