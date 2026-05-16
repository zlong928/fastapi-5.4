from app.core.config import parse_cors_allowed_origins


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
