import ast
import os
from pathlib import Path
import subprocess
import sys

from app.core.config import (
    is_allowed_frontend_origin,
    normalize_url,
    parse_cors_allowed_origins,
    parse_oauth_allowed_frontend_origins,
)
from app.core.time import APP_TIMEZONE_NAME, app_now


def test_normalize_url_removes_trailing_slashes_and_spaces():
    assert normalize_url(" https://frontend.example.com/// ") == "https://frontend.example.com"


def test_parse_cors_allowed_origins_includes_frontend_and_local_defaults():
    assert parse_cors_allowed_origins("https://example.vercel.app/") == [
        "https://example.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_parse_cors_allowed_origins_adds_extra_origins_without_duplicates():
    assert parse_cors_allowed_origins(
        "https://frontend.vercel.app",
        "https://frontend.vercel.app/, https://preview.vercel.app",
    ) == [
        "https://frontend.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://preview.vercel.app",
    ]


def test_parse_cors_allowed_origins_can_skip_local_defaults_for_production():
    assert parse_cors_allowed_origins(
        "https://frontend.vercel.app",
        "https://admin.vercel.app",
        include_local_defaults=False,
    ) == [
        "https://frontend.vercel.app",
        "https://admin.vercel.app",
    ]


def test_parse_oauth_allowed_frontend_origins_includes_frontend_cors_and_extra_origins():
    assert parse_oauth_allowed_frontend_origins(
        "https://fastapi-5-4.vercel.app/",
        ["http://localhost:3000", "https://fastapi-5-4.vercel.app"],
        "http://127.0.0.1:3000/",
    ) == [
        "https://fastapi-5-4.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_is_allowed_frontend_origin_rejects_unconfigured_origins():
    assert is_allowed_frontend_origin("http://localhost:3000/")
    assert not is_allowed_frontend_origin("https://evil.com")
    assert not is_allowed_frontend_origin("http://localhost:3000.evil.com")


def test_oauth_redirect_uses_allowed_origin_from_session(monkeypatch):
    from app.api.routes import oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "FRONTEND_URL", "https://fastapi-5-4.vercel.app")
    monkeypatch.setattr(
        oauth_routes,
        "is_allowed_frontend_origin",
        lambda origin: origin in {"http://localhost:3000", "https://fastapi-5-4.vercel.app"},
    )
    request = _DummyRequest({"oauth_frontend_origin": "http://localhost:3000"})

    response = oauth_routes._redirect_with_token(request, "abc123")

    assert response.headers["location"] == "http://localhost:3000/oauth/callback?token=abc123"
    assert "oauth_frontend_origin" not in request.session


def test_oauth_redirect_falls_back_when_session_origin_is_invalid(monkeypatch):
    from app.api.routes import oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "FRONTEND_URL", "https://fastapi-5-4.vercel.app")
    monkeypatch.setattr(
        oauth_routes,
        "is_allowed_frontend_origin",
        lambda origin: origin == "https://fastapi-5-4.vercel.app",
    )
    request = _DummyRequest({"oauth_frontend_origin": "https://evil.com"})

    response = oauth_routes._redirect_with_token(request, "abc123")

    assert response.headers["location"] == "https://fastapi-5-4.vercel.app/oauth/callback?token=abc123"
    assert "oauth_frontend_origin" not in request.session


def test_oauth_login_stores_fallback_for_invalid_frontend_origin(monkeypatch):
    from app.api.routes import oauth as oauth_routes

    monkeypatch.setattr(oauth_routes, "FRONTEND_URL", "https://fastapi-5-4.vercel.app")
    monkeypatch.setattr(oauth_routes, "is_allowed_frontend_origin", lambda origin: False)
    request = _DummyRequest()

    oauth_routes._store_oauth_frontend_origin(request, "https://evil.com")

    assert request.session["oauth_frontend_origin"] == "https://fastapi-5-4.vercel.app"


def test_production_runtime_requires_explicit_frontend_url():
    env = {
        **os.environ,
        "ENV": "production",
        "FRONTEND_URL": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FRONTEND_URL must be explicitly set in production" in result.stderr


def test_production_runtime_rejects_localhost_frontend_url():
    env = {
        **os.environ,
        "ENV": "production",
        "FRONTEND_URL": "http://localhost:3000",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FRONTEND_URL must be set to the deployed frontend URL in production" in result.stderr


def test_app_now_uses_china_timezone():
    now = app_now()

    assert APP_TIMEZONE_NAME == "Asia/Shanghai"
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 8 * 60 * 60


def test_runtime_app_code_does_not_use_raw_sql_strings():
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "text":
                offenders.append(f"{path.relative_to(app_root)} calls text()")
            if isinstance(func, ast.Attribute):
                if func.attr in {"execute", "exec_driver_sql", "enable_load_extension"}:
                    offenders.append(f"{path.relative_to(app_root)} calls {func.attr}()")
            if _is_sql_api_call(func) and any(
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and any(keyword in argument.value.upper() for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))
                for argument in node.args
            ):
                offenders.append(f"{path.relative_to(app_root)} passes SQL-like string to {ast.unparse(func)}")

    assert offenders == []


def _is_sql_api_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "text"
    if isinstance(func, ast.Attribute):
        return func.attr in {"execute", "exec_driver_sql"}
    return False


class _DummyRequest:
    def __init__(self, session: dict[str, str] | None = None):
        self.session = session or {}
