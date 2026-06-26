from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class PropertyRecord:
    entity: str
    property_name: str
    property_category: str
    value_text: str
    value_numeric: float | None = None
    value_unit: str | None = None
    condition: str = ""
    method: str = ""
    confidence: float = 0.0
    source_type: str = ""
    source_ref: str = ""
    source_cell_range: str | None = None
    source_bbox: str | None = None
    source_char_span: tuple[int, int] | None = None
    source_mrf_node_id: str = ""
    source_page: int | None = None
    source_asset_id: int | None = None
    evidence_excerpt: str = ""
    evidence_payload: str | None = None
    extraction_method: str = ""
    verification_notes: str = ""

    def indicator(self) -> str:
        return f"{self.entity} - {self.property_name}"


DerivationType = Literal["extractive", "normalized", "computed", "inferred"]


@dataclass
class CandidateEvidence:
    """Evidence locator emitted during extraction.

    This is a typed transport object used by the pipeline before persisting
    into :class:`ExtractionEvidence`.
    """

    source_type: str
    mrf_node_id: str
    page: int | None = None
    section_id: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    caption_id: str | None = None
    char_span: tuple[int, int] | None = None
    cell_range: str | None = None
    bbox: str | None = None
    quote: str = ""
    evidence_role: str = "supporting"
    evidence_id: str | None = None
    payload: str | None = None


@dataclass
class ExtractionCandidate:
    """Structured candidate from a single extractor pass, before fusion/finality.

    This explicitly carries the fields needed for downstream validation,
    fusion and evidence-aware persistence.
    """

    field_name: str
    entity: str
    value: str
    unit: str | None = None
    normalized_value: float | str | None = None
    source_type: str = ""
    mrf_node_id: str = ""
    evidence_id: str = ""
    quote: str = ""
    cell_range: str | None = None
    bbox: str | None = None
    derivation_type: DerivationType = "extractive"
    confidence: float = 0.0
    source_ref: str = ""
    property_category: str = ""
    condition: str = ""
    method: str = ""
    status: str = "insufficient"
    support_reason: str = "not_validated"
    supporting_evidence: list[str] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    fusion_decision: str = ""
    write_to_final: bool = True
    evidence: CandidateEvidence | None = None

    def indicator(self) -> str:
        return f"{self.entity} - {self.field_name}"
