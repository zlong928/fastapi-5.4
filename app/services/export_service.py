"""
Export service for exporting extraction results, documents, and papers to various formats.
Supports CSV, Excel, JSON, and Markdown formats.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime, timezone
from io import BytesIO, StringIO
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentAsset, DocumentChunk, ExtractionJob, ExtractionResult
from app.services.paper.evidence import asset_metadata, asset_image_url, normalize_evidence_type

logger = logging.getLogger(__name__)


def _source_label(source: str | None) -> str:
    labels = {
        "extracted_image": "嵌入图片",
        "rendered_figure_region": "图注裁剪",
        "page_visual_snapshot": "页面快照",
        "fallback_snapshot": "兜底快照",
        "table": "表格资产",
        "figure": "图片资产",
        "page_snapshot": "页面快照",
    }
    return labels.get(source or "", source or "unknown")


def _evidence_type_label(evidence_type: str) -> str:
    labels = {
        "text": "正文",
        "table": "表格",
        "figure": "图片",
        "chart": "图表",
        "equation": "公式",
        "page_region": "页面区域",
        "unknown": "未知",
    }
    return labels.get(evidence_type, evidence_type)


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


class ExportService:
    """Service for exporting data to various formats."""

    @staticmethod
    def export_extraction_to_csv(db: Session, job: ExtractionJob, result_ids: list[int] | None = None) -> str:
        """Export extraction job results to CSV format.

        Args:
            db: Database session
            job: Extraction job to export
            result_ids: Optional list of result IDs to export. If None, exports all results.
        """
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "ID",
            "Field Name",
            "Content",
            "Evidence",
            "Confidence",
            "Evidence Type",
            "Source Type",
            "Source ID",
            "Figure ID",
            "Caption",
            "Image URL",
            "Page",
            "Notes",
            "Parse Status",
            "Extraction Mode",
            "Created At"
        ])

        # Filter results if result_ids provided
        results = job.results
        if result_ids is not None:
            result_ids_set = set(result_ids)
            results = [r for r in results if r.id in result_ids_set]

        # Load assets for image URLs
        asset_ids = [r.source_id for r in results if r.source_id and r.source_type in {"asset", "figure", "table"}]
        assets_map = {}
        if asset_ids:
            assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
            assets_map = {a.id: a for a in assets}

        # Write data rows
        for result in sorted(results, key=lambda r: r.id):
            asset = assets_map.get(result.source_id) if result.source_id else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(
                source_type=result.source_type,
                asset=asset,
                metadata=metadata
            )
            image_url = asset_image_url(asset) if asset else ""
            page = asset.page_number if asset else None

            writer.writerow([
                result.id,
                result.field_name,
                result.content,
                result.evidence,
                result.confidence,
                evidence_type,
                result.source_type,
                result.source_id,
                result.figure_id or "",
                result.caption or "",
                image_url,
                page or "",
                result.notes or "",
                result.parse_status or "",
                result.extraction_mode or "",
                result.created_at.isoformat() if result.created_at else ""
            ])

        return output.getvalue()

    @staticmethod
    def export_extraction_to_json(db: Session, job: ExtractionJob, result_ids: list[int] | None = None) -> str:
        """Export extraction job results to JSON format.

        Args:
            db: Database session
            job: Extraction job to export
            result_ids: Optional list of result IDs to export. If None, exports all results.
        """
        # Filter results if result_ids provided
        results = job.results
        if result_ids is not None:
            result_ids_set = set(result_ids)
            results = [r for r in results if r.id in result_ids_set]

        # Load assets for image URLs
        asset_ids = [r.source_id for r in results if r.source_id and r.source_type in {"asset", "figure", "table"}]
        assets_map = {}
        if asset_ids:
            assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
            assets_map = {a.id: a for a in assets}

        results_data = []
        for result in sorted(results, key=lambda r: r.id):
            asset = assets_map.get(result.source_id) if result.source_id else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(
                source_type=result.source_type,
                asset=asset,
                metadata=metadata
            )

            results_data.append({
                "id": result.id,
                "field_name": result.field_name,
                "content": result.content,
                "evidence": result.evidence,
                "confidence": result.confidence,
                "evidence_type": evidence_type,
                "source_type": result.source_type,
                "source_id": result.source_id,
                "figure_id": result.figure_id,
                "caption": result.caption,
                "image_url": asset_image_url(asset) if asset else None,
                "page": asset.page_number if asset else None,
                "bbox": metadata.get("bbox") if metadata else None,
                "notes": result.notes,
                "structured_data": result.structured_data,
                "parse_status": result.parse_status,
                "extraction_mode": result.extraction_mode,
                "created_at": result.created_at.isoformat() if result.created_at else None
            })

        paper = db.get(Document, job.paper_id)

        export_data = {
            "job": {
                "id": job.id,
                "paper_id": job.paper_id,
                "paper_title": paper.title if paper else "",
                "query": job.query,
                "status": job.status,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None
            },
            "results": results_data,
            "summary": {
                "total_results": len(results_data),
                "filtered": result_ids is not None,
                "exported_at": datetime.now(timezone.utc).isoformat()
            }
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

    @staticmethod
    def _matching_text_chunk(db: Session, paper_id: int, result: ExtractionResult) -> DocumentChunk | None:
        evidence = _compact_text(result.evidence)
        content = _compact_text(result.content)
        candidates = [text for text in (evidence, content) if len(text) >= 20]
        if not candidates:
            return None

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == paper_id)
            .order_by(DocumentChunk.page_start.asc().nullslast(), DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
            .all()
        )
        for chunk in chunks:
            chunk_text = _compact_text(chunk.cleaned_text or chunk.text)
            if any(candidate[:120] in chunk_text or chunk_text[:120] in candidate for candidate in candidates):
                return chunk
        return None

    @staticmethod
    def _markdown_location_lines(
        db: Session,
        *,
        paper: Document | None,
        result: ExtractionResult,
        asset: DocumentAsset | None,
        metadata: dict,
        evidence_type: str,
    ) -> list[str]:
        paper_id = paper.id if paper else result.job.paper_id
        page = asset.page_number if asset else None
        chunk = None
        if page is None and paper_id is not None:
            chunk = ExportService._matching_text_chunk(db, paper_id, result)
            page = chunk.page_start if chunk else None

        source = str(metadata.get("source") or asset.asset_type) if asset else ("document_chunk" if chunk else result.source_type)
        lines = [
            "**Evidence Location:**",
            f"- Type: {_evidence_type_label(evidence_type)} (`{evidence_type}`)",
            f"- Source: {_source_label(source)} (`{source}`)",
        ]
        if page:
            lines.append(f"- Original PDF: [p.{page}](/documents/{paper_id}/file#page={page})")
        else:
            lines.append("- Original PDF: page not resolved")
        if chunk:
            chunk_page = f"p.{chunk.page_start}" if chunk.page_start else "page unknown"
            lines.append(f"- Text Chunk: #{chunk.chunk_index} ({chunk_page})")
        if asset:
            lines.append(f"- Asset: #{asset.id}")
            if asset.label:
                lines.append(f"- Asset Label: {asset.label}")
            if asset.page_number:
                lines.append(f"- Asset Page: p.{asset.page_number}")
            image_url = asset_image_url(asset)
            if image_url:
                lines.append(f"- Asset Preview: [open image]({image_url})")
            bbox = metadata.get("bbox")
            if bbox:
                lines.append(f"- Bounding Box: `{json.dumps(bbox, ensure_ascii=False)}`")
        if result.figure_id:
            lines.append(f"- Figure/Table ID: {result.figure_id}")
        return lines

    @staticmethod
    def export_extraction_to_markdown(db: Session, job: ExtractionJob, result_ids: list[int] | None = None) -> str:
        """Export extraction job results to Markdown format.

        Args:
            db: Database session
            job: Extraction job to export
            result_ids: Optional list of result IDs to export. If None, exports all results.
        """
        paper = db.get(Document, job.paper_id)

        # Filter results if result_ids provided
        results = job.results
        if result_ids is not None:
            result_ids_set = set(result_ids)
            results = [r for r in results if r.id in result_ids_set]

        # Load assets for image URLs
        asset_ids = [r.source_id for r in results if r.source_id and r.source_type in {"asset", "figure", "table"}]
        assets_map = {}
        if asset_ids:
            assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
            assets_map = {a.id: a for a in assets}

        lines = []
        lines.append(f"# Extraction Results: {paper.title if paper else 'Unknown'}")
        lines.append("")
        lines.append(f"**Query:** {job.query}")
        lines.append(f"**Status:** {job.status}")
        lines.append(f"**Created:** {job.created_at.strftime('%Y-%m-%d %H:%M:%S') if job.created_at else 'N/A'}")
        lines.append(f"**Total Results:** {len(results)}")
        if result_ids is not None:
            lines.append(f"**Filtered:** Yes (selected {len(results)} of {len(job.results)} results)")
        lines.append("")
        lines.append("---")
        lines.append("")

        for result in sorted(results, key=lambda r: r.id):
            asset = assets_map.get(result.source_id) if result.source_id else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(
                source_type=result.source_type,
                asset=asset,
                metadata=metadata
            )

            lines.append(f"## {result.field_name}")
            lines.append("")
            lines.append(f"**Content:** {result.content}")
            lines.append("")
            lines.append(f"**Evidence:** {result.evidence}")
            lines.append("")
            lines.extend(
                ExportService._markdown_location_lines(
                    db,
                    paper=paper,
                    result=result,
                    asset=asset,
                    metadata=metadata,
                    evidence_type=evidence_type,
                )
            )
            lines.append("")

            if result.confidence is not None:
                lines.append(f"**Confidence:** {result.confidence:.2f}")

            lines.append(f"**Evidence Type:** {evidence_type}")

            if result.figure_id:
                lines.append(f"**Figure ID:** {result.figure_id}")

            if result.caption:
                lines.append(f"**Caption:** {result.caption}")

            if asset:
                image_url = asset_image_url(asset)
                if image_url:
                    lines.append(f"**Image:** {image_url}")
                if asset.page_number:
                    lines.append(f"**Page:** {asset.page_number}")

            if result.notes:
                lines.append(f"**Notes:** {result.notes}")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def export_documents_to_csv(documents: list[Document]) -> str:
        """Export document list to CSV format."""
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "ID",
            "Title",
            "Source Type",
            "Status",
            "File Size (bytes)",
            "Page Count",
            "Created At",
            "Updated At",
            "Tags"
        ])

        # Write data rows
        for doc in documents:
            tags = ", ".join([tag.name for tag in doc.tags]) if hasattr(doc, 'tags') and doc.tags else ""
            writer.writerow([
                doc.id,
                doc.title,
                doc.source_type,
                doc.status,
                doc.file_size or 0,
                doc.page_count or 0,
                doc.created_at.isoformat() if doc.created_at else "",
                doc.updated_at.isoformat() if doc.updated_at else "",
                tags
            ])

        return output.getvalue()

    @staticmethod
    def export_documents_to_json(documents: list[Document]) -> str:
        """Export document list to JSON format."""
        docs_data = []
        for doc in documents:
            tags = [tag.name for tag in doc.tags] if hasattr(doc, 'tags') and doc.tags else []
            docs_data.append({
                "id": doc.id,
                "title": doc.title,
                "source_type": doc.source_type,
                "status": doc.status,
                "file_size": doc.file_size,
                "page_count": doc.page_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                "tags": tags
            })

        export_data = {
            "documents": docs_data,
            "summary": {
                "total_documents": len(docs_data),
                "exported_at": datetime.now(timezone.utc).isoformat()
            }
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

    @staticmethod
    def export_batch_extractions_to_csv(db: Session, jobs: list[ExtractionJob]) -> str:
        """Export multiple extraction jobs to CSV format."""
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Job ID",
            "Paper ID",
            "Paper Title",
            "Query",
            "Field Name",
            "Content",
            "Evidence",
            "Confidence",
            "Evidence Type",
            "Figure ID",
            "Caption",
            "Image URL",
            "Page",
            "Notes",
            "Job Status",
            "Job Created At"
        ])

        for job in jobs:
            paper = db.get(Document, job.paper_id)
            paper_title = paper.title if paper else ""

            # Load assets for this job
            asset_ids = [r.source_id for r in job.results if r.source_id and r.source_type in {"asset", "figure", "table"}]
            assets_map = {}
            if asset_ids:
                assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
                assets_map = {a.id: a for a in assets}

            for result in sorted(job.results, key=lambda r: r.id):
                asset = assets_map.get(result.source_id) if result.source_id else None
                metadata = asset_metadata(asset)
                evidence_type = normalize_evidence_type(
                    source_type=result.source_type,
                    asset=asset,
                    metadata=metadata
                )
                image_url = asset_image_url(asset) if asset else ""
                page = asset.page_number if asset else None

                writer.writerow([
                    job.id,
                    job.paper_id,
                    paper_title,
                    job.query,
                    result.field_name,
                    result.content,
                    result.evidence,
                    result.confidence,
                    evidence_type,
                    result.figure_id or "",
                    result.caption or "",
                    image_url,
                    page or "",
                    result.notes or "",
                    job.status,
                    job.created_at.isoformat() if job.created_at else ""
                ])

        return output.getvalue()

    @staticmethod
    def export_batch_extractions_to_json(db: Session, jobs: list[ExtractionJob]) -> str:
        """Export multiple extraction jobs to JSON format."""
        jobs_data = []

        for job in jobs:
            paper = db.get(Document, job.paper_id)

            # Load assets for this job
            asset_ids = [r.source_id for r in job.results if r.source_id and r.source_type in {"asset", "figure", "table"}]
            assets_map = {}
            if asset_ids:
                assets = db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
                assets_map = {a.id: a for a in assets}

            results_data = []
            for result in sorted(job.results, key=lambda r: r.id):
                asset = assets_map.get(result.source_id) if result.source_id else None
                metadata = asset_metadata(asset)
                evidence_type = normalize_evidence_type(
                    source_type=result.source_type,
                    asset=asset,
                    metadata=metadata
                )

                results_data.append({
                    "id": result.id,
                    "field_name": result.field_name,
                    "content": result.content,
                    "evidence": result.evidence,
                    "confidence": result.confidence,
                    "evidence_type": evidence_type,
                    "source_type": result.source_type,
                    "source_id": result.source_id,
                    "figure_id": result.figure_id,
                    "caption": result.caption,
                    "image_url": asset_image_url(asset) if asset else None,
                    "page": asset.page_number if asset else None,
                    "notes": result.notes,
                    "created_at": result.created_at.isoformat() if result.created_at else None
                })

            jobs_data.append({
                "job_id": job.id,
                "paper_id": job.paper_id,
                "paper_title": paper.title if paper else "",
                "query": job.query,
                "status": job.status,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "results": results_data
            })

        export_data = {
            "jobs": jobs_data,
            "summary": {
                "total_jobs": len(jobs_data),
                "total_results": sum(len(j["results"]) for j in jobs_data),
                "exported_at": datetime.now(timezone.utc).isoformat()
            }
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

    @staticmethod
    def export_extraction_to_excel(db: Session, job: ExtractionJob, result_ids: list[int] | None = None) -> bytes:
        """Export extraction job results to Excel format (chart data).

        Args:
            db: Database session
            job: Extraction job to export
            result_ids: Optional list of result IDs to export. If None, exports all results.

        Returns:
            Excel file bytes
        """
        from app.services.agent.excel_exporter import ChartExcelExporter

        # Filter results if result_ids provided
        results = job.results
        if result_ids is not None:
            result_ids_set = set(result_ids)
            results = [r for r in results if r.id in result_ids_set]

        # 从 structured_data 重建 extraction_results 格式
        by_figure = {}
        for result in results:
            if not result.structured_data or not result.figure_id:
                continue

            # 解析 structured_data
            try:
                chart_data = json.loads(result.structured_data)
            except Exception:
                continue

            # 确保 chart_data 包含 chart_type
            if not isinstance(chart_data, dict):
                continue

            figure_id = result.figure_id
            if figure_id not in by_figure:
                by_figure[figure_id] = {
                    "figure_id": figure_id,
                    "chart_data": chart_data,
                    "extractions": []
                }
            else:
                # 如果已存在，使用最新的 chart_data
                by_figure[figure_id]["chart_data"] = chart_data

        extraction_results = {"by_figure": by_figure}

        # 获取文档标题
        paper = db.get(Document, job.paper_id)
        filename = paper.title if paper else f"extraction_{job.id}"

        # 导出
        exporter = ChartExcelExporter()
        return exporter.export(extraction_results, filename)
