from __future__ import annotations

from dataclasses import dataclass, field

from app.models import DocumentAsset, PaperTable


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    text: str


@dataclass(slots=True)
class TextExtractionReport:
    pages: list[ParsedPage] = field(default_factory=list)
    text: str = ""
    status: str = "failed"
    message: str = ""


@dataclass(slots=True)
class FigureExtractionReport:
    assets: list[DocumentAsset] = field(default_factory=list)
    status: str = "failed"
    message: str = ""
    figure_count: int = 0
    snapshot_count: int = 0


@dataclass(slots=True)
class TableExtractionReport:
    tables: list[PaperTable] = field(default_factory=list)
    status: str = "failed"
    source: str = "none"
    message: str = ""
