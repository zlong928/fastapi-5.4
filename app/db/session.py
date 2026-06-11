from collections.abc import Generator

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, String, Text, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        run_pragma = cursor.execute
        run_pragma("PRAGMA journal_mode=WAL")
        run_pragma("PRAGMA busy_timeout=30000")
        run_pragma("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    from app.models import Book, BookProgress, ChatMessage, ChatMessageSource, ChatSession, Collection, Document, DocumentAsset, DocumentChunk, DocumentClaim, DocumentEvent, DocumentTag, ExtractionJob, ExtractionResult, FileCleanupJob, JobRun, KgEntity, KgRelation, OAuthAccount, PaperTable, ParseJob, Tag, Task, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_compat_columns()


def ensure_sqlite_compat_columns() -> None:
    """Patch local SQLite dev databases that predate nullable model fields."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("documents")}
    pending_operations: list[tuple[str, object]] = []
    if "source_url" not in columns:
        pending_operations.append(("add_column", Column("source_url", String(2048), nullable=True)))
    if "site_name" not in columns:
        pending_operations.append(("add_column", Column("site_name", String(255), nullable=True)))
    if "page_count" not in columns:
        pending_operations.append(("add_column", Column("page_count", Integer(), nullable=True)))
    if "metadata_json" not in columns:
        pending_operations.append(("add_column", Column("metadata_json", Text(), nullable=True)))

    if "document_assets" in inspector.get_table_names():
        asset_columns = {column["name"] for column in inspector.get_columns("document_assets")}
        for column_name in ["asset_index", "label", "caption", "markdown", "text_content", "summary"]:
            if column_name not in asset_columns:
                pending_operations.append(("add_asset_column", column_name))

    index_names = {index["name"] for index in inspector.get_indexes("documents")}
    if "ix_documents_site_name" not in index_names:
        pending_operations.append(("create_site_name_index", None))

    if not pending_operations:
        return

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for operation_name, payload in pending_operations:
            if operation_name == "add_column":
                operations.add_column("documents", payload)
            elif operation_name == "add_asset_column":
                column_name = str(payload)
                column_type = Integer() if column_name == "asset_index" else String(120) if column_name == "label" else Text()
                operations.add_column("document_assets", Column(column_name, column_type, nullable=True))
            elif operation_name == "create_site_name_index":
                operations.create_index("ix_documents_site_name", "documents", ["site_name"], unique=False)
