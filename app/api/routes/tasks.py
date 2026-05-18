from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.constants.jobs import JOB_KIND_DOCUMENT_PARSE
from app.services.job_run_service import JobRunService
from app.services.task_compat import job_run_to_task_detail
from ...api.deps import get_current_user
from ...db.session import get_db
from ...models import User
from ...schemas.auth import MessageResponse
from ...schemas.response import PaginatedTasksResponse, ProcessResponse, TaskDetail, TaskResultResponse
from ...services.task_service import TaskService

router = APIRouter()


@router.delete("/tasks", response_model=MessageResponse)
def clear_tasks(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    hidden_count = JobRunService(db).hide_jobs_for_user(current_user.id)
    db.commit()
    return MessageResponse(message=f"Cleared {hidden_count} task records from your task list. Job history remains attached to documents.")


@router.get("/tasks/search", response_model=PaginatedTasksResponse)
def search_tasks(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    document_id: int | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedTasksResponse:
    job_runs, total = JobRunService(db).search_jobs(
        user_id=current_user.id,
        page=page,
        size=size,
        query_text=q,
        status_filter=status,
        kind_filter=kind,
        document_id=document_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedTasksResponse(
        total=total,
        page=page,
        size=size,
        items=[job_run_to_task_detail(job_run) for job_run in job_runs],
    )


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def task_detail(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskDetail:
    job_run = JobRunService(db).get_job(task_id, user_id=current_user.id)
    if job_run is None or not job_run.is_visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return job_run_to_task_detail(job_run)


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
def task_result(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResultResponse:
    job_run = JobRunService(db).get_job(task_id, user_id=current_user.id)
    if job_run is not None and job_run.kind == JOB_KIND_DOCUMENT_PARSE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document parse tasks do not expose result JSON. Use the document detail endpoint instead.",
        )
    return _task_service(request).get_result(task_id, user_id=current_user.id)


@router.post("/tasks/process-next", response_model=ProcessResponse)
def process_next(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    service = _task_service(request)
    task = service.process_next()
    return ProcessResponse(processed=[task.to_detail()] if task and task.user_id == current_user.id else [])


@router.post("/tasks/process-all", response_model=ProcessResponse)
def process_all(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    service = _task_service(request)
    processed = service.process_all()
    return ProcessResponse(processed=[task.to_detail() for task in processed if task.user_id == current_user.id])


def _task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        service = TaskService()
        request.app.state.task_service = service
    return service
