"""
Redis-backed task queue with task-type dispatch support.

Queue naming convention:
- ``pdf_task_queue`` (default) — Document parsing tasks
- ``extraction_task_queue`` — Content extraction tasks
- ``batch_extraction_queue`` — Batch image extraction tasks

Usage:
    >>> from app.queue.redis_queue import RedisQueue
    >>> q = RedisQueue()

    # Enqueue a typed task (preferred)
    >>> q.enqueue({"task_type": "document_parse", "document_id": 1, "job_run_id": 1})

    # Enqueue a simple string
    >>> q.enqueue("task-id-123")

    # Dequeue
    >>> payload = q.dequeue(block=True, timeout=1.0)

    # Enqueue with explicit queue name
    >>> from app.core.config import EXTRACTION_QUEUE_NAME
    >>> q = RedisQueue(queue_name=EXTRACTION_QUEUE_NAME)
    >>> q.enqueue({"task_type": "extraction_run", "job_id": 42})
"""

from __future__ import annotations

import json
import logging

import redis

from app.core.config import DOCUMENT_QUEUE_NAME, REDIS_URL

logger = logging.getLogger(__name__)


# ── Task type registry ─────────────────────────────────────────────────

TASK_TYPE_DOCUMENT_PARSE = "document_parse"
TASK_TYPE_EXTRACTION = "extraction_run"
TASK_TYPE_BATCH_EXTRACTION = "batch_extraction"

TASK_QUEUE_MAP: dict[str, str] = {
    TASK_TYPE_DOCUMENT_PARSE: DOCUMENT_QUEUE_NAME,
    # extraction and batch extraction use their own queue names when instantiated
}

QUEUE_NAME_BY_TASK_TYPE: dict[str, str] = {
    TASK_TYPE_DOCUMENT_PARSE: DOCUMENT_QUEUE_NAME,
}


def get_queue_for_task_type(task_type: str, default_queue: str = DOCUMENT_QUEUE_NAME) -> str:
    """Resolve the queue name for a given task type."""
    return QUEUE_NAME_BY_TASK_TYPE.get(task_type, default_queue)


class RedisQueue:
    """A Redis-backed FIFO queue.

    Supports typed JSON payloads with task-type routing.
    """

    def __init__(self, queue_name: str | None = None) -> None:
        self.queue_name = queue_name or DOCUMENT_QUEUE_NAME
        self._redis = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
        )

    # ── Enqueue ───────────────────────────────────────────────────────

    def enqueue(self, payload: str | dict, task_data: dict | str | None = None) -> None:
        """Enqueue a task.

        Args:
            payload: Either the payload string/dict (if task_data is None),
                     or the queue name override (if task_data is provided).
            task_data: Optional task data; if provided, ``payload`` is treated
                      as the queue name override.
        """
        # Handle legacy two-argument signature: enqueue(queue_name, task_data)
        if task_data is not None:
            target_queue = str(payload or self.queue_name)
            data = task_data
        else:
            target_queue = self.queue_name
            data = payload

        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False)
        self._redis.rpush(target_queue, data)

    def enqueue_typed(self, task_type: str, data: dict) -> None:
        """Enqueue a typed task dict with automatic queue routing."""
        data["task_type"] = task_type
        target_queue = get_queue_for_task_type(task_type, self.queue_name)
        self._redis.rpush(target_queue, json.dumps(data, ensure_ascii=False))

    # ── Dequeue ───────────────────────────────────────────────────────

    def dequeue(self, block: bool = False, timeout: float | None = None) -> str | None:
        """Dequeue the next task from this queue."""
        if block:
            timeout_int = int(timeout) if timeout is not None else 0
            result = self._redis.blpop(self.queue_name, timeout=timeout_int)
            if result:
                return result[1]
            return None
        return self._redis.lpop(self.queue_name)

    # ── Introspection ──────────────────────────────────────────────────

    def size(self) -> int:
        """Get the current queue size."""
        return self._redis.llen(self.queue_name)

    def snapshot(self) -> list[str]:
        """Get all items in the queue (for inspection)."""
        return self._redis.lrange(self.queue_name, 0, -1)

    def remove_many(self, task_ids: list[str]) -> None:
        """Remove specific task IDs from the queue."""
        for task_id in task_ids:
            self._redis.lrem(self.queue_name, 0, task_id)

    async def async_dequeue(self, block: bool = False, timeout: float | None = None) -> str | None:
        """Async version of dequeue — runs blocking Redis call in executor."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.dequeue, block, timeout)
