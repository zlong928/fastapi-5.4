from __future__ import annotations

import logging
import signal
import sys
import time

from .core import config
config.ENABLE_BACKGROUND_WORKER = False#禁用    TaskService 内部的后台 Worker,改动增worker,typer,redis

from .core.config import ensure_runtime_dirs
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
    service = TaskService()
    logger.info("Worker started, waiting for tasks on Redis queue...")
    
    while not stop_requested:
        task_id = service._queue.dequeue(block=True, timeout=1.0)
        if task_id is None:
            continue
            
        logger.info(f"Picked up task {task_id}")
        try:
            record = service.process_task(task_id)
            logger.info(f"Finished task {record.task_id} with status {record.status}")
        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            
    logger.info("Worker stopped.")

if __name__ == "__main__":
    run_worker()
