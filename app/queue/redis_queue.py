from __future__ import annotations

import redis
from ..core.config import DOCUMENT_QUEUE_NAME, REDIS_URL

class RedisQueue:
    def __init__(self, queue_name: str = DOCUMENT_QUEUE_NAME) -> None:
        self.queue_name = queue_name
        self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    def enqueue(self, task_id: str) -> None:
        self._redis.rpush(self.queue_name, task_id)

    def dequeue(self, block: bool = False, timeout: float | None = None) -> str | None:
        if block:
            timeout_int = int(timeout) if timeout is not None else 0
            result = self._redis.blpop(self.queue_name, timeout=timeout_int)
            if result:
                return result[1]
            return None
        else:
            return self._redis.lpop(self.queue_name)

    def size(self) -> int:
        return self._redis.llen(self.queue_name)

    def snapshot(self) -> list[str]:
        return self._redis.lrange(self.queue_name, 0, -1)

    def remove_many(self, task_ids: list[str]) -> None:
        for task_id in task_ids:
            self._redis.lrem(self.queue_name, 0, task_id)
