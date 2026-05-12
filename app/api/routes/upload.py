from fastapi import APIRouter, Depends, File, Request, UploadFile

from ...api.deps import get_current_user
from ...models import User
from ...schemas.response import UploadResponse

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_single(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    service = request.app.state.task_service#调用TaskService 实例
    tasks = await service.save_uploads([file], user_id=current_user.id)
    #异步操作,async/await，可以在等待 I/O 的时候去处理其他请求
    return UploadResponse(
        tasks=[task.to_summary() for task in tasks],
        queue_size=service.queue_size(),
        task_id=tasks[0].task_id,
    )


@router.post("/upload/batch", response_model=UploadResponse)
async def upload_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    service = request.app.state.task_service
    tasks = await service.save_uploads(files, user_id=current_user.id)
    return UploadResponse(tasks=[task.to_summary() for task in tasks], queue_size=service.queue_size())
