from __future__ import annotations

import typer

from .core import config
config.ENABLE_BACKGROUND_WORKER = False

from .core.config import ensure_runtime_dirs
from .services.task_service import TaskRecord, TaskService


app = typer.Typer(help="Process uploaded PDF tasks.")


def _status_line(record: TaskRecord) -> str:
    if record.error:
        return f"{record.task_id}: {record.status} ({record.error})"
    return f"{record.task_id}: {record.status}"


@app.command("process")
def process_task(task_id: str) -> None:
    ensure_runtime_dirs()
    service = TaskService()
    record = service.process_task(task_id)
    typer.echo(_status_line(record))


@app.command("scan")
def scan_uploads() -> None:
    ensure_runtime_dirs()
    service = TaskService()
    processed = service.process_uploads()
    if not processed:
        typer.echo("No pending PDF uploads found.")
        return
    for record in processed:
        typer.echo(_status_line(record))


@app.command("process-queue")
def process_queue() -> None:
    ensure_runtime_dirs()
    service = TaskService()
    record = service.process_next()
    if not record:
        typer.echo("No tasks in queue.")
        return
    typer.echo(_status_line(record))


if __name__ == "__main__":
    app()
