from __future__ import annotations

from collections import deque
from threading import Condition


class TaskQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()#双端队列,先入先出
        self._condition = Condition()#生产者消费者模式,线程同步原语

    def enqueue(self, task_id: str) -> None:
        with self._condition:#自动加锁减锁
            self._items.append(task_id)
            self._condition.notify()#通知一个等待的线程,如果有的话,有新任务入队了
    def dequeue(self, block: bool = False, timeout: float | None = None) -> str | None:
        with self._condition:
            if not block:
                return self._items.popleft() if self._items else None

            if not self._items:
                self._condition.wait(timeout=timeout)
            return self._items.popleft() if self._items else None

    def size(self) -> int:
        with self._condition:
            return len(self._items)

    def snapshot(self) -> list[str]:
        with self._condition:
            return list(self._items)

    def remove_many(self, task_ids: list[str]) -> None:
        with self._condition:
            blocked = set(task_ids)
            self._items = deque(item for item in self._items if item not in blocked)
