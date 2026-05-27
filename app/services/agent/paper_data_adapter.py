from __future__ import annotations

import json

from app.models import Document, DocumentAsset, PaperTable
from app.services.agent.types import FigureInfo, PaperData
from app.services.file_storage import FileStorageService


class PaperDataAdapter:
    def __init__(self, file_storage: FileStorageService | None = None) -> None:
        self.file_storage = file_storage or FileStorageService()

    def build(self, *, paper: Document, figures: list[DocumentAsset], tables: list[PaperTable]) -> PaperData:
        content = paper.cleaned_text or paper.parsed_text or ""
        if tables:
            table_blocks = ["\n\n[Extracted Tables]"]
            for table in tables:
                table_blocks.append(f"\n{table.table_label}:\n{table.content}")
            content = f"{content}{''.join(table_blocks)}"
        return PaperData(
            paper_id=str(paper.id),
            title=paper.title,
            content=content,
            figures=[self._figure_info(asset) for asset in figures],
        )

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
        figure_id = f"{label} [asset:{asset.id}]"
        return FigureInfo(figure_id=figure_id, image_path=image_path, caption=caption, context=caption)
