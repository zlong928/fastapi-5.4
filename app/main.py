# app/main.py

from contextlib import asynccontextmanager

from fastapi import FastAPI

# 绝对导入路由
from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.upload import router as upload_router

# 导入核心模块和服务
from app.core.config import ensure_runtime_dirs
from app.core.logging_config import configure_logging
from app.services.task_service import TaskService


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_dirs()                # 创建运行所需目录
    configure_logging()                  # 配置日志
    app.state.task_service = TaskService()  # 初始化任务服务
    yield
    app.state.task_service.stop_background_worker()  # 关闭后台任务


# 创建 FastAPI 应用
app = FastAPI(title="File Processing Service", lifespan=lifespan)

# 根路由
@app.get("/")
async def root():
    return {"message": "File Processing Service is running!"}

# 注册路由
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(tasks_router)


# 允许直接用 python 运行 main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)