import ast
from pathlib import Path

from app.core.config import parse_cors_allowed_origins
from app.core.time import APP_TIMEZONE_NAME, app_now


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
