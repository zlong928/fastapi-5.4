from __future__ import annotations

import json
import hashlib
import time
from uuid import uuid4

from app.core.config import DOCUMENT_PARSE_TIMEOUT_SECONDS, ENABLE_MINERU_PARSER, RESULT_DIR
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import app_now
from app.db.session import SessionLocal
from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE, SUBJECT_TYPE_DOCUMENT
from app.models import Document, DocumentAsset, DocumentChunk, DocumentClaim, DocumentEvent, JobRun
from app.services.chunking_service import ChunkingService
from app.services.document_embedding_service import EmbeddingProvider, DocumentEmbeddingService
from app.services.document_kg_service import DocumentKgService
from app.services.document_parser import DocumentParserService, ParsedDocument, ParsedElement, ParsedPage
from app.services.document_processing_modes import ProcessingStrategy, select_parser_strategy
from app.services.document_input import build_document_input, DocumentInput
from app.services.job_run_service import JobRunService
from app.services.file_storage import FileStorageService
from app.services.mineru_asset_ingestion import MinerUVisualAssetIngestion
from app.services.mineru_parser import MinerUParserService, MinerUParserUnavailable
from app.services.ocr_service import OcrService
from app.services.paper.asset_understanding_service import AssetUnderstandingService
from app.services.paper.claim_extraction_service import ClaimExtractionService
from app.services.text_cleaner import TextCleaner

STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
PROCESSING_ERROR_EMPTY_CONTENT = "文件内容为空"
PROCESSING_ERROR_IMAGE_UNREADABLE = "图片文件无法打开"
PROCESSING_ERROR_PDF_DAMAGED = "PDF 文件损坏，无法解析"
PROCESSING_ERROR_TIMEOUT = "文件解析超时"
PROCESSING_ERROR_UNSUPPORTED = "文件类型不支持"
PROCESSING_ERROR_SOURCE_FILE_MISSING = "源文件不存在，无法解析"
PROCESSING_ERROR_SOURCE_PATH_INVALID = "源文件路径无效，无法解析"


