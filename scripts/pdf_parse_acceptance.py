from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.document_parser import ParsedDocument, DocumentParserService


def build_acceptance_report(parsed: ParsedDocument, pdf_path: Path) -> dict:
    profiles = [page.profile for page in parsed.pages if page.profile is not None]
    warnings: list[str] = []
    extraction_methods: dict[str, int] = {}
    element_counts: dict[str, int] = {}
    pages_with_bbox = 0

    for warning in parsed.warnings:
        if warning not in warnings:
            warnings.append(warning)

    for page in parsed.pages:
        page_has_bbox = False
        for warning in page.warnings:
            if warning not in warnings:
                warnings.append(warning)
        for element in page.elements:
            extraction_methods[element.extractor] = extraction_methods.get(element.extractor, 0) + 1
            element_counts[element.element_type] = element_counts.get(element.element_type, 0) + 1
            page_has_bbox = page_has_bbox or element.bbox is not None
        if page_has_bbox:
            pages_with_bbox += 1

    for profile in profiles:
        for warning in profile.warnings:
            if warning not in warnings:
                warnings.append(warning)

    pages_total = len(parsed.pages)
    pages_needing_ocr = [profile.page_number for profile in profiles if profile.needs_ocr]
    scanned_pages = [profile.page_number for profile in profiles if profile.is_scanned]
    bad_text_pages = [profile.page_number for profile in profiles if profile.bad_text_layer]
    text_chars_total = sum(profile.text_length for profile in profiles)
    word_count_total = sum(profile.word_count for profile in profiles)
    block_count_total = sum(profile.block_count for profile in profiles)
    image_block_count_total = sum(profile.image_block_count for profile in profiles)
    pages_text_extracted = len([profile for profile in profiles if profile.text_length > 0 and not profile.needs_ocr])

    if pages_total and len(pages_needing_ocr) / pages_total >= 0.5:
        warnings.append("acceptance_many_pages_need_ocr")
    if pages_total and pages_with_bbox < pages_total and parsed.parser_engine == "pymupdf":
        warnings.append("acceptance_some_pages_missing_bbox_elements")

    return {
        "file": str(pdf_path),
        "parser_engine": parsed.parser_engine,
        "pymupdf_available": parsed.pymupdf_available,
        "parser_version": parsed.parser_version,
        "pages_total": pages_total,
        "pages_text_extracted": pages_text_extracted,
        "pages_needing_ocr": pages_needing_ocr,
        "scanned_pages": scanned_pages,
        "bad_text_pages": bad_text_pages,
        "text_chars_total": text_chars_total,
        "word_count_total": word_count_total,
        "block_count_total": block_count_total,
        "image_block_count_total": image_block_count_total,
        "pages_with_bbox": pages_with_bbox,
        "extraction_methods": extraction_methods,
        "element_counts": element_counts,
        "table_extraction_enabled": parsed.table_extraction_enabled,
        "table_extraction_reason": parsed.table_extraction_reason,
        "warnings": warnings,
        "page_profiles": [
            {
                "page_number": profile.page_number,
                "text_length": profile.text_length,
                "word_count": profile.word_count,
                "block_count": profile.block_count,
                "image_block_count": profile.image_block_count,
                "image_count": profile.image_count,
                "is_scanned": profile.is_scanned,
                "bad_text_layer": profile.bad_text_layer,
                "needs_ocr": profile.needs_ocr,
                "extraction_method": profile.extraction_method,
                "warnings": profile.warnings,
            }
            for profile in profiles
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a PDF parsing acceptance report for a real PDF sample.")
    parser.add_argument("pdf_path", type=Path, help="Path to a PDF file inside the current environment.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = args.pdf_path
    if not pdf_path.exists():
        raise SystemExit(f"PDF file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise SystemExit(f"PDF path is not a file: {pdf_path}")

    parsed = DocumentParserService().parse_pdf_document(pdf_path)
    report = build_acceptance_report(parsed, pdf_path)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
