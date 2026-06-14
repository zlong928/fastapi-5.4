from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import zipfile

import httpx

from app.core.config import RESULT_DIR
from app.services.mineru_parser import MinerUParserService


def save_result_artifacts(full_zip_url: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "result.zip"
    extract_dir = output_dir / "extracted"
    response = httpx.get(full_zip_url, timeout=120)
    response.raise_for_status()
    zip_path.write_bytes(response.content)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(extract_dir)
        extracted_files = [str(extract_dir / name) for name in archive.namelist() if not name.endswith("/")]
    return {
        "zip_path": str(zip_path),
        "extract_dir": str(extract_dir),
        "extracted_files": extracted_files,
    }


def build_report(pdf_path: Path, parser: MinerUParserService, output_root: Path) -> dict:
    result = parser.parse_pdf_file(pdf_path, data_id=f"acceptance-{pdf_path.stem[:64]}")
    parsed = result.parsed_document
    markdown = "\n\n".join(parsed.text_pages).strip()
    artifact_dir = output_root / result.batch_id
    artifact_report = save_result_artifacts(result.full_zip_url, artifact_dir)
    return {
        "file": str(pdf_path),
        "parser_engine": parsed.parser_engine,
        "parser_version": parsed.parser_version,
        "batch_id": result.batch_id,
        "mineru_file_name": result.file_name,
        "mineru_markdown_file": result.markdown_file,
        "full_zip_url": result.full_zip_url,
        **artifact_report,
        "pages_total": len(parsed.pages),
        "text_chars_total": len(markdown),
        "markdown_preview": markdown[:800],
        "element_counts": {
            "paragraph": sum(
                1
                for page in parsed.pages
                for element in page.elements
                if element.element_type == "paragraph"
            )
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real MinerU PDF parsing acceptance test.")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF file to parse.")
    parser.add_argument("--api-key-env", default="MINERU_API_KEY", help="Environment variable containing the MinerU API key.")
    parser.add_argument("--model-version", default=os.getenv("MINERU_MODEL_VERSION", "vlm"))
    parser.add_argument("--language", default=os.getenv("MINERU_LANGUAGE", "en"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.getenv("MINERU_TIMEOUT_SECONDS", "1800")))
    parser.add_argument("--poll-interval-seconds", type=float, default=float(os.getenv("MINERU_POLL_INTERVAL_SECONDS", "5")))
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "mineru", help="Directory where MinerU zip and extracted files are saved.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.pdf_path.is_file():
        raise SystemExit(f"PDF file not found: {args.pdf_path}")
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not configured.")
    parser = MinerUParserService(
        api_key=api_key,
        model_version=args.model_version,
        language=args.language,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    report = build_report(args.pdf_path, parser, args.output_dir)
    report_path = Path(report["extract_dir"]).parent / "report.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
