# File Processing Service

FastAPI + Redis + worker service for asynchronous file and PDF processing, with a Vite + React frontend for uploads and task monitoring.

## Features

- JWT registration and login
- GitHub and Google OAuth login
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

## OAuth Setup

Backend environment variables:

```bash
FRONTEND_URL=http://localhost:3000
SESSION_SECRET_KEY=change-me
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

GitHub OAuth App:

```text
Authorization callback URL: http://localhost:8000/auth/github/callback
```

Google OAuth Client:

```text
Authorized redirect URI: http://localhost:8000/auth/google/callback
```

Local test flow:

1. Start backend and frontend.
2. Open `http://localhost:3000/login`.
3. Click `Continue with GitHub` or `Continue with Google`.
4. After provider login, the backend redirects to `/oauth/callback?token=...`.
5. The frontend stores this project JWT and redirects to the dashboard.
6. `GET /auth/me` should return the current local user.
