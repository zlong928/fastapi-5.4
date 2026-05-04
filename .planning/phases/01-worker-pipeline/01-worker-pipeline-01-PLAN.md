---
phase: 01-worker-pipeline
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: ["requirements.txt", "app/core/config.py", "app/queue/redis_queue.py", "app/services/task_service.py"]
autonomous: true
requirements: ["REDIS-01"]
user_setup:
  - service: redis
    why: "Task routing requires Redis"
must_haves:
  truths:
    - "Redis can be used to enqueue and dequeue tasks"
    - "TaskService uses Redis for task routing when configured"
  artifacts:
    - path: "app/queue/redis_queue.py"
      provides: "Redis based task queue"
  key_links:
    - from: "app/services/task_service.py"
      to: "app/queue/redis_queue.py"
      via: "task queueing"
---

<objective>
Implement Redis queue and integrate it into TaskService.
Purpose: Replace in-memory queue with robust Redis-based task routing.
Output: Redis queue implementation and updated TaskService.
</objective>

<context>
@app/queue/task_queue.py
@app/services/task_service.py
@app/core/config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add Redis dependency</name>
  <files>requirements.txt</files>
  <action>Add `redis==5.0.3` to requirements.txt.</action>
  <verify>
    <automated>grep redis requirements.txt</automated>
  </verify>
  <done>redis is in requirements.txt</done>
</task>

<task type="auto">
  <name>Task 2: Implement Redis queue and configuration</name>
  <files>app/core/config.py, app/queue/redis_queue.py</files>
  <action>
    Update `app/core/config.py` to add `REDIS_URL` (default to "redis://localhost:6379/0").
    Create `app/queue/redis_queue.py` with `RedisQueue` class.
    It should provide `enqueue(task_id: str)`, `dequeue(block: bool, timeout: float) -> str | None`, `size()`, and `snapshot()` just like `TaskQueue`. Use `redis.Redis.from_url(REDIS_URL, decode_responses=True)` for connection.
    Use `rpush` for enqueue and `blpop` or `lpop` for dequeue.
  </action>
  <verify>
    <automated>python -c "from app.queue.redis_queue import RedisQueue"</automated>
  </verify>
  <done>RedisQueue class exists with the expected interface</done>
</task>

<task type="auto">
  <name>Task 3: Integrate Redis Queue into TaskService</name>
  <files>app/services/task_service.py</files>
  <action>
    Update `TaskService` to use `RedisQueue` instead of `TaskQueue`.
    Import `RedisQueue` from `app.queue.redis_queue` and assign `self._queue = RedisQueue()`.
    Ensure that tasks state (metadata) is still managed, but task IDs for execution are routed through Redis.
    (Optionally, you can also move task record storage to Redis, but for now we just need queue routing).
  </action>
  <verify>
    <automated>python -c "from app.services.task_service import TaskService; TaskService()"</automated>
  </verify>
  <done>TaskService instantiates without error</done>
</task>

</tasks>
