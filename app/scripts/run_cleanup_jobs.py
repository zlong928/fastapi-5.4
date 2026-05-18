from __future__ import annotations

import logging

from app.core.config import ensure_runtime_dirs
from app.core.logging_config import configure_logging
from app.db.session import SessionLocal
from app.services.file_cleanup_service import FileCleanupService


def main() -> None:
    ensure_runtime_dirs()
    configure_logging()
    db = SessionLocal()
    try:
        processed = FileCleanupService(db).run_once()
    finally:
        db.close()
    logging.getLogger(__name__).info("Processed %s file cleanup jobs", processed)
    print(f"Processed {processed} file cleanup jobs.")


if __name__ == "__main__":
    main()
