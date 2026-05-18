from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import CHUNK_MIN_SIZE_TARGET, CHUNK_OVERLAP, CHUNK_SIZE, TEXT_SPLITTER


@dataclass(slots=True)
class ChunkInput:
    chunk_type: str
    text: str
    cleaned_text: str
    chunk_index: int
    char_start: int | None = None
    char_end: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    heading: str | None = None
    section_path: list[str] = field(default_factory=list)
    token_count: int = 0
    metadata: dict = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk_chars = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_./:-]+", text))
    other_chars = len(re.sub(r"[\sA-Za-z0-9_./:\-\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", "", text))
    return max(1, latin_words + int((cjk_chars + 1) / 2) + int((other_chars + 3) / 4))


class ChunkingService:
    def chunk_document(
        self,
        cleaned_text: str,
        captions: list[str],
        references_text: str | None,
        target_tokens: int | None = None,
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
        min_size_target: int | None = None,
    ) -> list[ChunkInput]:
        target_tokens = target_tokens or CHUNK_SIZE
        max_tokens = max_tokens or max(target_tokens, int(target_tokens * 1.6))
        overlap_tokens = CHUNK_OVERLAP if overlap_tokens is None else overlap_tokens
        min_size_target = CHUNK_MIN_SIZE_TARGET if min_size_target is None else min_size_target
        chunks = self._chunk_body(cleaned_text, target_tokens, max_tokens, overlap_tokens)
        for caption in captions:
            chunks.append(self._build_caption_chunk(caption, len(chunks)))
        if references_text:
            for reference_index, reference in enumerate(self._split_references(references_text), start=1):
                chunks.append(
                    self._make_chunk(
                        chunk_type="reference",
                        text=reference,
                        chunk_index=len(chunks),
                        metadata={"source": "reference", "reference_index": reference_index},
                    )
                )
        return self._merge_small_chunks(chunks, min_size_target, max_tokens)

    def build_ocr_chunk(
        self,
        text: str,
        chunk_index: int,
        page_number: int | None = None,
        confidence: float | None = None,
    ) -> ChunkInput:
        chunks = self.chunk_ocr_text(text, chunk_index, page_number=page_number, confidence=confidence)
        return chunks[0] if chunks else self._make_chunk(
            chunk_type="ocr",
            text="",
            chunk_index=chunk_index,
            page_start=page_number,
            page_end=page_number,
            metadata={"source": "ocr", "page_number": page_number, "confidence": confidence},
        )

    def chunk_ocr_text(
        self,
        text: str,
        start_index: int = 0,
        page_number: int | None = None,
        confidence: float | None = None,
        target_tokens: int | None = None,
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
    ) -> list[ChunkInput]:
        target_tokens = target_tokens or CHUNK_SIZE
        max_tokens = max_tokens or max(target_tokens, int(target_tokens * 1.6))
        overlap_tokens = CHUNK_OVERLAP if overlap_tokens is None else overlap_tokens
        chunks = self._split_text_into_chunks(
            text=text,
            chunk_type="ocr",
            start_index=start_index,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            page_start=page_number,
            page_end=page_number,
            metadata={"source": "ocr", "page_number": page_number, "confidence": confidence},
        )
        return chunks

    def chunk_element_text(
        self,
        text: str,
        chunk_type: str,
        start_index: int,
        page_number: int | None,
        metadata: dict,
        target_tokens: int | None = None,
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
    ) -> list[ChunkInput]:
        target_tokens = target_tokens or CHUNK_SIZE
        max_tokens = max_tokens or max(target_tokens, int(target_tokens * 1.6))
        overlap_tokens = CHUNK_OVERLAP if overlap_tokens is None else overlap_tokens
        if chunk_type == "table":
            return [
                self._make_chunk(
                    chunk_type="table",
                    text=text,
                    chunk_index=start_index,
                    page_start=page_number,
                    page_end=page_number,
                    metadata=metadata,
                )
            ]
        return self._split_text_into_chunks(
            text=text,
            chunk_type=chunk_type,
            start_index=start_index,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            page_start=page_number,
            page_end=page_number,
            metadata=metadata,
        )

    def _chunk_body(
        self,
        text: str,
        target_tokens: int,
        max_tokens: int,
        overlap_tokens: int,
    ) -> list[ChunkInput]:
        if not text.strip():
            return []

        if TEXT_SPLITTER == "character":
            sections = [{"text": text, "char_start": 0, "heading": None, "section_path": []}]
        elif TEXT_SPLITTER == "token":
            sections = self._paragraph_sections(text)
        else:
            sections = self._markdown_sections(text)
        if TEXT_SPLITTER == "markdown_header" and len(sections) == 1 and not sections[0]["section_path"]:
            sections = self._paragraph_sections(text)

        chunks: list[ChunkInput] = []
        for section in sections:
            section_chunks = self._split_text_into_chunks(
                text=section["text"],
                chunk_type="body",
                start_index=len(chunks),
                target_tokens=target_tokens,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                char_offset=section["char_start"],
                heading=section["heading"],
                section_path=section["section_path"],
                metadata={"source": "body", "heading": section["heading"], "section_path": section["section_path"]},
            )
            chunks.extend(section_chunks)
        return chunks

    def _markdown_sections(self, text: str) -> list[dict]:
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
        matches = list(heading_pattern.finditer(text))
        if not matches:
            return [{"text": text, "char_start": 0, "heading": None, "section_path": []}]

        sections: list[dict] = []
        stack: list[str] = []
        for index, match in enumerate(matches):
            level = len(match.group(1))
            heading = match.group(2).strip()
            stack = stack[: level - 1]
            stack.append(heading)
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if section_text:
                sections.append(
                    {
                        "text": section_text,
                        "char_start": start,
                        "heading": heading,
                        "section_path": stack.copy(),
                    }
                )
        if matches[0].start() > 0:
            prefix = text[: matches[0].start()].strip()
            if prefix:
                sections.insert(0, {"text": prefix, "char_start": 0, "heading": None, "section_path": []})
        return sections

    def _paragraph_sections(self, text: str) -> list[dict]:
        sections: list[dict] = []
        for match in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
            paragraph = match.group(0).strip()
            if paragraph:
                sections.append({"text": paragraph, "char_start": match.start(), "heading": None, "section_path": []})
        return sections or [{"text": text, "char_start": 0, "heading": None, "section_path": []}]

    def _split_text_into_chunks(
        self,
        text: str,
        chunk_type: str,
        start_index: int,
        target_tokens: int,
        max_tokens: int,
        overlap_tokens: int,
        char_offset: int = 0,
        page_start: int | None = None,
        page_end: int | None = None,
        heading: str | None = None,
        section_path: list[str] | None = None,
        metadata: dict | None = None,
    ) -> list[ChunkInput]:
        units = self._split_units(text)
        chunks: list[ChunkInput] = []
        cursor = 0
        while cursor < len(units):
            start_cursor = cursor
            selected: list[tuple[str, int, int]] = []
            token_total = 0
            while cursor < len(units):
                unit_text, unit_start, unit_end = units[cursor]
                unit_tokens = estimate_tokens(unit_text)
                if selected and token_total + unit_tokens > target_tokens:
                    break
                if not selected and unit_tokens > max_tokens:
                    hard_chunks = self._hard_split(
                        unit_text,
                        start_index + len(chunks),
                        max_tokens,
                        chunk_type,
                        char_offset + unit_start,
                        page_start,
                        page_end,
                        heading,
                        section_path or [],
                        metadata or {},
                    )
                    chunks.extend(hard_chunks)
                    cursor += 1
                    break
                selected.append((unit_text, unit_start, unit_end))
                token_total += unit_tokens
                cursor += 1
                if token_total >= target_tokens:
                    break

            if selected:
                chunk_text = "\n\n".join(unit[0].strip() for unit in selected if unit[0].strip()).strip()
                chunks.append(
                    self._make_chunk(
                        chunk_type=chunk_type,
                        text=chunk_text,
                        chunk_index=start_index + len(chunks),
                        char_start=char_offset + selected[0][1],
                        char_end=char_offset + selected[-1][2],
                        page_start=page_start,
                        page_end=page_end,
                        heading=heading,
                        section_path=section_path or [],
                        metadata=metadata or {},
                    )
                )

            if cursor <= start_cursor:
                cursor = start_cursor + 1
                continue
            if cursor >= len(units):
                break
            if overlap_tokens > 0:
                overlap_cursor = cursor
                overlap_total = 0
                while overlap_cursor > start_cursor:
                    previous_tokens = estimate_tokens(units[overlap_cursor - 1][0])
                    if overlap_total + previous_tokens > overlap_tokens:
                        break
                    overlap_total += previous_tokens
                    overlap_cursor -= 1
                if start_cursor < overlap_cursor < cursor:
                    cursor = overlap_cursor
        return chunks

    def _split_units(self, text: str) -> list[tuple[str, int, int]]:
        paragraphs = [(m.group(0).strip(), m.start(), m.end()) for m in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", text, re.DOTALL)]
        if len(paragraphs) > 1:
            return paragraphs
        sentence_matches = list(re.finditer(r"[^。！？.!?]+[。！？.!?]?", text))
        units = [(m.group(0).strip(), m.start(), m.end()) for m in sentence_matches if m.group(0).strip()]
        return units or [(text.strip(), 0, len(text))]

    def _hard_split(
        self,
        text: str,
        start_index: int,
        max_tokens: int,
        chunk_type: str,
        char_offset: int,
        page_start: int | None,
        page_end: int | None,
        heading: str | None,
        section_path: list[str],
        metadata: dict,
    ) -> list[ChunkInput]:
        words = re.findall(r"\S+", text)
        if not words:
            return []
        chunks: list[ChunkInput] = []
        current: list[str] = []
        current_start = 0
        char_cursor = 0
        for word in words:
            proposed = " ".join([*current, word])
            if current and estimate_tokens(proposed) > max_tokens:
                chunk_text = " ".join(current)
                chunks.append(
                    self._make_chunk(
                        chunk_type=chunk_type,
                        text=chunk_text,
                        chunk_index=start_index + len(chunks),
                        char_start=char_offset + current_start,
                        char_end=char_offset + current_start + len(chunk_text),
                        page_start=page_start,
                        page_end=page_end,
                        heading=heading,
                        section_path=section_path,
                        metadata={**metadata, "quality_flags": ["hard_split"]},
                        quality_flags=["hard_split"],
                    )
                )
                current_start = char_cursor
                current = [word]
            else:
                if not current:
                    current_start = char_cursor
                current.append(word)
            char_cursor += len(word) + 1
        if current:
            chunk_text = " ".join(current)
            chunks.append(
                self._make_chunk(
                    chunk_type=chunk_type,
                    text=chunk_text,
                    chunk_index=start_index + len(chunks),
                    char_start=char_offset + current_start,
                    char_end=char_offset + current_start + len(chunk_text),
                    page_start=page_start,
                    page_end=page_end,
                    heading=heading,
                    section_path=section_path,
                    metadata={**metadata, "quality_flags": ["hard_split"]},
                    quality_flags=["hard_split"],
                )
            )
        return chunks

    def _build_caption_chunk(self, caption: str, chunk_index: int) -> ChunkInput:
        label_match = re.search(r"\b(Figure|Fig\.|Table)\s*([0-9]+[A-Za-z]?)", caption, re.IGNORECASE)
        caption_type = "unknown"
        label = None
        if label_match:
            label_kind = label_match.group(1).lower()
            caption_type = "table" if label_kind == "table" else "figure"
            label_prefix = "Table" if caption_type == "table" else "Figure"
            label = f"{label_prefix} {label_match.group(2)}"
        return self._make_chunk(
            chunk_type="caption",
            text=caption,
            chunk_index=chunk_index,
            metadata={"source": "caption", "caption_type": caption_type, "label": label},
        )

    def _make_chunk(
        self,
        chunk_type: str,
        text: str,
        chunk_index: int,
        char_start: int | None = None,
        char_end: int | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        heading: str | None = None,
        section_path: list[str] | None = None,
        metadata: dict | None = None,
        quality_flags: list[str] | None = None,
    ) -> ChunkInput:
        cleaned_text = text.strip()
        flags = quality_flags or []
        full_metadata = dict(metadata or {})
        if heading:
            full_metadata["heading"] = heading
        if section_path:
            full_metadata["section_path"] = section_path
        if flags:
            full_metadata["quality_flags"] = flags
        full_metadata["start_index"] = char_start
        full_metadata["text_splitter"] = TEXT_SPLITTER
        return ChunkInput(
            chunk_type=chunk_type,
            text=cleaned_text,
            cleaned_text=cleaned_text,
            chunk_index=chunk_index,
            char_start=char_start,
            char_end=char_end,
            page_start=page_start,
            page_end=page_end,
            heading=heading,
            section_path=section_path or [],
            token_count=estimate_tokens(cleaned_text),
            metadata=full_metadata,
            quality_flags=flags,
        )

    def _split_references(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        expanded_lines: list[str] = []
        inline_marker = re.compile(r"(?=(?:\[\d+\]|\d+\.)\s+)")
        for line in lines:
            starts = [match.start() for match in inline_marker.finditer(line)]
            if len(starts) > 1:
                starts.append(len(line))
                expanded_lines.extend(line[starts[index] : starts[index + 1]].strip() for index in range(len(starts) - 1))
            else:
                expanded_lines.append(line)
        lines = [line for line in expanded_lines if line]
        references: list[str] = []
        current: list[str] = []
        marker = re.compile(r"^(\[\d+\]|\d+\.)\s+")
        standalone = re.compile(r"(doi:|https?://|arxiv:)", re.IGNORECASE)
        for line in lines:
            starts_new = bool(marker.match(line)) or (bool(standalone.search(line)) and bool(current))
            if starts_new and current:
                references.append(" ".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            references.append(" ".join(current).strip())
        return references

    def _merge_small_chunks(
        self,
        chunks: list[ChunkInput],
        min_size_target: int,
        max_tokens: int,
    ) -> list[ChunkInput]:
        if min_size_target <= 0 or len(chunks) < 2:
            return chunks
        merged: list[ChunkInput] = []
        cursor = 0
        while cursor < len(chunks):
            current = chunks[cursor]
            if current.token_count >= min_size_target or cursor + 1 >= len(chunks):
                merged.append(current)
                cursor += 1
                continue
            nxt = chunks[cursor + 1]
            mergeable_type = current.chunk_type in {"body", "ocr", "ocr_text"}
            same_scope = (
                mergeable_type
                and current.chunk_type == nxt.chunk_type
                and current.page_start == nxt.page_start
                and current.page_end == nxt.page_end
                and current.section_path == nxt.section_path
                and current.metadata.get("file_id") == nxt.metadata.get("file_id")
            )
            combined_text = f"{current.cleaned_text}\n\n{nxt.cleaned_text}".strip()
            if same_scope and estimate_tokens(combined_text) <= max_tokens:
                metadata = {**nxt.metadata, **current.metadata, "merged_small_chunk": True}
                merged.append(
                    self._make_chunk(
                        chunk_type=current.chunk_type,
                        text=combined_text,
                        chunk_index=current.chunk_index,
                        char_start=current.char_start,
                        char_end=nxt.char_end,
                        page_start=current.page_start,
                        page_end=current.page_end,
                        heading=current.heading or nxt.heading,
                        section_path=current.section_path or nxt.section_path,
                        metadata=metadata,
                        quality_flags=list({*current.quality_flags, *nxt.quality_flags, "merged_small_chunk"}),
                    )
                )
                cursor += 2
                continue
            merged.append(current)
            cursor += 1
        for index, chunk in enumerate(merged):
            chunk.chunk_index = index
            chunk.metadata["chunk_index"] = index
        return merged
