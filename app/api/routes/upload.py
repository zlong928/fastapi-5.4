from fastapi import APIRouter, File, Request, UploadFile

from ...schemas.response import UploadResponse

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_single(request: Request, file: UploadFile = File(...)) -> UploadResponse:
    service = request.app.state.task_service#调用TaskService 实例
    tasks = await service.save_uploads([file])
    #异步操作,async/await，可以在等待 I/O 的时候去处理其他请求
    return UploadResponse(tasks=[task.to_summary() for task in tasks], queue_size=service.queue_size())


@router.post("/upload/batch", response_model=UploadResponse)
async def upload_batch(request: Request, files: list[UploadFile] = File(...)) -> UploadResponse:
    service = request.app.state.task_service
    tasks = await service.save_uploads(files)
    return UploadResponse(tasks=[task.to_summary() for task in tasks], queue_size=service.queue_size())

