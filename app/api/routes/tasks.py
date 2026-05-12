from fastapi import APIRouter, Depends, Query, Request

from ...api.deps import get_current_user
from ...models import User
from ...schemas.auth import MessageResponse
from ...schemas.response import ProcessResponse, TaskDetail, TaskResultResponse

router = APIRouter()


@router.get("/tasks")
def list_tasks(
    request: Request,
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> list[TaskDetail]:
    service = request.app.state.task_service
    return [task.to_detail() for task in service.list_tasks(status, user_id=current_user.id)]


@router.delete("/tasks", response_model=MessageResponse)
def clear_tasks(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    service = request.app.state.task_service
    deleted_count = service.clear_tasks(user_id=current_user.id)
    return MessageResponse(message=f"Cleared {deleted_count} task records.")


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def task_detail(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> TaskDetail:
    service = request.app.state.task_service
    return service.get_task(task_id, user_id=current_user.id).to_detail()


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
def task_result(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> TaskResultResponse:
    service = request.app.state.task_service
    return service.get_result(task_id, user_id=current_user.id)


@router.post("/tasks/process-next", response_model=ProcessResponse)
def process_next(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    service = request.app.state.task_service
    task = service.process_next()
    return ProcessResponse(processed=[task.to_detail()] if task and task.user_id == current_user.id else [])


@router.post("/tasks/process-all", response_model=ProcessResponse)
def process_all(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    service = request.app.state.task_service
    processed = service.process_all()
    return ProcessResponse(processed=[task.to_detail() for task in processed if task.user_id == current_user.id])
