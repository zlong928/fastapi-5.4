from __future__ import annotations

import logging
import signal
import sys
import time

from .core import config
config.ENABLE_BACKGROUND_WORKER = False#禁用    TaskService 内部的后台 Worker,改动增worker,typer,redis

from .core.config import ensure_runtime_dirs
from .db.session import create_db_and_tables
from .queue.document_parse_queue import parse_document_parse_payload
from .services.document_parse_pipeline import DocumentParsePipeline
from .services.task_service import TaskService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker")

stop_requested = False

def handle_shutdown(signum, frame) -> None:#停机信号处理
    global stop_requested
    logger.info("Shutdown signal received. Stopping worker after current task...")
    stop_requested = True

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

def run_worker() -> None:#worker主循环
    ensure_runtime_dirs()
    create_db_and_tables()
    service = TaskService()
    document_pipeline = DocumentParsePipeline()
    logger.info("Worker started, waiting for tasks on Redis queue...")
    
    while not stop_requested:
        payload = service._queue.dequeue(block=True, timeout=1.0)
        if payload is None:
            continue
            
        logger.info(f"Picked up task {payload}")
        try:
            document_parse = parse_document_parse_payload(payload)
            if document_parse is not None:
                document_id, job_run_id = document_parse
                logger.info(
                    "Starting document parse document_id=%s job_run_id=%s",
                    document_id,
                    job_run_id,
                )
                document = document_pipeline.run(document_id, job_run_id=job_run_id)
                logger.info(
                    "Finished document parse document_id=%s job_run_id=%s status=%s",
                    document_id,
                    job_run_id,
                    document.status,
                )
                continue

            record = service.process_task(payload)
            logger.info(f"Finished task {record.task_id} with status {record.status}")
        except Exception as e:
            logger.exception(f"Error processing task {payload}: {e}")
            
    logger.info("Worker stopped.")

if __name__ == "__main__":
    run_worker()
