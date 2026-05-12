from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Task, User


class FakeQueue:
    def __init__(self, items: list[str]) -> None:
        self.items = items

    def remove_many(self, task_ids: list[str]) -> None:
        blocked = set(task_ids)
        self.items = [item for item in self.items if item not in blocked]


class FakeTaskService:
    def __init__(self, queue: FakeQueue) -> None:
        self._queue = queue
        self._records = {"task-1": object(), "task-2": object(), "task-3": object()}
        from threading import Lock

        self._lock = Lock()

    from app.services.task_service import TaskService

    clear_tasks = TaskService.clear_tasks


def make_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.services.task_service.SessionLocal", session_factory)
    client = TestClient(app)
    return client, session_factory


def create_user(session_factory, email: str, username: str) -> User:
    db = session_factory()
    user = User(email=email, username=username, hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.expunge(user)
    db.close()
    return user


def create_task(session_factory, task_id: str, user_id: int) -> None:
    db = session_factory()
    db.add(
        Task(
            task_id=task_id,
            user_id=user_id,
            file_name=f"{task_id}.pdf",
            file_size=123,
            file_type="pdf",
            status="queued",
            storage_path=f"/tmp/{task_id}.pdf",
        )
    )
    db.commit()
    db.close()


def test_clear_tasks_removes_only_current_users_records(monkeypatch):
    client, session_factory = make_client(monkeypatch)
    user = create_user(session_factory, "user@example.com", "user")
    other_user = create_user(session_factory, "other@example.com", "other")
    create_task(session_factory, "task-1", user.id)
    create_task(session_factory, "task-2", user.id)
    create_task(session_factory, "task-3", other_user.id)

    app.dependency_overrides[get_current_user] = lambda: user
    queue = FakeQueue(["task-1", "task-2", "task-3"])
    app.state.task_service = FakeTaskService(queue)

    try:
        response = client.delete("/tasks")

        assert response.status_code == 200
        assert response.json() == {"message": "Cleared 2 task records."}
        assert queue.items == ["task-3"]
        assert set(app.state.task_service._records) == {"task-3"}

        db = session_factory()
        remaining = db.scalars(select(Task.task_id)).all()
        db.close()
        assert remaining == ["task-3"]
    finally:
        del app.state._state["task_service"]
        app.dependency_overrides.clear()
