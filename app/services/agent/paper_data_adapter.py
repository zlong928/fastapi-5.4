from __future__ import annotations

import json
import re

from app.models import Document, DocumentAsset
from app.services.agent.types import FigureInfo, PaperData, TableInfo
from app.services.file_storage import FileStorageService


class PaperDataAdapter:
    def __init__(self, file_storage: FileStorageService | None = None) -> None:
        self.file_storage = file_storage or FileStorageService()

    def build(self, *, paper: Document, figures: list[DocumentAsset], tables: list[DocumentAsset]) -> PaperData:
        content = paper.cleaned_text or paper.parsed_text or ""
        structured_tables = [self._table_info(table) for table in tables]
        if tables:
            table_blocks = ["\n\n[Extracted Tables]"]
            for table in tables:
                label = table.label or f"Table {table.asset_index + 1 if table.asset_index is not None else table.id}"
                table_blocks.append(f"\n{label}:\n{table.markdown or table.text_content or table.ocr_text or ''}")
            content = f"{content}{''.join(table_blocks)}"
        return PaperData(
            paper_id=str(paper.id),
            title=paper.title,
            content=content,
            figures=[self._figure_info(asset) for asset in figures],
            tables=structured_tables,
        )

    def _table_info(self, asset: DocumentAsset) -> TableInfo:
        markdown = asset.markdown or asset.text_content or asset.ocr_text or ""
        label = asset.label or f"Table {asset.asset_index + 1 if asset.asset_index is not None else asset.id}"
        headers = self._parse_table_headers(markdown)
        row_count = self._count_table_rows(markdown)
        caption = asset.caption or ""
        return TableInfo(
            table_id=f"{label} [asset:{asset.id}]",
            label=label,
            page_number=asset.page_number,
            headers=headers,
            row_count=row_count,
            markdown=markdown,
            caption=caption,
        )

    def _parse_table_headers(self, markdown: str) -> list[str]:
        for line in markdown.splitlines():
            line = line.strip()
            if line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if cells and not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
                    return [cell for cell in cells if cell]
        return []

    def _count_table_rows(self, markdown: str) -> int:
        count = 0
        for line in markdown.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
                count += 1
        return max(0, count - 1)

    def _figure_info(self, asset: DocumentAsset) -> FigureInfo:
        metadata = {}
        if asset.metadata_json:
            try:
                metadata = json.loads(asset.metadata_json)
            except Exception:
                metadata = {}
        image_path = ""
        if asset.file_path:
            image_path = str(self.file_storage.get_file_path(asset.file_path))
        caption = str(metadata.get("caption") or "")
        label = str(metadata.get("figure_label") or f"Figure {asset.id}")
        source = str(metadata.get("source") or "")
        fallback = metadata.get("fallback", asset.asset_type == "page_snapshot")
        visual_role = self._visual_role(asset, metadata, source)
        context = str(metadata.get("context") or caption)
        role_note = self._visual_role_note(source, visual_role)
        if role_note:
            context = f"{context}\n{role_note}"
        context = (
            f"{context}\n"
            f"asset_type={asset.asset_type}; source={source}; fallback={fallback}; visual_role={visual_role}; "
            f"page_number={asset.page_number or ''}; figure_label={label}; caption={caption}"
        )
        figure_id = f"{label} [asset:{asset.id}]"
        return FigureInfo(figure_id=figure_id, image_path=image_path, caption=caption, context=context)

    def _visual_role(self, asset: DocumentAsset, metadata: dict, source: str) -> str:
        raw_role = metadata.get("visual_role")
        if raw_role:
            return str(raw_role)
        if source == "extracted_image":
            return "image_object"
        if source == "page_visual_snapshot":
            return "page_evidence"
        if asset.asset_type == "figure":
            return "figure_candidate"
        return source or "unknown"

    def _visual_role_note(self, source: str, visual_role: str) -> str:
        if source == "rendered_figure_region" or visual_role == "figure_candidate":
            return "Figure candidate produced from caption-guided page crop."
        if source == "page_visual_snapshot" or visual_role == "page_evidence":
            return "Page-level visual evidence; not a complete figure."
        if source == "extracted_image" or visual_role == "image_object":
            return "PDF image object; it may be a figure panel or image fragment."
        if source == "fallback_snapshot" or visual_role == "fallback_snapshot":
            return "Fallback snapshot; lowest-priority visual evidence."
        return ""
