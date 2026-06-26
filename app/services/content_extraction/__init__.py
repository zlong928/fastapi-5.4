"""Content extraction pipeline — multi-source structured property extraction.

Extracts structured property records from MinerU-parsed document content
(sections, tables, captions, figures) using LLM understanding.
"""

from app.services.content_extraction.models import PropertyRecord
from app.services.content_extraction.contracts import (
    PropertyContract,
    register,
    get_contract,
    validate_unit,
    validate_numeric,
    CONTRACT_REGISTRY,
)
from app.services.content_extraction.fusion_engine import FusionEngine
from app.services.content_extraction.section_extractor import SectionExtractor
from app.services.content_extraction.table_extractor import TableExtractor
from app.services.content_extraction.caption_extractor import CaptionExtractor
from app.services.content_extraction.figure_extractor import FigureExtractor
from app.services.content_extraction.pipeline import ContentExtractionPipeline

__all__ = [
    "PropertyRecord",
    "PropertyContract",
    "register",
    "get_contract",
    "validate_unit",
    "validate_numeric",
    "CONTRACT_REGISTRY",
    "FusionEngine",
    "SectionExtractor",
    "TableExtractor",
    "CaptionExtractor",
    "FigureExtractor",
    "ContentExtractionPipeline",
]
