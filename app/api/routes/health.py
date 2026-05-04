from fastapi import APIRouter, Request

from ...schemas.response import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    service = request.app.state.task_service
    return HealthResponse(
        status="ok",
        queued_tasks=service.queue_size(),
        tracked_tasks=service.tracked_count(),
    )

