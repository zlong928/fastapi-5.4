项目简介

这是一个基于 FastAPI 的文件处理服务，支持：

* 单文件上传和批量上传（.txt, .log, .csv）
* 文件验证、保存和分析
* 任务队列管理（FIFO）
* 后台任务处理（异步 worker）
* 查询任务状态与处理结果
* 日志记录 API 调用和任务处理
* 模块化项目结构，便于扩展和维护
项目目录结构
fastapi_app/
├── app/
│   ├── main.py
│   ├── api/routes/
│   │   ├── health.py
│   │   ├── upload.py
│   │   └── tasks.py
│   ├── core/
│   │   ├── config.py
│   │   └── logging_config.py
│   ├── services/
│   │   ├── file_service.py
│   │   └── task_service.py
│   ├── queue/task_queue.py
│   └── schemas/response.py
├── data/uploads/
├── data/results/
├── logs/
├── requirements.txt
└── README.md

本地运行
cd fastapi_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

访问：

* Swagger UI: http://127.0.0.1:8000/docs
* 健康检查: /health
* 上传接口: /upload 和 /upload/batch
* 查询任务: /tasks/{task_id}
* 查询结果: /tasks/{task_id}/result

批量上传测试
curl -X POST "http://127.0.0.1:8000/upload/batch" \
  -F "files=@file1.txt" \
  -F "files=@file2.txt"

  查看任务状态：curl http://127.0.0.1:8000/tasks/<task_id>

  查看处理结果：curl http://127.0.0.1:8000/tasks/<task_id>/result

  扩展建议

* 后台线程自动消费队列
* 失败任务重试
* 任务进度显示
* 支持 JSON 结果下载
* 内存队列替换为 Redis 实现分布式任务处理