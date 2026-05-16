from dataclasses import dataclass, field
from pathlib import Path
import re

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import fitz
except ImportError:
    fitz = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


@dataclass(slots=True)
class PdfPageProfile:
    page_number: int
    text_length: int
    word_count: int
    block_count: int
    image_block_count: int
    image_count: int
    is_scanned: bool
    bad_text_layer: bool
    needs_ocr: bool
    extraction_method: str
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedElement:
    element_type: str
    text: str
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    extractor: str = "unknown"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ParsedPage:
    page_number: int
    profile: PdfPageProfile | None
    elements: list[ParsedElement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedDocument:
    pages: list[ParsedPage]
    source_type: str
    parser_version: str = "pdf_profile_v1"
    parser_engine: str = "unknown"
    pymupdf_available: bool = False
    table_extraction_enabled: bool = False
    table_extraction_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def text_pages(self) -> list[str]:
        return [
            "\n\n".join(element.text for element in page.elements if element.text.strip())
            for page in self.pages
        ]


class DocumentParserService:
    """文档解析服务，支持 PDF, Markdown, TXT 格式。"""

    @staticmethod
    def parse_pdf(file_path: str | Path) -> str:
        """解析 PDF 文件。

        Args:
            file_path: PDF 文件路径

        Returns:
            str: 提取的文本

        Raises:
            ImportError: 如果未安装 pypdf
            ValueError: 如果 PDF 格式错误
        """
        if pypdf is None:
            raise ImportError("pypdf is not installed. Install it with: pip install pypdf")

        try:
            return "\n--- Page Break ---\n".join(DocumentParserService.parse_pdf_pages(file_path)).strip()
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}")

    @staticmethod
    def parse_pdf_pages(file_path: str | Path) -> list[str]:
        if pypdf is None:
            raise ImportError("pypdf is not installed. Install it with: pip install pypdf")

        pages: list[str] = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                pages.append(page.extract_text() or "")
        return pages

    def parse_pdf_document(self, file_path: str | Path) -> ParsedDocument:
        if fitz is not None:
            return self._parse_pdf_document_with_pymupdf(file_path)
        return self._parse_pdf_document_with_pypdf(
            file_path,
            warnings=["pymupdf_unavailable: falling back to pypdf"],
        )

    def profile_pdf_pages(self, file_path: str | Path) -> list[PdfPageProfile]:
        parsed = self.parse_pdf_document(file_path)
        return [page.profile for page in parsed.pages if page.profile is not None]

    def _parse_pdf_document_with_pymupdf(self, file_path: str | Path) -> ParsedDocument:
        pages: list[ParsedPage] = []
        table_extraction_enabled = False
        table_reason = "pdfplumber is not installed; table extraction is disabled."

        with fitz.open(file_path) as doc:
            for page_index, page in enumerate(doc, start=1):
                text_blocks, image_blocks = self._pymupdf_blocks(page)
                if not text_blocks:
                    text_blocks = self._pymupdf_words_as_blocks(page)
                plain_text = "\n\n".join(block["text"] for block in text_blocks if block["text"].strip())
                image_count = len(page.get_images(full=True))
                image_block_count = len(image_blocks)
                profile = self._build_profile(
                    page_number=page_index,
                    text=plain_text,
                    block_count=len(text_blocks),
                    image_block_count=image_block_count,
                    image_count=image_count,
                )
                elements = []
                for block in sorted(text_blocks, key=lambda item: (item["bbox"][1], item["bbox"][0])):
                    if not block["text"].strip():
                        continue
                    elements.append(
                        ParsedElement(
                            element_type="paragraph",
                            text=block["text"],
                            page_number=page_index,
                            bbox=block["bbox"],
                            extractor="pymupdf",
                            metadata={
                                "block_index": block["block_index"],
                                "source_type": "pdf",
                                "parser_engine": "pymupdf",
                            },
                        )
                    )
                for image_index, image_block in enumerate(image_blocks, start=1):
                    elements.append(
                        ParsedElement(
                            element_type="image",
                            text="",
                            page_number=page_index,
                            bbox=image_block["bbox"],
                            extractor="pymupdf",
                            metadata={
                                "image_index": image_index,
                                "source_type": "pdf",
                                "parser_engine": "pymupdf",
                            },
                        )
                    )
                pages.append(ParsedPage(page_number=page_index, profile=profile, elements=elements, warnings=profile.warnings.copy()))

        if pdfplumber is not None:
            table_extraction_enabled = True
            table_reason = None
            self._append_pdfplumber_tables(file_path, pages)

        return ParsedDocument(
            pages=pages,
            source_type="pdf",
            parser_engine="pymupdf",
            pymupdf_available=True,
            table_extraction_enabled=table_extraction_enabled,
            table_extraction_reason=table_reason,
        )

    def _parse_pdf_document_with_pypdf(self, file_path: str | Path, warnings: list[str] | None = None) -> ParsedDocument:
        if pypdf is None:
            raise ImportError("pypdf is not installed. Install it with: pip install pypdf")

        pages: list[ParsedPage] = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page_index, page in enumerate(reader.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                image_count = self._pypdf_image_count(page)
                profile = self._build_profile(
                    page_number=page_index,
                    text=text,
                    block_count=1 if text.strip() else 0,
                    image_block_count=0,
                    image_count=image_count,
                )
                elements = []
                if text.strip():
                    elements.append(
                        ParsedElement(
                            element_type="paragraph",
                            text=text.strip(),
                            page_number=page_index,
                            extractor="pypdf",
                            metadata={"source_type": "pdf", "fallback_parser": "pypdf", "parser_engine": "pypdf"},
                        )
                    )
                page_warnings = profile.warnings.copy()
                if warnings:
                    page_warnings.extend(warnings)
                pages.append(ParsedPage(page_number=page_index, profile=profile, elements=elements, warnings=page_warnings))

        return ParsedDocument(
            pages=pages,
            source_type="pdf",
            parser_engine="pypdf",
            pymupdf_available=False,
            table_extraction_enabled=False,
            table_extraction_reason="PyMuPDF/pdfplumber are not installed; using pypdf text extraction only.",
            warnings=warnings or [],
        )

    def _pymupdf_blocks(self, page) -> tuple[list[dict], list[dict]]:
        text_blocks = []
        image_blocks = []
        for block in page.get_text("blocks", sort=True):
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[:5]
            block_type = block[6] if len(block) > 6 else 0
            bbox = (float(x0), float(y0), float(x1), float(y1))
            if block_type == 1:
                image_blocks.append({"bbox": bbox, "block_index": len(image_blocks)})
                continue
            if block_type != 0 or not str(text).strip():
                continue
            text_blocks.append(
                {
                    "bbox": bbox,
                    "text": str(text).strip(),
                    "block_index": len(text_blocks),
                }
            )
        return text_blocks, image_blocks

    def _pymupdf_words_as_blocks(self, page) -> list[dict]:
        words = page.get_text("words", sort=True)
        if not words:
            return []
        lines: dict[tuple[int, int, int], list[tuple]] = {}
        for word in words:
            if len(word) < 5:
                continue
            x0, y0, x1, y1, text = word[:5]
            block_no = int(word[5]) if len(word) > 5 else 0
            line_no = int(word[6]) if len(word) > 6 else int(float(y0) // 5)
            key = (block_no, line_no, int(float(y0) // 5))
            lines.setdefault(key, []).append((float(x0), float(y0), float(x1), float(y1), str(text)))
        blocks = []
        for words_in_line in lines.values():
            ordered = sorted(words_in_line, key=lambda item: item[0])
            text = " ".join(item[4] for item in ordered).strip()
            if not text:
                continue
            blocks.append(
                {
                    "bbox": (
                        min(item[0] for item in ordered),
                        min(item[1] for item in ordered),
                        max(item[2] for item in ordered),
                        max(item[3] for item in ordered),
                    ),
                    "text": text,
                    "block_index": len(blocks),
                }
            )
        return sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0]))

    def _append_pdfplumber_tables(self, file_path: str | Path, pages: list[ParsedPage]) -> None:
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    if page_index > len(pages):
                        continue
                    for table_index, table in enumerate(page.extract_tables() or [], start=1):
                        markdown = self._table_to_markdown(table)
                        if not markdown:
                            continue
                        row_count = len(table)
                        column_count = max((len(row or []) for row in table), default=0)
                        pages[page_index - 1].elements.append(
                            ParsedElement(
                                element_type="table",
                                text=markdown,
                                page_number=page_index,
                                extractor="table",
                                metadata={
                                    "source_type": "pdf",
                                    "table_index": table_index,
                                    "row_count": row_count,
                                    "column_count": column_count,
                                },
                            )
                        )
        except Exception as exc:
            warning = f"table_extraction_failed: {type(exc).__name__}: {exc}"
            for page in pages:
                page.warnings.append(warning)
                if page.profile:
                    page.profile.warnings.append(warning)

    def _table_to_markdown(self, table: list[list[str | None]] | None) -> str:
        if not table:
            return ""
        rows = [["" if cell is None else re.sub(r"\s+", " ", str(cell)).strip() for cell in row] for row in table if row]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header = rows[0]
        separator = ["---"] * width
        body = rows[1:]
        markdown_rows = [header, separator, *body]
        return "\n".join("| " + " | ".join(row) + " |" for row in markdown_rows).strip()

    def _build_profile(
        self,
        page_number: int,
        text: str,
        block_count: int,
        image_block_count: int,
        image_count: int,
    ) -> PdfPageProfile:
        stripped = text.strip()
        text_length = len(stripped)
        word_count = len(re.findall(r"\w+", stripped))
        replacement_chars = stripped.count("\ufffd")
        odd_chars = len(re.findall(r"[^\w\s.,;:!?()\[\]{}<>/@#$%^&*+=|\\'\"`~\-\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", stripped))
        bad_char_ratio = (replacement_chars + odd_chars) / max(1, text_length)
        whitespace_ratio = sum(1 for char in text if char.isspace()) / max(1, len(text))
        warnings: list[str] = []
        is_scanned = word_count < 5 and image_count > 0
        bad_text_layer = bool(stripped) and (bad_char_ratio > 0.08 or whitespace_ratio > 0.55)
        needs_ocr = text_length < 30 or word_count < 5 or bad_text_layer or is_scanned
        if not stripped:
            warnings.append("empty_text")
        elif text_length < 30:
            warnings.append("very_short_text")
        if is_scanned:
            warnings.append("suspected_scanned_page")
        if bad_text_layer:
            warnings.append("suspected_bad_text_layer")
        if self._looks_layout_complex(block_count=block_count, text=text):
            warnings.append("layout_complex_possible_multicolumn")
        return PdfPageProfile(
            page_number=page_number,
            text_length=text_length,
            word_count=word_count,
            block_count=block_count,
            image_block_count=image_block_count,
            image_count=image_count,
            is_scanned=is_scanned,
            bad_text_layer=bad_text_layer,
            needs_ocr=needs_ocr,
            extraction_method="ocr" if needs_ocr else "pdf_text",
            warnings=warnings,
        )

    def _looks_layout_complex(self, block_count: int, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        short_lines = sum(1 for line in lines if 20 <= len(line) <= 80)
        return block_count >= 8 and len(lines) >= 8 and short_lines / max(1, len(lines)) > 0.6

    def _pypdf_image_count(self, page) -> int:
        try:
            xobjects = page.get("/Resources", {}).get("/XObject", {})
            count = 0
            for obj in xobjects.values():
                resolved = obj.get_object() if hasattr(obj, "get_object") else obj
                if resolved.get("/Subtype") == "/Image":
                    count += 1
            return count
        except Exception:
            return 0

    @staticmethod
    def parse_markdown(file_path: str | Path) -> str:
        """解析 Markdown 文件。

        Args:
            file_path: Markdown 文件路径

        Returns:
            str: 文件内容

        Raises:
            ValueError: 如果文件格式错误
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode Markdown file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse Markdown: {e}")

    @staticmethod
    def parse_txt(file_path: str | Path) -> str:
        """解析 TXT 文件。

        Args:
            file_path: TXT 文件路径

        Returns:
            str: 文件内容

        Raises:
            ValueError: 如果文件格式错误
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode TXT file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse TXT: {e}")

    @staticmethod
    def parse(file_path: str | Path, source_type: str) -> str:
        """根据文件类型解析文件。

        Args:
            file_path: 文件路径
            source_type: 文件类型 (pdf, markdown, txt)

        Returns:
            str: 提取的文本

        Raises:
            ValueError: 如果文件类型不支持或解析失败
        """
        source_type = source_type.lower()

        if source_type == "pdf":
            return DocumentParserService.parse_pdf(file_path)
        elif source_type in ("markdown", "md"):
            return DocumentParserService.parse_markdown(file_path)
        elif source_type == "txt":
            return DocumentParserService.parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {source_type}")
