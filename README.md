# File Processing Service

FastAPI + Redis + worker service for asynchronous file and PDF processing, with a Vite + React frontend for uploads and task monitoring.

## Features

- JWT registration and login
- Private file uploads and task records per user
- SQLite task persistence shared by API and worker
- Redis-backed processing queue
- Vite + React dashboard for upload, task list, and task detail polling

## Local Backend

```bash
python3 -m uvicorn app.main:app --reload --port 8000
python3 -m app.worker
```

## Local Frontend

```bash
cd frontend
npm install
npm run dev
```

Create `frontend/.env.local` if you need to override the API URL:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## Docker

```bash
docker compose up --build
```

Docker uses `./data/app.db` for SQLite persistence, so API and worker see the same task state.

## Access

- Frontend: http://localhost:3000
- Backend docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The browser-facing frontend should use `http://localhost:8000` for the API, not the internal Docker service hostname.

## Auth Flow

1. Open the frontend and register a user.
2. Log in with that account.
3. Uploads, task list, task detail, and task result requests use `Authorization: Bearer <token>`.
4. Requests without a token return `401`; tasks owned by another user return `404`.
