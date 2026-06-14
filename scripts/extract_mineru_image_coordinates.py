from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.chart_extraction import process_mineru_image_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument("--content-list", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sample-limit", type=int, default=15)
    parser.add_argument("--image-path", type=Path, default=None)
    args = parser.parse_args()

    result = process_mineru_image_batch(
        images_dir=args.images_dir,
        content_list_path=args.content_list,
        out_dir=args.out_dir,
        sample_limit=args.sample_limit,
        image_path=args.image_path,
    )
    print(
        json.dumps(
            {
                "summary_path": str(result.summary_path),
                "combined_csv": str(result.combined_csv_path),
                "quality_audit": str(result.quality_audit_path),
                "manifest": str(result.manifest_path),
                "processed": result.processed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
