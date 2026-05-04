from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import API_LOG_FILE, TASK_LOG_FILE, ensure_runtime_dirs


def _build_file_handler(log_file):
    ensure_runtime_dirs()
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    return handler


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_file_processing_configured", False):
        return

    api_logger = logging.getLogger("file_processing.api")
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False
    api_logger.handlers.clear()
    api_logger.addHandler(_build_file_handler(API_LOG_FILE))

    task_logger = logging.getLogger("file_processing.task")
    task_logger.setLevel(logging.INFO)
    task_logger.propagate = False
    task_logger.handlers.clear()
    task_logger.addHandler(_build_file_handler(TASK_LOG_FILE))

    root._file_processing_configured = True  # type: ignore[attr-defined]


def get_api_logger() -> logging.Logger:
    configure_logging()
    return logging.getLogger("file_processing.api")


def get_task_logger() -> logging.Logger:
    configure_logging()
    return logging.getLogger("file_processing.task")
