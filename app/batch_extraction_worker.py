"""
Async batch extraction worker.

架构：
- asyncio 事件循环驱动，单进程内高并发
- ThreadPoolExecutor 运行同步提取代码（OpenCV + httpx LLM 调用）
- asyncio.Semaphore 控制并发数（默认 20）
- 多进程部署可通过外部 supervisor 启动多个实例

性能设计：
- LLM_MAX_CONCURRENCY=100，每图平均 ~1.3 次 LLM 调用
- BATCH_CONCURRENCY=20/worker，5 个 worker 打满 100 路 LLM
- 超时通过 asyncio.wait_for 实现（配置 IMAGE_EXTRACT_TIMEOUT，默认 300s）
- 进度每 BATCH_PROGRESS_INTERVAL 秒输出一次
- 支持并行处理多个 job（BATCH_WORKER_MAX_JOBS，默认 3）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from concurrent.futures import ThreadPoolExecutor

from .core.config import (
    BATCH_CONCURRENCY,
    BATCH_EXTRACTION_QUEUE_NAME,
    BATCH_WORKER_MAX_JOBS,
    ensure_runtime_dirs,
)
from .db.session import create_db_and_tables, get_db
from .queue.redis_queue import RedisQueue
from .services.batch_extraction_service import BatchExtractionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("batch_extraction_worker")

stop_requested = False


def handle_shutdown(signum, frame) -> None:
    global stop_requested
    logger.info("Shutdown signal received. Stopping batch extraction worker...")
    stop_requested = True


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


async def run_worker_async() -> None:
    """Async worker main entrypoint."""
    ensure_runtime_dirs()
    create_db_and_tables()

    recover_db = next(get_db())
    try:
        recovered = BatchExtractionService(recover_db).recover_active_jobs()
        if recovered:
            logger.info(
                "Recovered %s active batch extraction jobs: %s",
                len(recovered),
                [job.id for job in recovered],
            )
    finally:
        recover_db.close()

    queue = RedisQueue(queue_name=BATCH_EXTRACTION_QUEUE_NAME)
    thread_pool_size = BATCH_WORKER_MAX_JOBS * BATCH_CONCURRENCY + 4
    thread_pool = ThreadPoolExecutor(
        max_workers=thread_pool_size,
        thread_name_prefix="batch_extract",
    )
    job_sem = asyncio.Semaphore(BATCH_WORKER_MAX_JOBS)
    active_tasks: set[asyncio.Task] = set()

    logger.info(
        "Async batch extraction worker started "
        "(concurrency=%d/job, max_jobs=%d, thread_pool=%d, timeout=%ds, queue=%s)",
        BATCH_CONCURRENCY,
        BATCH_WORKER_MAX_JOBS,
        thread_pool_size,
        int(os.getenv("IMAGE_EXTRACT_TIMEOUT", "300")),
        BATCH_EXTRACTION_QUEUE_NAME,
    )

    while not stop_requested:
        # 清理已完成的 task
        active_tasks.difference_update(t for t in list(active_tasks) if t.done())

        # 如果已达并发上限，等待一个 slot
        if len(active_tasks) >= BATCH_WORKER_MAX_JOBS:
            await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
            active_tasks.difference_update(t for t in list(active_tasks) if t.done())
            continue

        try:
            payload = await _async_dequeue(queue)
        except Exception:
            logger.exception("Error dequeuing from Redis")
            await asyncio.sleep(1)
            continue

        if payload is None:
            continue

        job_id = _parse_payload(payload)
        if job_id is None:
            continue

        task = asyncio.create_task(_process_job_with_semaphore(job_id, job_sem, thread_pool))
        active_tasks.add(task)
        logger.info("Job %d scheduled (active=%d)", job_id, len(active_tasks))

    # 等待所有活跃 job 完成
    if active_tasks:
        logger.info("Waiting for %d active jobs to finish...", len(active_tasks))
        await asyncio.gather(*active_tasks, return_exceptions=True)

    thread_pool.shutdown(wait=True)
    logger.info("Batch extraction worker stopped.")


async def _process_job_with_semaphore(
    job_id: int, sem: asyncio.Semaphore, thread_pool: ThreadPoolExecutor
) -> None:
    """获取信号量后处理单个 job。"""
    async with sem:
        db = next(get_db())
        try:
            service = BatchExtractionService(db)
            await service.async_process_job(job_id, thread_pool)
            logger.info("Async batch extraction job %d completed", job_id)
        except asyncio.CancelledError:
            logger.warning("Async batch extraction job %d cancelled", job_id)
        except Exception as exc:
            logger.exception("Error processing async batch extraction job %d: %s", job_id, exc)
        finally:
            db.close()


async def _async_dequeue(queue: RedisQueue) -> str | None:
    """非阻塞 dequeue 封装（通过 run_in_executor 避免卡住事件循环）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, queue.dequeue, True, 1.0)


def _parse_payload(payload: str) -> int | None:
    """解析队列消息，提取 job_id。"""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError:
        logger.warning("Failed to parse payload: %s", payload)
        return None

    if not isinstance(data, dict) or data.get("task_type") != "batch_extraction":
        logger.warning("Ignoring unknown payload: %s", data)
        return None

    job_id = data.get("job_id")
    if not job_id:
        logger.warning("Missing job_id in payload: %s", data)
        return None

    return int(job_id)


def run_worker() -> None:
    """同步入口（兼容旧版调用方）"""
    asyncio.run(run_worker_async())


if __name__ == "__main__":
    run_worker()
