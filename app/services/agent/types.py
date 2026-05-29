from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TableInfo:
    table_id: str
    label: str
    page_number: int | None
    headers: list[str]
    row_count: int
    markdown: str
    caption: str = ""


@dataclass
class FigureInfo:
    figure_id: str
    image_path: str
    caption: str
    context: str


@dataclass
class ExtractionTask:
    metric_name: str
    text_context: str
    specific_instruction: str = ""


@dataclass
class FigureExtractionPlan:
    figure_id: str
    image_path: str
    caption: str
    tasks: list[ExtractionTask] = field(default_factory=list)
    review_notes: str = ""


@dataclass
class ExtractionMap:
    figures: dict[str, FigureExtractionPlan] = field(default_factory=dict)
    text_only_metrics: list[dict] = field(default_factory=list)


@dataclass
class PaperData:
    paper_id: str
    title: str
    content: str
    figures: list[FigureInfo] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)


@dataclass
class SupervisorState:
    mapping_adjusted: bool = False
    visual_retries: dict[str, int] = field(default_factory=dict)
    reflection_notes: list[dict] = field(default_factory=list)
