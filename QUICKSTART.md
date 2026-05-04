# 🚀 Redis Worker Pipeline - 快速开始指南

## 安装和配置

### 1. 安装依赖

```bash
cd /Users/Apple/Desktop/study\ report/week\ 2改/fastapi_app

# 如果还没有创建虚拟环境
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # macOS/Linux
# 或
.venv\Scripts\activate  # Windows

# 安装所有依赖
.venv/bin/pip install -r requirements.txt
```

### 2. 启动 Redis 服务

```bash
# macOS (使用 Homebrew)
brew services start redis

# 或直接运行
redis-server --daemonize yes --port 6379

# 验证 Redis 连接
redis-cli ping
# 应该返回: PONG
```

### 3. 配置环境变量

创建或编辑 `.env` 文件：

```bash
# Redis 配置
REDIS_URL=redis://localhost:6379/0

# 禁用 TaskService 内部后台 Worker（重要！避免竞争）
ENABLE_BACKGROUND_WORKER=False

# 目录配置
DATA_DIR=./data
UPLOAD_DIR=./data/uploads
RESULT_DIR=./data/results
LOG_DIR=./logs
```

---

## 使用方式

### 方式 1️⃣: 使用 Typer CLI 处理单个任务

```bash
# 列出帮助
.venv/bin/python -m app.cli --help

# 处理队列中的一个任务
.venv/bin/python -m app.cli process-queue

# 输出示例:
# task_abc123def: success

# 处理指定任务 ID
.venv/bin/python -m app.cli process {task_id}

# 扫描上传目录并处理所有待处理任务
.venv/bin/python -m app.cli scan
```

### 方式 2️⃣: 使用独立 Worker 持续处理

```bash
# 启动 Worker
.venv/bin/python -m app.worker

# 输出示例:
# 2026-05-04 10:00:00,000 - worker - INFO - Worker started, waiting for tasks on Redis queue...
# 2026-05-04 10:00:05,123 - worker - INFO - Picked up task abc123def456
# 2026-05-04 10:00:06,456 - worker - INFO - Finished task abc123def456 with status success

# 停止 Worker (Ctrl+C)
# 输出: Shutdown signal received. Stopping worker after current task...
#       Worker stopped.
```

### 方式 3️⃣: 通过 API 上传 PDF 并处理

```bash
# 启动 FastAPI 服务器
.venv/bin/python -m uvicorn app.main:app --reload

# 在另一个终端窗口中上传 PDF
curl -F "files=@/path/to/document.pdf" http://localhost:8000/api/upload

# 响应示例:
# {
#   "tasks": [
#     {
#       "task_id": "abc123def456",
#       "file_name": "document.pdf",
#       "status": "queued",
#       "file_size": 50000,
#       "created_at": "2026-05-04T10:00:00+00:00"
#     }
#   ]
# }

# 然后通过 CLI 或 Worker 处理队列中的任务
.venv/bin/python -m app.cli process-queue

# 或使用 Worker
.venv/bin/python -m app.worker
```

---

## 架构概览

```
┌─────────────────────────────────────────────┐
│          PDF 上传接口 (FastAPI API)           │
│         /api/upload, /api/tasks              │
└────────────────────┬────────────────────────┘
                     │ 入队任务
                     │
                     ▼
             ┌──────────────────┐
             │   Redis Queue    │
             │                  │
             │ (pdf_task_queue) │
             └────────┬─────────┘
                      │
         ┌────────────┼────────────┐
         │                        │
         ▼                        ▼
    ┌────────────┐          ┌────────────┐
    │ Typer CLI  │          │   Worker   │
    │ (按需处理)  │          │ (连续处理)  │
    └────────────┘          └────────────┘
         │                        │
         └────────────┬───────────┘
                      │
                      ▼
           ┌────────────────────┐
           │   TaskService      │
           │  (处理逻辑控制)     │
           └────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
    ┌────────┐  ┌──────────┐  ┌───────────┐
    │ PDF    │  │ File     │  │ 结果文件  │
    │ Service│  │ Service  │  │ (JSON)    │
    └────────┘  └──────────┘  └───────────┘
```

---

## 测试验证

### 运行所有测试

```bash
# 基础功能测试
.venv/bin/python tests/test_functional_redis_worker.py

# 真实场景测试
.venv/bin/python tests/test_real_world_workflow.py

# 并发处理演示
.venv/bin/python tests/test_dual_pathway_demo.py
```

### 预期输出

所有测试都应该显示：
```
🎉 ALL TESTS PASSED!
```

---

## 常见任务

### 任务 1: 上传并处理单个 PDF

```bash
# 创建目录并准备 PDF
mkdir -p data/uploads/my_task_001
cp ~/Downloads/document.pdf data/uploads/my_task_001/

# 入队任务
redis-cli rpush pdf_task_queue my_task_001

# 通过 CLI 处理
.venv/bin/python -m app.cli process-queue

# 查看结果
cat data/results/my_task_001.json
```

