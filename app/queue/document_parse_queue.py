from __future__ import annotations

import json

from app.queue.redis_queue import RedisQueue

DOCUMENT_PARSE_TASK_TYPE = "document_parse"


def build_document_parse_payload(document_id: int, job_run_id: int) -> str:
    return json.dumps(
        {
            "type": DOCUMENT_PARSE_TASK_TYPE,
            "document_id": document_id,
            "job_run_id": job_run_id,
        }
    )


def parse_document_parse_payload(payload: str) -> tuple[int, int] | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if data.get("type") != DOCUMENT_PARSE_TASK_TYPE:
        return None
    document_id = data.get("document_id")
    job_run_id = data.get("job_run_id")
    if job_run_id is None:
        job_run_id = data.get("parse_job_id")
    if not isinstance(document_id, int) or not isinstance(job_run_id, int):
        return None
    return document_id, job_run_id


def enqueue_document_parse(document_id: int, job_run_id: int) -> None:
    RedisQueue().enqueue(build_document_parse_payload(document_id, job_run_id))
