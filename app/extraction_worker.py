from __future__ import annotations

import logging
import signal

from .core.config import EXTRACTION_QUEUE_NAME, ensure_runtime_dirs
from .db.session import create_db_and_tables
from .queue.extraction_queue import parse_extraction_payload
from .queue.redis_queue import RedisQueue
from .services.extraction_job_service import run_extraction_job_by_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("extraction_worker")

stop_requested = False


def handle_shutdown(signum, frame) -> None:
    global stop_requested
    logger.info("Shutdown signal received. Stopping extraction worker after current job...")
    stop_requested = True


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def run_worker() -> None:
    ensure_runtime_dirs()
    create_db_and_tables()
    queue = RedisQueue(queue_name=EXTRACTION_QUEUE_NAME)
    logger.info("Extraction worker started, waiting for jobs on Redis queue %s...", EXTRACTION_QUEUE_NAME)

    while not stop_requested:
        payload = queue.dequeue(block=True, timeout=1.0)
        if payload is None:
            continue

        job_id = parse_extraction_payload(payload)
        if job_id is None:
            logger.warning("Ignoring unknown extraction queue payload: %s", payload[:300])
            continue

        logger.info("Starting extraction job_id=%s", job_id)
        try:
            run_extraction_job_by_id(job_id)
            logger.info("Finished extraction job_id=%s", job_id)
        except Exception as exc:
            logger.exception("Error processing extraction job_id=%s: %s", job_id, exc)

    logger.info("Extraction worker stopped.")


if __name__ == "__main__":
    run_worker()