### 任务 2: 批量处理多个 PDF

```bash
# 创建多个任务目录
for i in {1..5}; do
  mkdir -p data/uploads/batch_task_$i
  cp ~/Downloads/document.pdf data/uploads/batch_task_$i/
  redis-cli rpush pdf_task_queue batch_task_$i
done

# 启动 Worker 持续处理
.venv/bin/python -m app.worker

# 在另一个终端查看处理进度
watch -n 1 'redis-cli llen pdf_task_queue'
```

### 任务 3: 监控队列状态

```bash
# 检查队列长度
redis-cli llen pdf_task_queue

# 查看队列中的所有任务 ID
redis-cli lrange pdf_task_queue 0 -1

# 清空队列（谨慎操作）
redis-cli del pdf_task_queue
```

### 任务 4: 查看处理结果

```bash
# 列出所有结果文件
ls -lah data/results/

# 查看特定任务的结果
cat data/results/{task_id}.json | jq .

# 查看成功的任务
find data/results -name "*.json" -exec grep -l '"error": null' {} \;

# 查看失败的任务
find data/results -name "*.json" -exec grep -l '"error"' {} \;
```

---

## 高级配置

### 使用远程 Redis

```bash
# 编辑 .env
REDIS_URL=redis://redis-server.example.com:6379/0

# 或使用带认证的 Redis
REDIS_URL=redis://:password@redis-server.example.com:6379/0
```

### 使用 Redis 哨兵（高可用）

```bash
REDIS_URL=sentinel://password@sentinel-1:26379,sentinel-2:26379,sentinel-3:26379/0
```

### Docker 部署

```bash
# 启动 Redis 容器
docker run -d -p 6379:6379 redis:latest

# 在 Docker 中运行 Worker
docker run -e REDIS_URL=redis://redis-host:6379/0 \
           -v $(pwd)/data:/app/data \
           -v $(pwd)/logs:/app/logs \
           my-worker-image python -m app.worker
```

---

## 故障排除

### 问题 1: Redis 连接失败

```bash
# 检查 Redis 是否运行
redis-cli ping

# 如果返回 "PONG"，则 Redis 正常运行
# 如果连接失败，启动 Redis:
redis-server --daemonize yes
```

### 问题 2: 任务没有被处理

```bash
# 检查任务是否在队列中
redis-cli lrange pdf_task_queue 0 -1

# 检查是否启用了 Worker
ps aux | grep "app.worker"

# 检查日志
tail -f logs/task_run.log
```

### 问题 3: PDF 处理失败

```bash
# 检查结果文件中的错误信息
cat data/results/{task_id}.json | jq .error

# 常见错误：
# - "Invalid PDF header." - PDF 文件损坏
# - "No extractable text found in PDF." - PDF 是图像或扫描件
# - "PDF upload not found." - 文件不存在
```

### 问题 4: 两个 Worker 处理同一任务

```bash
# 这不应该发生（Redis blpop 是原子操作）
# 如果发生，检查：
# 1. 是否有多个 TaskService 实例使用相同的队列
# 2. 是否在同一进程中启用了多个 Worker
# 3. 解决方案：确保 ENABLE_BACKGROUND_WORKER=False
```

---

## 性能优化建议

### 1. 调整 Worker 线程数

对于 CPU 密集型任务（如 PDF 处理），建议：
- CPU 核心数 ≤ 4：使用 1 个 Worker
- CPU 核心数 5-8：使用 2 个 Worker
- CPU 核心数 > 8：使用 N/2 个 Worker

```bash
# 启动 4 个 Worker 处理
for i in {1..4}; do
  .venv/bin/python -m app.worker &
done
```

### 2. 批量处理优化

```bash
# 而不是逐个处理任务，使用 scan 命令一次处理所有
.venv/bin/python -m app.cli scan
```

### 3. Redis 持久化

```bash
# 编辑 redis.conf 启用持久化
save 900 1       # 900 秒内至少有 1 个修改
save 300 10      # 300 秒内至少有 10 个修改
save 60 10000    # 60 秒内至少有 10000 个修改
```

---

## 日志位置

```
logs/
├── api_run.log      # FastAPI 服务器日志
└── task_run.log     # 任务处理日志（CLI 和 Worker）
```

---

## 更多信息

- 📄 [完整测试报告](./TESTING_REPORT.md)
- 📚 [API 文档](./app/api)
- 🔧 [配置说明](./app/core/config.py)
- 💾 [数据库架构](./app/services)

---

## 需要帮助？

1. 检查日志文件
2. 查看测试代码了解用法
3. 运行测试脚本验证功能
4. 参考本文档的故障排除部分

---

**最后更新**: 2026-05-04
