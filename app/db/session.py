from collections.abc import Generator

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, String, create_engine, inspect
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
    from app.models import Book, BookProgress, Collection, Document, DocumentAsset, DocumentChunk, DocumentEvent, DocumentTag, ExtractionJob, ExtractionResult, FileCleanupJob, JobRun, KgEntity, KgRelation, OAuthAccount, PaperTable, ParseJob, Tag, Task, User  # noqa: F401

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
            elif operation_name == "create_site_name_index":
                operations.create_index("ix_documents_site_name", "documents", ["site_name"], unique=False)
