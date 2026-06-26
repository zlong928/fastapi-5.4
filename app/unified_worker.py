"""
Unified worker — single entry point for all background processing.

Replaces the three separate workers (worker.py, extraction_worker.py,
batch_extraction_worker.py) with a single dispatcher.

Usage:
    python -m app.unified_worker document     # Document parsing
    python -m app.unified_worker extraction   # Content extraction
    python -m app.unified_worker batch        # Batch image extraction
    python -m app.unified_worker all          # All types (multi-threaded)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from typing import Callable

from app.core.config import (
    BATCH_EXTRACTION_QUEUE_NAME,
    EXTRACTION_QUEUE_NAME,
    ensure_runtime_dirs,
)
from app.db.session import create_db_and_tables
from app.queue.redis_queue import RedisQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("unified_worker")

stop_requested = False


def handle_shutdown(signum, frame) -> None:
    global stop_requested
    logger.info("Shutdown signal received. Stopping worker...")
    stop_requested = True


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ── Worker loops ───────────────────────────────────────────────────────


def _document_worker_loop(worker_name: str = "doc-worker") -> None:
    """Process document parsing tasks."""
    from app.queue.document_parse_queue import parse_document_parse_payload
    from app.services.document_parse_pipeline import DocumentParsePipeline
    from app.services.task_service import TaskService

    queue = RedisQueue()
    service = TaskService()
    pipeline = DocumentParsePipeline()
    logger.info("%s: waiting for document parse tasks...", worker_name)

    while not stop_requested:
        payload = queue.dequeue(block=True, timeout=1.0)
        if payload is None:
            continue

        logger.info("%s: picked up payload: %s", worker_name, str(payload)[:200])
        try:
            document_parse = parse_document_parse_payload(payload)
            if document_parse is not None:
                document_id, job_run_id = document_parse
                logger.info("%s: parsing document_id=%s job_run_id=%s", worker_name, document_id, job_run_id)
                document = pipeline.run(document_id, job_run_id=job_run_id)
                logger.info("%s: parsed document_id=%s status=%s", worker_name, document_id, document.status)
                continue

            record = service.process_task(payload)
            logger.info("%s: finished task %s status=%s", worker_name, record.task_id, record.status)
        except Exception as exc:
            logger.exception("%s: error processing payload: %s", worker_name, exc)


def _extraction_worker_loop(worker_name: str = "extract-worker") -> None:
    """Process content extraction tasks."""
    from app.queue.extraction_queue import parse_extraction_payload
    from app.services.extraction_job_service import run_extraction_job_by_id

    queue = RedisQueue(queue_name=EXTRACTION_QUEUE_NAME)
    logger.info("%s: waiting for extraction tasks on '%s'...", worker_name, EXTRACTION_QUEUE_NAME)

    while not stop_requested:
        payload = queue.dequeue(block=True, timeout=1.0)
        if payload is None:
            continue

        job_id = parse_extraction_payload(payload)
        if job_id is None:
            logger.warning("%s: unknown payload: %s", worker_name, str(payload)[:200])
            continue

        logger.info("%s: starting extraction job_id=%s", worker_name, job_id)
        try:
            run_extraction_job_by_id(job_id)
            logger.info("%s: finished extraction job_id=%s", worker_name, job_id)
        except Exception as exc:
            logger.exception("%s: error processing extraction job_id=%s: %s", worker_name, job_id, exc)


async def _batch_extraction_worker_loop(worker_name: str = "batch-worker") -> None:
    """Process batch image extraction tasks (async)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from app.core.config import BATCH_CONCURRENCY, BATCH_WORKER_MAX_JOBS
    from app.services.batch_extraction_service import BatchExtractionService

    queue = RedisQueue(queue_name=BATCH_EXTRACTION_QUEUE_NAME)
    thread_pool = ThreadPoolExecutor(
        max_workers=BATCH_WORKER_MAX_JOBS * BATCH_CONCURRENCY + 4,
        thread_name_prefix="batch_extract",
    )
    logger.info("%s: waiting for batch extraction tasks on '%s'...", worker_name, BATCH_EXTRACTION_QUEUE_NAME)

    while not stop_requested:
        try:
            payload = await _async_dequeue(queue)
        except Exception:
            logger.exception("%s: error dequeuing", worker_name)
            await asyncio.sleep(1)
            continue

        if payload is None:
            continue

        job_id = _parse_batch_payload(payload)
        if job_id is None:
            continue

        logger.info("%s: processing batch job_id=%s", worker_name, job_id)
        try:
            async with _get_db_session() as db:
                service = BatchExtractionService(db)
                await service.async_process_job(job_id, thread_pool)
            logger.info("%s: finished batch job_id=%s", worker_name, job_id)
        except Exception as exc:
            logger.exception("%s: error processing batch job_id=%s: %s", worker_name, job_id, exc)

    thread_pool.shutdown(wait=True)


