from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    from app.models import Book, BookProgress, Document, DocumentAsset, DocumentChunk, DocumentEvent, JobRun, KgEntity, KgRelation, OAuthAccount, ParseJob, Task, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_users_password_nullable()
    _ensure_sqlite_document_processing_mvp()


def _ensure_sqlite_users_password_nullable() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = inspector.get_columns("users")
    hashed_password = next((column for column in columns if column["name"] == "hashed_password"), None)
    if not hashed_password or not hashed_password.get("nullable") is False:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users RENAME TO users_old"))
        User.__table__.create(bind=connection)
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, username, hashed_password, is_active, created_at, updated_at)
                SELECT id, email, username, hashed_password, is_active, created_at, updated_at
                FROM users_old
                """
            )
        )
        connection.execute(text("DROP TABLE users_old"))


def _ensure_sqlite_document_processing_mvp() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("documents")}
    additions = {
        "cleaned_text": "TEXT",
        "parse_quality_json": "TEXT",
        "references_text": "TEXT",
        "processing_mode": "VARCHAR(50) NOT NULL DEFAULT 'auto'",
        "processing_strategy": "VARCHAR(100)",
    }

    with engine.begin() as connection:
        for column_name, column_type in additions.items():
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column_name} {column_type}"))

    if "parse_jobs" in inspector.get_table_names():
        parse_job_columns = {column["name"] for column in inspector.get_columns("parse_jobs")}
        with engine.begin() as connection:
            if "metadata_json" not in parse_job_columns:
                connection.execute(text("ALTER TABLE parse_jobs ADD COLUMN metadata_json TEXT"))

    if "document_chunks" not in inspector.get_table_names():
        return

    chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    chunk_additions = {
        "embedding_json": "TEXT",
        "embedding_model": "VARCHAR(100)",
        "embedding_dim": "INTEGER",
        "embedded_at": "DATETIME",
    }
    with engine.begin() as connection:
        for column_name, column_type in chunk_additions.items():
            if column_name not in chunk_columns:
                connection.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {column_name} {column_type}"))
