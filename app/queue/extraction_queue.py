from __future__ import annotations

import json

from app.core.config import EXTRACTION_QUEUE_NAME
from app.queue.redis_queue import RedisQueue

EXTRACTION_TASK_TYPE = "extraction_run"


def build_extraction_payload(job_id: int) -> str:
    return json.dumps(
        {
            "type": EXTRACTION_TASK_TYPE,
            "job_id": job_id,
        }
    )


def parse_extraction_payload(payload: str) -> int | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if data.get("type") != EXTRACTION_TASK_TYPE:
        return None
    job_id = data.get("job_id")
    if not isinstance(job_id, int):
        return None
    return job_id


def enqueue_extraction(job_id: int) -> None:
    RedisQueue(queue_name=EXTRACTION_QUEUE_NAME).enqueue(build_extraction_payload(job_id))
