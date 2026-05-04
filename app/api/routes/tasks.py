from fastapi import APIRouter, Query, Request

from ...schemas.response import ProcessResponse, TaskDetail, TaskResultResponse

router = APIRouter()


@router.get("/tasks")
def list_tasks(request: Request, status: str | None = Query(default=None)) -> list[TaskDetail]:
    service = request.app.state.task_service
    return [task.to_detail() for task in service.list_tasks(status)]


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def task_detail(task_id: str, request: Request) -> TaskDetail:
    service = request.app.state.task_service
    return service.get_task(task_id).to_detail()


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
def task_result(task_id: str, request: Request) -> TaskResultResponse:
    service = request.app.state.task_service
    return service.get_result(task_id)


@router.post("/tasks/process-next", response_model=ProcessResponse)
def process_next(request: Request) -> ProcessResponse:
    service = request.app.state.task_service
    task = service.process_next()
    return ProcessResponse(processed=[task.to_detail()] if task else [])


@router.post("/tasks/process-all", response_model=ProcessResponse)
def process_all(request: Request) -> ProcessResponse:
    service = request.app.state.task_service
    processed = service.process_all()
    return ProcessResponse(processed=[task.to_detail() for task in processed])

