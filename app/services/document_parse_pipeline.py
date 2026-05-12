from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.models import Document, DocumentAsset, DocumentChunk, ParseJob
from app.services.chunking_service import ChunkingService
from app.services.document_parser import DocumentParserService
from app.services.file_storage import FileStorageService
from app.services.ocr_service import OcrService
from app.services.text_cleaner import TextCleaner


class DocumentParsePipeline:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        file_storage: FileStorageService | None = None,
        ocr_service: OcrService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.file_storage = file_storage or FileStorageService()
        self.ocr_service = ocr_service or OcrService()
        self.parser = DocumentParserService()
        self.cleaner = TextCleaner()
        self.chunker = ChunkingService()

    def run(self, document_id: int, job_type: str = "initial_parse") -> Document:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")

            job = ParseJob(
                document_id=document.id,
                user_id=document.user_id,
                status="processing",
                job_type=job_type,
                started_at=datetime.now(timezone.utc),
            )
            document.status = "processing"
            document.error_message = None
            db.add(job)
            db.commit()
            db.refresh(job)

        try:
            parsed_pages, ocr_assets = self._extract_pages(document_id)
            cleaned = self.cleaner.clean_pages(parsed_pages)
            chunks = self.chunker.chunk_document(
                cleaned_text=cleaned.cleaned_text,
                captions=cleaned.captions,
                references_text=cleaned.references_text,
            )
            if ocr_assets:
                chunks = []
                for asset in ocr_assets:
                    text = asset["ocr_text"]
                    chunks.append(
                        self.chunker.build_ocr_chunk(
                            text=text,
                            chunk_index=len(chunks),
                            page_number=asset.get("page_number"),
                        )
                    )

            with self.session_factory() as db:
                document = db.get(Document, document_id)
                job = db.get(ParseJob, job.id)
                if document is None or job is None:
                    raise ValueError(f"Document not found: {document_id}")

                db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
                db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document.id))
                document.parsed_text = cleaned.raw_text
                document.cleaned_text = cleaned.cleaned_text
                document.references_text = cleaned.references_text
                document.parse_quality_json = json.dumps(cleaned.quality, ensure_ascii=False)
                document.status = "parsed"
                document.parsed_at = datetime.now(timezone.utc)
                document.error_message = None

                for chunk in chunks:
                    db.add(
                        DocumentChunk(
                            document_id=document.id,
                            parse_job_id=job.id,
                            chunk_index=chunk.chunk_index,
                            chunk_type=chunk.chunk_type,
                            text=chunk.text,
                            cleaned_text=chunk.cleaned_text,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                            token_count=len(chunk.cleaned_text.split()),
                        )
                    )
                for asset in ocr_assets:
                    db.add(
                        DocumentAsset(
                            document_id=document.id,
                            parse_job_id=job.id,
                            asset_type=asset["asset_type"],
                            page_number=asset.get("page_number"),
                            file_path=asset.get("file_path"),
                            mime_type=asset.get("mime_type"),
                            ocr_text=asset.get("ocr_text"),
                        )
                    )

                job.status = "succeeded"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(document)
                return document

        except Exception as exc:
            with self.session_factory() as db:
                document = db.get(Document, document_id)
                job = db.get(ParseJob, job.id)
                if document is not None:
                    document.status = "failed"
                    document.error_message = str(exc)
                if job is not None:
                    job.status = "failed"
                    job.error_message = str(exc)
                    job.finished_at = datetime.now(timezone.utc)
                db.commit()
            raise

    def _extract_pages(self, document_id: int) -> tuple[list[str], list[dict[str, str | int | None]]]:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            file_path = self.file_storage.get_file_path(document.original_file_path)
            source_type = document.source_type
            mime_type = document.mime_type
            relative_path = document.original_file_path

        if source_type == "pdf":
            pages = self.parser.parse_pdf_pages(file_path)
            if any(page.strip() for page in pages):
                return pages, []
            ocr_pages = self.ocr_service.ocr_pdf_pages(file_path)
            return ocr_pages, [
                {
                    "asset_type": "pdf_page_ocr",
                    "page_number": index + 1,
                    "file_path": relative_path,
                    "mime_type": mime_type,
                    "ocr_text": page_text,
                }
                for index, page_text in enumerate(ocr_pages)
            ]
        if source_type == "image":
            text = self.ocr_service.ocr_image(file_path)
            return [text], [
                {
                    "asset_type": "uploaded_image",
                    "page_number": None,
                    "file_path": relative_path,
                    "mime_type": mime_type,
                    "ocr_text": text,
                }
            ]
        return [self.parser.parse(file_path, source_type)], []