class DocumentProcessingFailure(RuntimeError):
    def __init__(self, reason: str, *, error_type: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_type = error_type or self.__class__.__name__


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
        self.asset_understanding = AssetUnderstandingService()
        self.claim_extractor = ClaimExtractionService()
        self.mineru_asset_ingestion = MinerUVisualAssetIngestion(self.file_storage)

    def run(
        self,
        document_id: int,
        job_run_id: int | None = None,
        job_type: str = "initial_parse",
        parse_job_id: int | None = None,
        require_mineru: bool = False,
        preserve_outputs_on_failure: bool = False,
    ) -> Document:
        if job_run_id is None and parse_job_id is not None:
            job_run_id = parse_job_id
        job_id: int | None = job_run_id
        previous_status: str | None = None
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            previous_status = document.status

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
                        "require_mineru": require_mineru,
                    },
                    metadata={"job_type": job_type, "require_mineru": require_mineru},
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
            job_service.update_progress(
                job_run,
                10,
                metadata={**self._processing_metadata(document, strategy), "require_mineru": require_mineru},
            )
            document.status = STATUS_PROCESSING
            document.error_message = None
            document.fail_reason = None
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
            deadline = time.monotonic() + DOCUMENT_PARSE_TIMEOUT_SECONDS
            parsed_document, ocr_assets, strategy_metadata = self._extract_document(document_id)
            self._raise_if_timeout(deadline)
            cleaned = self.cleaner.clean_pages(parsed_document.text_pages)
            document_input = self._build_document_input(document_id, cleaned.cleaned_text)
            if not document_input.page_content.strip():
                raise DocumentProcessingFailure(PROCESSING_ERROR_EMPTY_CONTENT, error_type="empty_content")
            self._raise_if_timeout(deadline)
            content_hash = self._content_hash(document_input.page_content)
            collection_name = self._collection_name(document_id, content_hash)
            content_summary = self._content_summary(document_input.page_content)
            if parsed_document.source_type == "pdf":
                chunks = self._chunk_parsed_pdf(parsed_document)
            else:
                chunks = self.chunker.chunk_document(
                    cleaned_text=cleaned.cleaned_text,
                    captions=cleaned.captions,
                    references_text=cleaned.references_text,
                )
            self._raise_if_timeout(deadline)

            with self.session_factory() as db:
                document = db.get(Document, document_id)
                job_run = db.get(JobRun, job_id)
                if document is None or job_run is None:
                    raise ValueError(f"Document not found: {document_id}")
                if document.status == "deleted":
                    return document
                job_service = JobRunService(db)
                duplicate = db.scalars(
                    select(Document).where(
                        Document.user_id == document.user_id,
                        Document.id != document.id,
                        Document.content_hash == content_hash,
                        Document.status != "deleted",
                    )
                ).first()
                if duplicate is not None:
                    raise ValueError(
                        f"Duplicate document content: matches document {duplicate.id} ({duplicate.original_filename})."
                    )
                job_service.update_progress(job_run, 70, metadata={"stage": "saving_parse_outputs"})

                (
                    db.query(DocumentChunk)
                    .filter(DocumentChunk.document_id == document.id)
                    .delete(synchronize_session=False)
                )
                (
                    db.query(DocumentAsset)
                    .filter(DocumentAsset.document_id == document.id)
                    .delete(synchronize_session=False)
                )
                (
                    db.query(DocumentClaim)
                    .filter(DocumentClaim.document_id == document.id)
                    .delete(synchronize_session=False)
                )
                document.parsed_text = cleaned.raw_text
                document.cleaned_text = cleaned.cleaned_text
                document.references_text = cleaned.references_text
                quality = {**cleaned.quality, **strategy_metadata, **self._quality_metadata(parsed_document)}
                document.processing_strategy = str(strategy_metadata["processing_strategy"])
                document.parse_quality_json = json.dumps(quality, ensure_ascii=False)
                document.status = STATUS_PROCESSING
                document.parsed_at = app_now()
                document.collection_name = collection_name
                document.content_hash = content_hash
                document.page_count = len(parsed_document.pages) or None
                document.content_summary = content_summary
                document.chunk_count = len(chunks)
                document.error_message = None
                self._log_event(
                    db,
                    document,
                    "text_extracted",
                    "文本抽取完成",
                    metadata={"char_count": len(cleaned.raw_text or "")},
                )

                for chunk in chunks:
                    metadata = {
                        **chunk.metadata,
                        **document_input.metadata,
                        "chunk_source": chunk.metadata.get("source"),
                        "chunk_index": chunk.chunk_index,
                        "start_index": chunk.char_start,
                        "hash": content_hash,
                    }
                    db.add(
                        DocumentChunk(
                            vector_id=str(uuid4()),
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
                            metadata_json=json.dumps(metadata, ensure_ascii=False),
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

                table_assets = self._table_assets_from_parsed_document(
                    document=document,
                    parse_job_id=job_run.id,
                    parsed_document=parsed_document,
                )
                for asset in table_assets:
                    self.asset_understanding.understand(asset)
                    db.add(asset)

                mineru_visual_assets = self._mineru_visual_assets(
                    document=document,
                    parse_job_id=job_run.id,
                    strategy_metadata=strategy_metadata,
                    markdown_text=document.cleaned_text or document.parsed_text or "",
                )
                for asset in mineru_visual_assets:
                    self.asset_understanding.understand(asset)
                    db.add(asset)

                db.flush()

                self._log_event(
                    db,
                    document,
                    "asset_summary_finished",
                    "证据资产摘要完成",
                    metadata={
                        "table_count": len(table_assets),
                        "mineru_visual_asset_count": len(mineru_visual_assets),
                        "asset_count": len(ocr_assets) + len(table_assets) + len(mineru_visual_assets),
                    },
                )

                persisted_chunks = (
                    db.query(DocumentChunk)
                    .filter(DocumentChunk.document_id == document.id)
                    .order_by(DocumentChunk.chunk_index)
                    .all()
                )
                persisted_assets = (
                    db.query(DocumentAsset)
                    .filter(DocumentAsset.document_id == document.id)
                    .order_by(DocumentAsset.id)
                    .all()
                )
                claims = self.claim_extractor.extract(chunks=persisted_chunks, assets=persisted_assets)
                for claim in claims:
                    db.add(claim)
                self._log_event(
                    db,
                    document,
                    "claim_extraction_finished",
                    f"抽取到 {len(claims)} 条关键结果",
                    metadata={"claim_count": len(claims)},
                )

                job_service.update_progress(job_run, 85, metadata={"stage": "embedding_chunks"})
                self._log_event(
                    db,
                    document,
                    "chunks_saved",
                    "切块保存完成，开始 embedding",
                    metadata={
                        "job_run_id": job_run.id,
                        "job_id": job_run.job_id,
                        "chunk_count": len(chunks),
                        "asset_count": len(ocr_assets) + len(table_assets) + len(mineru_visual_assets),
                    },
                )
                db.commit()
                db.refresh(document)
                try:
                    embedded_count = DocumentEmbeddingService(
                        session_factory=self.session_factory,
                        embedding_provider=self.embedding_provider,
                    ).embed_document(document.id)
                    if embedded_count != len(chunks):
                        raise RuntimeError(f"Expected {len(chunks)} embedded chunks, got {embedded_count}.")
                except Exception as exc:
                    self._record_warning(document.id, "embedding_failed", exc)
                    embedded_count = 0
                with self.session_factory() as status_db:
                    completed_document = status_db.get(Document, document_id)
                    completed_job = status_db.get(JobRun, job_id) if job_id is not None else None
                    if completed_document is None:
                        raise ValueError(f"Document not found: {document_id}")
                    completed_document.status = STATUS_DONE
                    completed_document.error_message = None
                    completed_document.fail_reason = None
                    if completed_job is not None:
                        JobRunService(status_db).mark_succeeded(
                            completed_job,
                            output_data={
                                "chunk_count": len(chunks),
                                "asset_count": len(ocr_assets),
                                "processing_mode": completed_document.processing_mode,
                                "detected_source_type": completed_document.source_type,
                                "collection_name": completed_document.collection_name,
                                "hash": completed_document.content_hash,
                                **strategy_metadata,
                            },
                        )
                    self._log_event(
                        status_db,
                        completed_document,
                        "parse_success",
                        "处理完成",
                        metadata={
                            "job_run_id": completed_job.id if completed_job else None,
                            "job_id": completed_job.job_id if completed_job else None,
                            "chunk_count": len(chunks),
                            "collection_name": completed_document.collection_name,
                            "hash": completed_document.content_hash,
                        },
                    )
                    status_db.commit()
                try:
                    DocumentKgService(session_factory=self.session_factory).extract_document(document.id)
                except Exception as exc:
                    self._record_warning(document.id, "kg_failed", exc)
                self._auto_enhance_pdf(document_id)
                with self.session_factory() as final_db:
                    final_document = final_db.get(Document, document_id)
                    if final_document is None:
                        raise ValueError(f"Document not found: {document_id}")
                    return final_document

        except Exception as exc:
            self._record_processing_failure(
                document_id,
                job_id,
                "parse_failed",
                exc,
                clear_outputs=not preserve_outputs_on_failure,
                restore_status=previous_status if preserve_outputs_on_failure else None,
            )
            return self._get_document(document_id)

    @staticmethod
    def select_parser_strategy(processing_mode: str, detected_source_type: str) -> ProcessingStrategy:
        return select_parser_strategy(processing_mode, detected_source_type)

    def _extract_document(
        self,
        document_id: int,
    ) -> tuple[ParsedDocument, list[dict[str, str | int | None]], dict[str, bool | str | int | list]]:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            try:
                file_path = self.file_storage.get_file_path(document.original_file_path)
            except ValueError as exc:
                raise DocumentProcessingFailure(
                    PROCESSING_ERROR_SOURCE_PATH_INVALID,
                    error_type="invalid_source_path",
                ) from exc
            if not file_path.is_file():
                raise DocumentProcessingFailure(
                    PROCESSING_ERROR_SOURCE_FILE_MISSING,
                    error_type="missing_source_file",
                )
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
            if not ENABLE_MINERU_PARSER:
                raise DocumentProcessingFailure(
                    "MinerU parser is required for PDF documents but is currently disabled.",
                    error_type="mineru_required_disabled",
                )
            try:
                mineru_result = MinerUParserService().parse_pdf_file(
                    file_path,
                    data_id=f"document-{document_id}",
                    output_root=RESULT_DIR / "mineru",
                )
                metadata.update(
                    {
                        "processing_strategy": "mineru",
                        "mineru_enabled": True,
                        "mineru_used": True,
                        "mineru_batch_id": mineru_result.batch_id,
                        "mineru_file_name": mineru_result.file_name,
                        "mineru_markdown_file": mineru_result.markdown_file,
                        "mineru_full_zip_url": mineru_result.full_zip_url,
                        "mineru_artifact_dir": mineru_result.artifact_dir or "",
                        "mineru_zip_path": mineru_result.zip_path or "",
                        "mineru_extract_dir": mineru_result.extract_dir or "",
                        "mineru_content_list_path": mineru_result.content_list_path or "",
                        "mineru_layout_path": mineru_result.layout_path or "",
                    }
                )
                return mineru_result.parsed_document, [], metadata
            except MinerUParserUnavailable as exc:
                raise DocumentProcessingFailure(
                    f"MinerU 解析不可用：{exc}",
                    error_type="mineru_required_failed",
                ) from exc
            except Exception as exc:
                raise DocumentProcessingFailure(
                    f"MinerU 解析失败：{exc}",
                    error_type="mineru_required_failed",
                ) from exc
        if source_type == "image":
            try:
                text = self.ocr_service.ocr_image(file_path)
            except TimeoutError:
                raise
            except Exception as exc:
                raise DocumentProcessingFailure(PROCESSING_ERROR_IMAGE_UNREADABLE, error_type="image_parse_failed") from exc
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
        try:
            text = self.parser.parse(file_path, source_type)
        except TimeoutError:
            raise
        except ValueError as exc:
            message = str(exc).lower()
            if source_type not in {"txt", "text", "markdown", "md"} or "unsupported file type" in message:
                raise DocumentProcessingFailure(PROCESSING_ERROR_UNSUPPORTED, error_type="unsupported_file_type") from exc
            raise
        if not text.strip():
            raise DocumentProcessingFailure(PROCESSING_ERROR_EMPTY_CONTENT, error_type="empty_content")
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

    def _table_assets_from_parsed_document(
        self,
        *,
        document: Document,
        parse_job_id: int,
        parsed_document: ParsedDocument,
    ) -> list[DocumentAsset]:
        assets: list[DocumentAsset] = []
        for page in parsed_document.pages:
            for element in page.elements:
                if element.element_type != "table" or not element.text.strip():
                    continue
                index = len(assets)
                metadata = {
                    **element.metadata,
                    "extractor": element.extractor,
                    "source": "parsed_table",
                    "data_extraction_possible": True,
                }
                label = str(metadata.get("label") or metadata.get("table_label") or f"Table {index + 1}")
                caption = str(metadata.get("caption") or metadata.get("context") or label)
                assets.append(
                    DocumentAsset(
                        document_id=document.id,
                        parse_job_id=parse_job_id,
                        asset_type="table",
                        asset_index=index,
                        label=label,
                        caption=caption,
                        page_number=element.page_number,
                        markdown=element.text,
                        text_content=element.text,
                        mime_type="text/markdown",
                        metadata_json=json.dumps(metadata, ensure_ascii=False),
                    )
                )
        return assets

    def _mineru_visual_assets(
        self,
        *,
        document: Document,
        parse_job_id: int,
        strategy_metadata: dict,
        markdown_text: str = "",
    ) -> list[DocumentAsset]:
        if not strategy_metadata.get("mineru_used"):
            return []
        return self.mineru_asset_ingestion.ingest(
            document=document,
            parse_job_id=parse_job_id,
            markdown_text=markdown_text,
            extract_dir=str(strategy_metadata.get("mineru_extract_dir") or ""),
            generate_coordinate_preview=True,
        )

    def _build_document_input(self, document_id: int, page_content: str) -> DocumentInput:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            return build_document_input(
                page_content=page_content,
                filename=document.original_filename,
                file_id=document.id,
                source=document.original_file_path,
                content_type=document.mime_type,
                created_by=document.user_id,
                extra_metadata={
                    "source_type": document.source_type,
                    "processing_mode": document.processing_mode,
                },
            )

    def _content_hash(self, text: str) -> str:
        normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _collection_name(self, document_id: int, content_hash: str) -> str:
        return f"document_{document_id}_{content_hash[:12]}"

    def _content_summary(self, text: str, limit: int = 500) -> str:
        return " ".join(text.split())[:limit]

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

    def _get_document(self, document_id: int) -> Document:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document not found: {document_id}")
            return document

    def _auto_enhance_pdf(self, document_id: int) -> None:
        with self.session_factory() as db:
            document = db.get(Document, document_id)
            if document is None or document.source_type != "pdf" or document.status != STATUS_DONE:
                return
            try:
                from app.services.paper.enhancement_service import PaperEnhancementService
                PaperEnhancementService(db, file_storage=self.file_storage).enhance(document)
            except Exception as exc:
                self._record_warning(document_id, "auto_enhance_failed", exc)

    def _raise_if_timeout(self, deadline: float) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError(PROCESSING_ERROR_TIMEOUT)

    def _failure_reason(self, exc: Exception) -> tuple[str, str]:
        if isinstance(exc, DocumentProcessingFailure):
            return exc.reason, exc.error_type
        if isinstance(exc, TimeoutError):
            return PROCESSING_ERROR_TIMEOUT, "parse_timeout"
        message = str(exc)
        normalized = message.lower()
        if "extracted document content is empty" in normalized or "file is empty" in normalized:
            return PROCESSING_ERROR_EMPTY_CONTENT, type(exc).__name__
        if "unsupported file type" in normalized:
            return PROCESSING_ERROR_UNSUPPORTED, type(exc).__name__
        return message or "文件处理失败", type(exc).__name__

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

    def _record_processing_failure(
        self,
        document_id: int,
        job_run_id: int | None,
        event_type: str,
        exc: Exception,
        *,
        clear_outputs: bool = True,
        restore_status: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            reason, error_type = self._failure_reason(exc)
            document = db.get(Document, document_id)
            job_run = db.get(JobRun, job_run_id) if job_run_id is not None else None
            if document is not None:
                if clear_outputs:
                    (
                        db.query(DocumentChunk)
                        .filter(DocumentChunk.document_id == document.id)
                        .delete(synchronize_session=False)
                    )
                    (
                        db.query(DocumentAsset)
                        .filter(DocumentAsset.document_id == document.id)
                        .delete(synchronize_session=False)
                    )
                    (
                        db.query(DocumentClaim)
                        .filter(DocumentClaim.document_id == document.id)
                        .delete(synchronize_session=False)
                    )
                    document.parsed_at = None
                    document.chunk_count = 0
                document.status = restore_status or STATUS_FAILED
                document.error_message = reason
                document.fail_reason = reason
                self._log_event(
                    db,
                    document,
                    event_type,
                    reason[:500],
                    metadata={"error_type": error_type, "outputs_preserved": not clear_outputs},
                )
            if job_run is not None:
                JobRunService(db).mark_failed(
                    job_run,
                    reason,
                    metadata={"error_type": error_type, "stage": event_type},
                )
            db.commit()
