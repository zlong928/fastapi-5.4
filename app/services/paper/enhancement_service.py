from __future__ import annotations

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import app_now
from app.models import Document, DocumentAsset, DocumentEvent, PaperTable
from app.services.file_storage import FileStorageService
from app.services.paper.asset_understanding_service import AssetUnderstandingService
from app.services.paper.figure_extractor import FigureExtractor
from app.services.paper.table_extractor import TableExtractor
from app.services.paper.text_extractor import TextExtractor
from app.services.paper.visual_assets import is_mineru_visual_asset


class PaperEnhancementService:
    """Coordinate paper-only enrichment for already parsed PDF documents."""

    def __init__(
        self,
        db: Session,
        file_storage: FileStorageService | None = None,
        text_extractor: TextExtractor | None = None,
        figure_extractor: FigureExtractor | None = None,
        table_extractor: TableExtractor | None = None,
    ) -> None:
        self.db = db
        self.file_storage = file_storage or FileStorageService()
        self.text_extractor = text_extractor or TextExtractor()
        self.figure_extractor = figure_extractor or FigureExtractor(self.file_storage)
        self.table_extractor = table_extractor or TableExtractor()
        self.asset_understanding = AssetUnderstandingService()

    def parse(self, paper: Document) -> Document:
        return self.enhance(paper)

    def enhance(self, paper: Document) -> Document:
        self._validate_paper(paper)
        paper_id = paper.id
        paper.status = "processing"
        paper.updated_at = app_now()
        self._log_event(paper, "paper_enhancement_started", "论文增强解析开始。")
        self.db.commit()
        try:
            source_path = self.file_storage.get_file_path(paper.original_file_path)
            if not source_path.exists():
                raise FileNotFoundError("源 PDF 文件不存在")

            text_report = self.text_extractor.extract(source_path)
            if text_report.status == "failed":
                raise RuntimeError(text_report.message or "PDF 正文提取失败")

            existing_text = text_report.text or paper.cleaned_text or paper.parsed_text or ""
            existing_mineru_visuals = self._has_mineru_visual_assets(paper)
            if existing_mineru_visuals:
                figure_report = None
            else:
                figure_report = self.figure_extractor.extract(source_path=source_path, paper=paper, pages=text_report.pages)
                if figure_report.status == "failed":
                    raise RuntimeError(figure_report.message or "PDF 图片/截图提取失败")

            table_report = self.table_extractor.extract(
                paper_id=paper.id,
                source_path=source_path,
                pages=text_report.pages,
                existing_text=existing_text,
            )

            self._delete_previous_enhancement(paper)

            text_to_save = text_report.text.strip()
            if text_to_save:
                paper.parsed_text = text_to_save
                paper.cleaned_text = text_to_save
            elif not (paper.cleaned_text or paper.parsed_text):
                paper.parsed_text = "当前 PDF 未解析到可抽取正文。"
                paper.cleaned_text = paper.parsed_text

            if figure_report is not None:
                for asset in figure_report.assets:
                    self.asset_understanding.understand(asset)
                    self.db.add(asset)
            table_assets = [self._table_asset_from_legacy_table(table, index) for index, table in enumerate(table_report.tables)]
            for asset in table_assets:
                self.asset_understanding.understand(asset)
                self.db.add(asset)

            paper.status = "done"
            paper.parsed_at = paper.parsed_at or app_now()
            paper.updated_at = app_now()
            done_metadata = {
                "figure_count": 0 if figure_report is None else figure_report.figure_count,
                "snapshot_count": 0 if figure_report is None else figure_report.snapshot_count,
                "figure_status": "mineru_preserved" if figure_report is None else figure_report.status,
                "table_count": len(table_assets),
                "table_status": table_report.status,
                "table_source": table_report.source,
            }
            self._log_event(paper, "paper_enhancement_done", "论文增强解析完成。", done_metadata)
            if figure_report is not None and figure_report.status == "partial":
                self._log_event(paper, "paper_figures_partial", figure_report.message, done_metadata)
            if table_report.status in {"fallback", "partial"}:
                self._log_event(
                    paper,
                    "paper_tables_fallback",
                    table_report.message,
                    {"table_count": len(table_assets), "table_status": table_report.status, "table_source": table_report.source},
                )
            self.db.commit()
            self.db.refresh(paper)
            return paper
        except Exception as exc:
            self.db.rollback()
            failed_paper = self.db.get(Document, paper_id)
            if failed_paper is not None:
                failed_paper.status = "failed"
                failed_paper.fail_reason = str(exc)[:500]
                failed_paper.updated_at = app_now()
                self._log_event(failed_paper, "paper_enhancement_failed", str(exc), {"error": str(exc)})
                self.db.commit()
            raise

    def _validate_paper(self, paper: Document) -> None:
        if paper.source_type != "pdf":
            raise ValueError("仅支持 PDF 文档进行论文增强解析")
        if paper.status not in ("done", "failed"):
            raise ValueError("文档解析完成后才能进行论文增强解析")

    def _delete_previous_enhancement(self, paper: Document) -> None:
        self.db.query(DocumentAsset).filter(
            DocumentAsset.document_id == paper.id,
            DocumentAsset.asset_type.in_(["table", "figure", "page_snapshot"]),
            or_(
                DocumentAsset.metadata_json.is_(None),
                ~DocumentAsset.metadata_json.like('%"source": "mineru_%'),
            ),
        ).delete(synchronize_session=False)
        self.db.query(PaperTable).filter(PaperTable.paper_id == paper.id).delete(synchronize_session=False)

    def _has_mineru_visual_assets(self, paper: Document) -> bool:
        assets = (
            self.db.query(DocumentAsset)
            .filter(
                DocumentAsset.document_id == paper.id,
                DocumentAsset.asset_type.in_(["figure", "page_snapshot"]),
            )
            .all()
        )
        return any(is_mineru_visual_asset(asset) for asset in assets)

    def _table_asset_from_legacy_table(self, table: PaperTable, index: int) -> DocumentAsset:
        metadata = {
            "source": "paper_table_intermediate",
            "legacy_table_id": table.id,
            "table_label": table.table_label,
        }
        return DocumentAsset(
            document_id=table.paper_id,
            asset_type="table",
            asset_index=index,
            label=table.table_label,
            caption=table.table_label,
            page_number=table.page,
            markdown=table.content,
            text_content=table.content,
            mime_type="text/markdown",
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )

    def _log_event(self, paper: Document, event_type: str, message: str, metadata: dict | None = None) -> None:
        self.db.add(
            DocumentEvent(
                document_id=paper.id,
                user_id=paper.user_id,
                event_type=event_type,
                message=message[:500],
                event_metadata=json.dumps(metadata or {}, ensure_ascii=False),
            )
        )
