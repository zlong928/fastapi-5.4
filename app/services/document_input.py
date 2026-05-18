from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DocumentInput:
    page_content: str
    metadata: dict[str, object] = field(default_factory=dict)


def build_document_input(
    *,
    page_content: str,
    filename: str,
    file_id: int,
    source: str,
    content_type: str,
    created_by: int,
    extra_metadata: dict[str, object] | None = None,
) -> DocumentInput:
    metadata: dict[str, object] = {
        "filename": filename,
        "file_id": file_id,
        "source": source,
        "content_type": content_type,
        "created_by": created_by,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return DocumentInput(page_content=page_content, metadata=metadata)