def _parse_batch_payload(payload: str) -> int | None:
    """Parse batch extraction payload; return job_id or None."""
    import json
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError:
        logger.warning("Failed to parse batch payload: %s", str(payload)[:200])
        return None
    if not isinstance(data, dict) or data.get("task_type") != "batch_extraction":
        return None
    job_id = data.get("job_id")
    return int(job_id) if job_id else None


async def _async_dequeue(queue: RedisQueue) -> str | None:
    """Non-blocking dequeue via executor."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, queue.dequeue, True, 1.0)


# ── Context manager for DB sessions ────────────────────────────────────


from contextlib import asynccontextmanager as _asynccontextmanager


@_asynccontextmanager
async def _get_db_session():
    """Get a DB session for async use."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Thread-based concurrency for "all" mode ────────────────────────────


def _run_worker_in_thread(target: Callable, name: str, is_async: bool = False) -> threading.Thread:
    """Run a worker loop in a background thread."""
    import asyncio

    def wrapper():
        if is_async:
            asyncio.run(target(name))
        else:
            target(name)

    thread = threading.Thread(target=wrapper, name=f"worker-{name}", daemon=True)
    thread.start()
    return thread


# ── Entry point ─────────────────────────────────────────────────────────


def run_document_worker() -> None:
    """Run the document parsing worker (sync)."""
    ensure_runtime_dirs()
    create_db_and_tables()
    logger.info("Document worker started")
    _document_worker_loop()


def run_extraction_worker() -> None:
    """Run the content extraction worker (sync)."""
    ensure_runtime_dirs()
    create_db_and_tables()
    concurrency = _worker_concurrency("EXTRACTION_WORKER_CONCURRENCY")
    logger.info("Extraction worker started (concurrency=%s)", concurrency)
    if concurrency == 1:
        _extraction_worker_loop()
    else:
        threads = [
            threading.Thread(
                target=_extraction_worker_loop,
                args=(f"extract-worker-{i}",),
                daemon=False,
            )
            for i in range(1, concurrency + 1)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


def run_batch_worker() -> None:
    """Run the batch image extraction worker (async)."""
    import asyncio
    ensure_runtime_dirs()
    create_db_and_tables()

    # Recover interrupted jobs
    from app.services.batch_extraction_service import BatchExtractionService
    from app.db.session import get_db

    recover_db = next(get_db())
    try:
        recovered = BatchExtractionService(recover_db).recover_active_jobs()
        if recovered:
            logger.info("Recovered %s active batch jobs: %s", len(recovered), [j.id for j in recovered])
    finally:
        recover_db.close()

    logger.info("Batch extraction worker started")
    asyncio.run(_batch_extraction_worker_loop())


def run_all_workers() -> None:
    """Run all worker types concurrently (multi-threaded)."""
    ensure_runtime_dirs()
    create_db_and_tables()
    logger.info("Starting all workers...")

    threads = [
        _run_worker_in_thread(_document_worker_loop, "document"),
        _run_worker_in_thread(_extraction_worker_loop, "extraction"),
    ]
    # Batch worker uses asyncio — run in a separate thread
    import asyncio
    batch_thread = threading.Thread(
        target=lambda: asyncio.run(_batch_extraction_worker_loop("batch")),
        name="worker-batch",
        daemon=True,
    )
    batch_thread.start()
    threads.append(batch_thread)

    for t in threads:
        t.join()

    logger.info("All workers stopped.")


def _worker_concurrency(env_var: str = "EXTRACTION_WORKER_CONCURRENCY") -> int:
    try:
        value = int(os.getenv(env_var, "1"))
    except (TypeError, ValueError):
        return 1
    return max(1, min(value, 4))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Unified worker for background tasks")
    parser.add_argument(
        "worker_type",
        nargs="?",
        default="all",
        choices=["document", "extraction", "batch", "all"],
        help="Type of worker to run (default: all)",
    )
    args = parser.parse_args()

    worker_map = {
        "document": run_document_worker,
        "extraction": run_extraction_worker,
        "batch": run_batch_worker,
        "all": run_all_workers,
    }
    worker_map[args.worker_type]()


if __name__ == "__main__":
    main()
