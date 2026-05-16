from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...schemas.response import HealthResponse
from ...services.task_service import TaskService
from ...services.job_run_service import JobRunService
from ...services.obsidian_service import ObsidianService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request, db: Session = Depends(get_db)) -> HealthResponse:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        service = TaskService()
        request.app.state.task_service = service
    counts = JobRunService(db).health_counts()
    return HealthResponse(
        status="ok",
        queued_tasks=service.queue_size(),
        tracked_tasks=counts.running_jobs + counts.queued_jobs,
        tracked_tasks_total=counts.jobs_total,
        basic_file_tasks_total=counts.jobs_total,
        parse_jobs_total=counts.jobs_total,
        parse_jobs_active=counts.running_jobs + counts.queued_jobs,
        parse_jobs_failed=counts.failed_jobs,
        jobs_total=counts.jobs_total,
        visible_jobs=counts.visible_jobs,
        running_jobs=counts.running_jobs,
        failed_jobs=counts.failed_jobs,
    )


@router.get("/obsidian/health")
def obsidian_health() -> dict:
    return ObsidianService().health()
