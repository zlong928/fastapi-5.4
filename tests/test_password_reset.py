from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.security import get_password_hash
from app.db.session import Base, get_db
from app.main import app
from app.models import User


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expired: set[str] = set()

    def get(self, key: str) -> str | None:
        if key in self.expired:
            return None
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def expire_key(self, key: str) -> None:
        self.expired.add(key)


def make_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    redis = FakeRedis()
    sent_codes: list[tuple[str, str]] = []

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def capture_email(email: str, code: str) -> None:
        sent_codes.append((email, code))

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)
    monkeypatch.setattr("app.api.routes.auth.redis_client", redis)
    monkeypatch.setattr("app.api.routes.auth.send_password_reset_code_email", capture_email)

    client = TestClient(app)
    return client, session_factory, redis, sent_codes


def create_user(session_factory, email: str = "user@example.com") -> User:
    db = session_factory()
    user = User(email=email, username="user", hashed_password="$2b$12$placeholder")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def test_forgot_password_returns_uniform_success_for_missing_email(monkeypatch):
    client, _, redis, sent_codes = make_client(monkeypatch)

    response = client.post("/auth/password/forgot", json={"email": "missing@example.com"})

    assert response.status_code == 200
    assert response.json() == {"message": "If the email exists, a verification code has been sent."}
    assert redis.values == {}
    assert sent_codes == []
    app.dependency_overrides.clear()


def test_forgot_password_stores_reset_hash_for_existing_email(monkeypatch):
    client, session_factory, redis, sent_codes = make_client(monkeypatch)
    create_user(session_factory)

    response = client.post("/auth/password/forgot", json={"email": " User@Example.COM "})

    assert response.status_code == 200
    stored = redis.get("password_reset:user@example.com")
    assert stored is not None
    assert stored != sent_codes[0][1]
    assert sent_codes[0][0] == "user@example.com"
    assert redis.get("password_reset_cooldown:user@example.com") == "1"
    app.dependency_overrides.clear()


def test_forgot_password_cooldown_prevents_duplicate_email(monkeypatch):
    client, session_factory, _, sent_codes = make_client(monkeypatch)
    create_user(session_factory)

    first_response = client.post("/auth/password/forgot", json={"email": "user@example.com"})
    second_response = client.post("/auth/password/forgot", json={"email": "user@example.com"})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(sent_codes) == 1
    app.dependency_overrides.clear()


def test_reset_password_rejects_wrong_code(monkeypatch):
    client, session_factory, _, _ = make_client(monkeypatch)
    create_user(session_factory)
    client.post("/auth/password/forgot", json={"email": "user@example.com"})

    response = client.post(
        "/auth/password/reset",
        json={"email": "user@example.com", "code": "000000", "new_password": "NewPassword123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired verification code"
    app.dependency_overrides.clear()


def test_reset_password_rejects_expired_code(monkeypatch):
    client, session_factory, redis, sent_codes = make_client(monkeypatch)
    create_user(session_factory)
    client.post("/auth/password/forgot", json={"email": "user@example.com"})
    redis.expire_key("password_reset:user@example.com")

    response = client.post(
        "/auth/password/reset",
        json={"email": "user@example.com", "code": sent_codes[0][1], "new_password": "NewPassword123"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired verification code"
    app.dependency_overrides.clear()


def test_reset_password_updates_hash_and_code_cannot_be_reused(monkeypatch):
    client, session_factory, redis, sent_codes = make_client(monkeypatch)
    create_user(session_factory)
    client.post("/auth/password/forgot", json={"email": "user@example.com"})
    code = sent_codes[0][1]

    response = client.post(
        "/auth/password/reset",
        json={"email": "user@example.com", "code": code, "new_password": "NewPassword123"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Password reset successfully."}
    assert redis.get("password_reset:user@example.com") is None

    db = session_factory()
    user = db.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    assert user.hashed_password != "$2b$12$placeholder"
    db.close()

    reuse_response = client.post(
        "/auth/password/reset",
        json={"email": "user@example.com", "code": code, "new_password": "OtherPassword123"},
    )
    assert reuse_response.status_code == 400
    app.dependency_overrides.clear()


def test_existing_login_still_works(monkeypatch):
    client, session_factory, _, _ = make_client(monkeypatch)
    db = session_factory()
    user = User(email="login@example.com", username="login", hashed_password=get_password_hash("Password123"))
    db.add(user)
    db.commit()
    db.close()

    response = client.post("/auth/login", json={"email": "login@example.com", "password": "Password123"})

    assert response.status_code == 200
    assert response.json()["access_token"]
    app.dependency_overrides.clear()


def test_login_after_password_reset(monkeypatch):
    """关键测试：重置密码后能否使用新密码登录"""
    client, session_factory, _, sent_codes = make_client(monkeypatch)
    
    # 第一步：创建用户，使用旧密码 OldPassword123
    db = session_factory()
    user = User(
        email="reset@example.com",
        username="resetuser",
        hashed_password=get_password_hash("OldPassword123")
    )
    db.add(user)
    db.commit()
    db.close()
    
    # 第二步：验证旧密码能登录
    response = client.post("/auth/login", json={"email": "reset@example.com", "password": "OldPassword123"})
    assert response.status_code == 200
    
    # 第三步：请求密码重置
    response = client.post("/auth/password/forgot", json={"email": "reset@example.com"})
    assert response.status_code == 200
    reset_code = sent_codes[0][1]
    
    # 第四步：重置密码为新密码
    response = client.post(
        "/auth/password/reset",
        json={
            "email": "reset@example.com",
            "code": reset_code,
            "new_password": "NewPassword456"
        }
    )
    assert response.status_code == 200, f"密码重置失败: {response.json()}"
    
    # 第五步：关键测试 - 使用新密码登录
    response = client.post("/auth/login", json={"email": "reset@example.com", "password": "NewPassword456"})
    
    # 如果这个测试失败，说明密码重置后无法登录
    assert response.status_code == 200, f"新密码登录失败: {response.json()}"
    assert response.json()["access_token"]
    app.dependency_overrides.clear()
