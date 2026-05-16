from __future__ import annotations

import json

from app.services.chunking_service import ChunkingService, estimate_tokens


def test_estimate_tokens_handles_common_text_shapes():
    assert estimate_tokens("") == 0
    assert estimate_tokens("DocumentParsePipeline uses Redis.") >= 3
    assert estimate_tokens("中文分块测试") > 0
    assert estimate_tokens("FastAPI 路由 /documents/upload stores file_123.") > 0


def test_markdown_headings_create_section_metadata():
    chunks = ChunkingService().chunk_document(
        "# Intro\n\nHello world.\n\n## Details\n\nDocumentParsePipeline uses Redis.",
        captions=[],
        references_text=None,
        target_tokens=20,
    )

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].heading == "Intro"
    assert chunks[0].section_path == ["Intro"]
    assert chunks[-1].metadata["section_path"] == ["Intro", "Details"]


def test_long_paragraph_splits_without_exceeding_max_or_looping():
    text = " ".join(f"word{i}" for i in range(1800))
    chunks = ChunkingService().chunk_document(
        text,
        captions=[],
        references_text=None,
        target_tokens=120,
        max_tokens=160,
        overlap_tokens=20,
    )

    assert len(chunks) > 5
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count <= 170 for chunk in chunks)


def test_references_split_common_formats():
    chunks = ChunkingService().chunk_document(
        cleaned_text="Body",
        captions=[],
        references_text="[1] Smith, A. Paper.\n[2] Brown, B. More.\n1. Clark, C. DOI:10.1/example",
    )
    references = [chunk for chunk in chunks if chunk.chunk_type == "reference"]

    assert len(references) == 3
    assert [chunk.metadata["reference_index"] for chunk in references] == [1, 2, 3]
    assert all(chunk.metadata["source"] == "reference" for chunk in references)


def test_captions_identify_figure_and_table_metadata():
    chunks = ChunkingService().chunk_document(
        cleaned_text="Body",
        captions=["Figure 1. Architecture.", "Table 2 Results.", "An unlabeled caption"],
        references_text=None,
    )
    captions = [chunk for chunk in chunks if chunk.chunk_type == "caption"]

    assert captions[0].metadata["caption_type"] == "figure"
    assert captions[0].metadata["label"] == "Figure 1"
    assert captions[1].metadata["caption_type"] == "table"
    assert captions[1].metadata["label"] == "Table 2"
    assert captions[2].metadata["caption_type"] == "unknown"


def test_ocr_long_text_splits_with_page_metadata():
    text = " ".join(f"ocr{i}" for i in range(900))
    chunks = ChunkingService().chunk_ocr_text(
        text,
        start_index=3,
        page_number=7,
        confidence=0.82,
        target_tokens=120,
        max_tokens=160,
        overlap_tokens=20,
    )

    assert len(chunks) > 1
    assert chunks[0].chunk_index == 3
    assert all(chunk.chunk_type == "ocr" for chunk in chunks)
    assert all(chunk.page_start == 7 and chunk.page_end == 7 for chunk in chunks)
    assert all(chunk.metadata["source"] == "ocr" for chunk in chunks)
    assert all(chunk.metadata["page_number"] == 7 for chunk in chunks)
    assert all(chunk.metadata["confidence"] == 0.82 for chunk in chunks)
