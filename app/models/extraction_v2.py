"""New extraction models: extraction_runs, extraction_items, extraction_evidence.

These replace the old ``ExtractionJob`` / ``ExtractionResult`` as the canonical
source of truth for structured data extraction. The old models are kept as a
compatibility shell that projects from these new tables.

Architecture:
    extraction_runs  —— the top-level extraction run (one per user query per paper)
    extraction_items —— individual indicator/value pairs extracted
    extraction_evidence —— links each item to its source (figure, section, table)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import app_now
from app.db.session import Base

if TYPE_CHECKING:
    from app.models.document import Document, DocumentAsset


class ExtractionRun(Base):
    """A single structured extraction run against a paper.

    One run = one user query (e.g., "extract all rheology parameters").
    A run proceeds through phases: classification → routing → text extraction
    → figure extraction → fusion → done.
    """

    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id"), index=True, nullable=False
    )
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), default="pending", index=True, nullable=False
    )
    # Phases: pending → classifying → extracting_text → extracting_figures
    #         → fusing → done | failed
    phase: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # --- Classification results (LLM output) ---
    # JSON: [{"indicator": "...", "figures": ["Figure 1", ...], "sections": [...], ...}]
    classification_json: Mapped[str | None] = mapped_column(JSON, nullable=True)

    # --- Routing decisions ---
    # JSON: [{"figure_label": "Figure 1", "extractors": ["coordinate", "bar"], ...}]
    routing_json: Mapped[str | None] = mapped_column(JSON, nullable=True)

    # --- Summary ---
    # Human-readable summary of what was extracted
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Error tracking ---
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_phase: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: app_now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: app_now(),
        onupdate=lambda: app_now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Legacy link (for backward compatibility) ---
    legacy_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_jobs.id"), nullable=True
    )

    # --- Soft delete ---
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    paper: Mapped[Document] = relationship("Document")
    items: Mapped[list[ExtractionItem]] = relationship(
        "ExtractionItem", back_populates="run", cascade="all, delete-orphan"
    )


class ExtractionItem(Base):
    """A single extracted indicator/value from the paper.

    Each item represents one atomic fact:
    - A text-based indicator (e.g., "cell diameter: 10-40 µm")
    - A figure-based data point (e.g., "viscosity at shear rate 100 s⁻¹: 45 mPa·s")
    - A table row extracted as structured data
    """

    __tablename__ = "extraction_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_runs.id"), index=True, nullable=False
    )

    # --- What was extracted ---
    indicator: Mapped[str] = mapped_column(
        String(300), nullable=False
    )  # e.g., "零剪切粘度"
    value_text: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # human-readable: "45.2 ± 3.1 mPa·s"
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_unit: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )  # canonical unit: "mPa·s"
    value_error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # error bar description: "±3.1 (SD, n=3)"

    # --- Source classification ---
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )  # "figure" | "table" | "text" | "section" | "caption" | "fusion"
    extraction_method: Mapped[str | None] = mapped_column(
        String(60), nullable=True
    )  # "coordinate_extraction" | "bar_chart" | "text_llm" | "table_parse"

    # --- For figure-based items: axis & scale info ---
    figure_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    x_axis_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    x_axis_unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    x_axis_scale: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "linear" | "log10" | "log"
    y_axis_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    y_axis_unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    y_axis_scale: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- For coordinate data series ---
    series_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    series_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Structured data for coordinate points ---
    # JSON: [{"x": ..., "y": ..., "x_unit": ..., "y_unit": ...}, ...]
    data_points_json: Mapped[str | None] = mapped_column(JSON, nullable=True)

    # --- Confidence ---
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_breakdown: Mapped[str | None] = mapped_column(
        JSON, nullable=True
    )  # {"axis_calibration": 0.9, "ocr_quality": 0.8, ...}

    # --- LLM verification ---
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: app_now(), nullable=False
    )

    # Relationships
    run: Mapped[ExtractionRun] = relationship("ExtractionRun", back_populates="items")
    evidence: Mapped[list[ExtractionEvidence]] = relationship(
        "ExtractionEvidence", back_populates="item", cascade="all, delete-orphan"
    )


class ExtractionEvidence(Base):
    """Evidence linking an extracted item to its source in the paper.

    One item can have multiple pieces of evidence (e.g., a value that appears in
    both a figure and the text). Each evidence record points to the specific
    source and includes the relevant excerpt.
    """

    __tablename__ = "extraction_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_items.id"), index=True, nullable=False
    )

    # --- Source reference ---
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # "figure" | "table" | "text_chunk" | "section" | "caption" | "fusion"
    source_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # DocumentAsset.id or DocumentChunk.id
    source_label: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # "Figure 3", "Table 2", etc.

    # --- The actual evidence text ---
    excerpt: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # relevant text snippet
    excerpt_context: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # surrounding context

    # --- Page / location ---
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Evidence quality ---
    relevance: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 0-1 how relevant this evidence is

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: app_now(), nullable=False
    )

    # Relationships
    item: Mapped[ExtractionItem] = relationship(
        "ExtractionItem", back_populates="evidence"
    )
