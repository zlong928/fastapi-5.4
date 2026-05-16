from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE, SUBJECT_TYPE_DOCUMENT
from app.models import Document, DocumentAsset, DocumentChunk, DocumentEvent, JobRun
from app.services.chunking_service import ChunkingService
from app.services.document_embedding_service import EmbeddingProvider, DocumentEmbeddingService
from app.services.document_kg_service import DocumentKgService
from app.services.document_parser import DocumentParserService, ParsedDocument, ParsedElement, ParsedPage
from app.services.document_processing_modes import ProcessingStrategy, select_parser_strategy
from app.services.job_run_service import JobRunService
from app.services.file_storage import FileStorageService
from app.services.ocr_service import OcrService
from app.services.text_cleaner import TextCleaner


class DocumentParsePipeline:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        file_storage: FileStorageService | None = None,
        ocr_service: OcrService | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.file_storage = file_storage or FileStorageService()
        self.ocr_service = ocr_service or OcrService()
        self.embedding_provider = embedding_provider
        self.parser = DocumentParserService()
        self.cleaner = TextCleaner()
        self.chunker = ChunkingService()

    def run(
        self,
        document_id: int,
        job_run_id: int | None = None,
        job_type: str = "initial_parse",
        parse_job_id: int | None = None,
    ) -> Document:
        if job_run_id is None and parse_job_id is not None:
            job_run_id = parse_job_id
        job_id: int | None = job_run_id
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")

            job_service = JobRunService(db)
            if job_run_id is None:
                job_run = job_service.create_job(
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
                        "processing_strategy": document.processing_strategy,
                        "retry": job_type == "retry_parse",
                    },
                    metadata={"job_type": job_type},
                )
                job_id = job_run.id
            else:
                job_run = db.get(JobRun, job_run_id)
                if job_run is None or job_run.document_id != document.id:
                    raise ValueError(f"JobRun not found for document: {job_run_id}")
            if job_run.status == "succeeded":
                return document
            if document.status == "deleted":
                job_service.mark_failed(job_run, "Document was deleted before parsing.")
                self._log_event(
                    db,
                    document,
                    "parse_skipped",
                    "文档已删除，跳过解析任务",
                    metadata={"job_run_id": job_run.id, "job_id": job_run.job_id},
                )
                db.commit()
                return document

            strategy = self.select_parser_strategy(document.processing_mode, document.source_type)
            document.processing_strategy = strategy.name
            job_service.mark_running(job_run, worker_name="document_parse_pipeline")
            job_service.update_progress(job_run, 10, metadata=self._processing_metadata(document, strategy))
            document.status = "processing"
            document.error_message = None
            self._log_event(
                db,
                document,
                "parse_started",
                "开始解析",
                metadata={"job_run_id": job_run.id, "job_id": job_run.job_id},
            )
            db.commit()
            db.refresh(job_run)

        try:
            parsed_document, ocr_assets, strategy_metadata = self._extract_document(document_id)
            cleaned = self.cleaner.clean_pages(parsed_document.text_pages)
            if parsed_document.source_type == "pdf":
                chunks = self._chunk_parsed_pdf(parsed_document)
            else:
                chunks = self.chunker.chunk_document(
                    cleaned_text=cleaned.cleaned_text,
                    captions=cleaned.captions,
                    references_text=cleaned.references_text,
                )

            with self.session_factory() as db:
                document = db.get(Document, document_id)
                job_run = db.get(JobRun, job_id)
                if document is None or job_run is None:
                    raise ValueError(f"Document not found: {document_id}")
                if document.status == "deleted":
                    return document
                job_service = JobRunService(db)
                job_service.update_progress(job_run, 70, metadata={"stage": "saving_parse_outputs"})

                db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
                db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document.id))
                document.parsed_text = cleaned.raw_text
                document.cleaned_text = cleaned.cleaned_text
                document.references_text = cleaned.references_text
                quality = {**cleaned.quality, **strategy_metadata, **self._quality_metadata(parsed_document)}
                document.processing_strategy = str(strategy_metadata["processing_strategy"])
                document.parse_quality_json = json.dumps(quality, ensure_ascii=False)
                document.status = "parsed"
                document.parsed_at = datetime.now(timezone.utc)
                document.error_message = None
                self._log_event(
                    db,
                    document,
                    "text_extracted",
                    "文本抽取完成",
                    metadata={"char_count": len(cleaned.raw_text or "")},
                )

                for chunk in chunks:
                    db.add(
                        DocumentChunk(
                            document_id=document.id,
                            parse_job_id=job_run.id,
                            chunk_index=chunk.chunk_index,
                            chunk_type=chunk.chunk_type,
                            text=chunk.text,
                            cleaned_text=chunk.cleaned_text,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                            token_count=chunk.token_count,
                            metadata_json=json.dumps(chunk.metadata, ensure_ascii=False) if chunk.metadata else None,
                        )
                    )
                for asset in ocr_assets:
                    db.add(
                        DocumentAsset(
                            document_id=document.id,
                            parse_job_id=job_run.id,
                            asset_type=asset["asset_type"],
                            page_number=asset.get("page_number"),
                            file_path=asset.get("file_path"),
                            mime_type=asset.get("mime_type"),
                            ocr_text=asset.get("ocr_text"),
                        )
                    )

                job_service.mark_succeeded(
                    job_run,
                    output_data={
                        "chunk_count": len(chunks),
                        "asset_count": len(ocr_assets),
                        "processing_mode": document.processing_mode,
                        "detected_source_type": document.source_type,
                        **strategy_metadata,
                    },
                )
                self._log_event(
                    db,
                    document,
                    "parsed",
                    "解析成功",
                    metadata={
                        "job_run_id": job_run.id,
                        "job_id": job_run.job_id,
                        "chunk_count": len(chunks),
                        "asset_count": len(ocr_assets),
                    },
                )
                db.commit()
                db.refresh(document)
                try:
                    DocumentEmbeddingService(
                        session_factory=self.session_factory,
                        embedding_provider=self.embedding_provider,
                    ).embed_document(document.id)
                except Exception as exc:
                    self._record_warning(document.id, "embedding_failed", exc)
                try:
                    DocumentKgService(session_factory=self.session_factory).extract_document(document.id)
                except Exception as exc:
                    self._record_warning(document.id, "kg_failed", exc)
                db.refresh(document)
                return document

        except Exception as exc:
            with self.session_factory() as db:
                document = db.get(Document, document_id)
                job_run = db.get(JobRun, job_id) if job_id is not None else None
                if document is not None:
                    document.status = "failed"
                    document.error_message = str(exc)
                    self._log_event(
                        db,
                        document,
                        "failed",
                        "解析失败",
                        metadata={"error_type": type(exc).__name__, "message": str(exc)[:500]},
                    )
                if job_run is not None:
                    JobRunService(db).mark_failed(
                        job_run,
                        str(exc),
                        metadata={"error_type": type(exc).__name__, "message": str(exc)[:500]},
                    )
                db.commit()
            raise

    @staticmethod
    def select_parser_strategy(processing_mode: str, detected_source_type: str) -> ProcessingStrategy:
        return select_parser_strategy(processing_mode, detected_source_type)

    def _extract_document(self, document_id: int) -> tuple[ParsedDocument, list[dict[str, str | int | None]], dict[str, bool | str | int | list]]:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            file_path = self.file_storage.get_file_path(document.original_file_path)
            source_type = document.source_type
            mime_type = document.mime_type
            relative_path = document.original_file_path
            processing_mode = document.processing_mode

        strategy = self.select_parser_strategy(processing_mode, source_type)
        metadata = {
            "processing_mode": processing_mode,
            "detected_source_type": source_type,
            **strategy.metadata(),
        }

        if source_type == "pdf":
            if strategy.ocr_first:
                ocr_pages = self.ocr_service.ocr_pdf_pages(file_path)
                metadata["used_ocr"] = True
                parsed_document = self._parsed_document_from_ocr_pages(ocr_pages, source_type="pdf")
                return parsed_document, [
                    {
                        "asset_type": "pdf_page_ocr",
                        "page_number": index + 1,
                        "file_path": relative_path,
                        "mime_type": mime_type,
                        "ocr_text": page_text,
                    }
                    for index, page_text in enumerate(ocr_pages)
                ], metadata
            parsed_document = self.parser.parse_pdf_document(file_path)
            ocr_assets: list[dict[str, str | int | None]] = []
            for page in parsed_document.pages:
                if not page.profile or not page.profile.needs_ocr:
                    continue
                try:
                    ocr_text = self.ocr_service.ocr_pdf_page(file_path, page.page_number)
                    if ocr_text.strip():
                        retained_elements = [
                            element for element in page.elements if element.element_type == "table"
                        ]
                        page.elements = retained_elements
                        page.elements.append(
                            ParsedElement(
                                element_type="ocr_text",
                                text=ocr_text,
                                page_number=page.page_number,
                                extractor="ocr",
                                metadata={
                                    "source_type": "pdf",
                                    "ocr_used": True,
                                    "warnings": page.profile.warnings.copy(),
                                },
                            )
                        )
                        page.profile.extraction_method = "hybrid" if retained_elements else "ocr"
                    else:
                        warning = "ocr_returned_empty_text"
                        page.warnings.append(warning)
                        page.profile.warnings.append(warning)
                    ocr_assets.append(
                        {
                            "asset_type": "pdf_page_ocr",
                            "page_number": page.page_number,
                            "file_path": relative_path,
                            "mime_type": mime_type,
                            "ocr_text": ocr_text,
                        }
                    )
                    metadata["used_ocr"] = True
                    metadata["ocr_fallback_used"] = True
                except Exception as exc:
                    warning = f"ocr_failed: {type(exc).__name__}: {exc}"
                    page.warnings.append(warning)
                    if page.profile:
                        page.profile.warnings.append(warning)
                    metadata["ocr_fallback_used"] = True
                    metadata.setdefault("warnings", []).append(warning)
            return parsed_document, ocr_assets, metadata
        if source_type == "image":
            text = self.ocr_service.ocr_image(file_path)
            metadata["used_ocr"] = True
            parsed_document = ParsedDocument(
                pages=[
                    ParsedPage(
                        page_number=1,
                        profile=None,
                        elements=[
                            ParsedElement(
                                element_type="ocr_text",
                                text=text,
                                page_number=None,
                                extractor="ocr",
                                metadata={"source_type": "image", "ocr_used": True},
                            )
                        ],
                    )
                ],
                source_type="image",
            )
            return parsed_document, [
                {
                    "asset_type": "uploaded_image",
                    "page_number": None,
                    "file_path": relative_path,
                    "mime_type": mime_type,
                    "ocr_text": text,
                }
            ], metadata
        text = self.parser.parse(file_path, source_type)
        return ParsedDocument(
            pages=[
                ParsedPage(
                    page_number=1,
                    profile=None,
                    elements=[
                        ParsedElement(
                            element_type="paragraph",
                            text=text,
                            page_number=None,
                            extractor="plain_text",
                            metadata={"source_type": source_type, "ocr_used": False},
                        )
                    ],
                )
            ],
            source_type=source_type,
        ), [], metadata

    def _chunk_parsed_pdf(self, parsed_document: ParsedDocument):
        chunks = []
        for page in parsed_document.pages:
            page_warnings = page.warnings.copy()
            if page.profile:
                page_warnings.extend(warning for warning in page.profile.warnings if warning not in page_warnings)
            for element in page.elements:
                metadata = {
                    "extractor": element.extractor,
                    "ocr_used": element.extractor == "ocr" or bool(element.metadata.get("ocr_used")),
                    "source_type": "pdf",
                    "page_number": element.page_number,
                    "page_range": [element.page_number, element.page_number] if element.page_number else None,
                    "warnings": page_warnings,
                    **element.metadata,
                }
                if element.bbox is not None:
                    metadata["bbox"] = list(element.bbox)
                chunk_type = "table" if element.element_type == "table" else "ocr_text" if element.extractor == "ocr" else "body"
                chunks.extend(
                    self.chunker.chunk_element_text(
                        text=element.text,
                        chunk_type=chunk_type,
                        start_index=len(chunks),
                        page_number=element.page_number,
                        metadata=metadata,
                    )
                )
        return chunks

    def _parsed_document_from_ocr_pages(self, pages: list[str], source_type: str) -> ParsedDocument:
        parsed_pages = []
        for index, text in enumerate(pages, start=1):
            parsed_pages.append(
                ParsedPage(
                    page_number=index,
                    profile=None,
                    elements=[
                        ParsedElement(
                            element_type="ocr_text",
                            text=text,
                            page_number=index,
                            extractor="ocr",
                            metadata={"source_type": source_type, "ocr_used": True},
                        )
                    ],
                )
            )
        return ParsedDocument(pages=parsed_pages, source_type=source_type)

    def _quality_metadata(self, parsed_document: ParsedDocument) -> dict:
        profiles = [page.profile for page in parsed_document.pages if page.profile is not None]
        extraction_methods: dict[str, int] = {}
        warnings: list[str] = []
        table_count = 0
        for page in parsed_document.pages:
            for warning in page.warnings:
                if warning not in warnings:
                    warnings.append(warning)
            for element in page.elements:
                extraction_methods[element.extractor] = extraction_methods.get(element.extractor, 0) + 1
                if element.element_type == "table":
                    table_count += 1
        for profile in profiles:
            for warning in profile.warnings:
                if warning not in warnings:
                    warnings.append(warning)
        for warning in parsed_document.warnings:
            if warning not in warnings:
                warnings.append(warning)
        pages_total = len(parsed_document.pages)
        pages_ocr_used = len(
            {
                element.page_number
                for page in parsed_document.pages
                for element in page.elements
                if element.extractor == "ocr" and element.page_number is not None
            }
        )
        if pages_total and pages_ocr_used / pages_total >= 0.5:
            warnings.append("many_pages_required_ocr")
        bad_text_pages = [profile.page_number for profile in profiles if profile.bad_text_layer]
        if pages_total and len(bad_text_pages) / pages_total >= 0.5:
            warnings.append("many_pages_have_bad_text_layer")
        return {
            "parser_version": parsed_document.parser_version,
            "parser_engine": parsed_document.parser_engine,
            "pymupdf_available": parsed_document.pymupdf_available,
            "pages_total": pages_total,
            "pages_text_extracted": len({profile.page_number for profile in profiles if not profile.needs_ocr}),
            "pages_ocr_used": pages_ocr_used,
            "scanned_pages": [profile.page_number for profile in profiles if profile.is_scanned],
            "bad_text_pages": bad_text_pages,
            "table_count": table_count,
            "table_extraction_enabled": parsed_document.table_extraction_enabled,
            "table_extraction_reason": parsed_document.table_extraction_reason,
            "extraction_methods": extraction_methods,
            "warnings": warnings,
            "page_profiles": [
                {
                    "page_number": profile.page_number,
                    "text_length": profile.text_length,
                    "word_count": profile.word_count,
                    "block_count": profile.block_count,
                    "image_block_count": profile.image_block_count,
                    "image_count": profile.image_count,
                    "is_scanned": profile.is_scanned,
                    "bad_text_layer": profile.bad_text_layer,
                    "needs_ocr": profile.needs_ocr,
                    "extraction_method": profile.extraction_method,
                    "warnings": profile.warnings,
                }
                for profile in profiles
            ],
        }

    def _processing_metadata(self, document: Document, strategy: ProcessingStrategy) -> dict[str, bool | str]:
        return {
            "processing_mode": document.processing_mode,
            "detected_source_type": document.source_type,
            **strategy.metadata(),
        }

    def _log_event(
        self,
        db: Session,
        document: Document,
        event_type: str,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        db.add(
            DocumentEvent(
                document_id=document.id,
                user_id=document.user_id,
                event_type=event_type,
                message=message,
                event_metadata=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            )
        )

    def _record_warning(self, document_id: int, event_type: str, exc: Exception) -> None:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                return
            self._log_event(
                db,
                document,
                event_type,
                str(exc)[:500],
                metadata={"error_type": type(exc).__name__},
            )
            db.commit()
