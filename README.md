# File Processing Service

Small FastAPI backend for single and batch file uploads, FIFO task processing, status queries, result retrieval, and log tracking.

## Run

```bash
cd fastapi_app
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /health`
- `POST /upload`
- `POST /upload/batch`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `POST /tasks/process-next`
- `POST /tasks/process-all`

## Storage

- Uploads: `data/uploads/`
- Results: `data/results/`
- Logs: `logs/api_run.log`, `logs/task_run.log`

## Scripts

- `scripts/generate_mock_files.sh`
- `scripts/batch_upload_test.sh`

