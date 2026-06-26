"""
Migrate all data from SQLite to PostgreSQL.

Usage:
  1. Ensure PostgreSQL is running and has empty tables created.
  2. Run: DATABASE_URL=postgresql://fastapi_user:fastapi_pass@localhost:5432/fastapi_app \
           python scripts/migrate_sqlite_to_postgres.py
"""

import logging
import sys
from datetime import datetime

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SOURCE_URL = "sqlite:///./data/app.db"
TARGET_URL = "postgresql://fastapi_user:fastapi_pass@localhost:5432/fastapi_app"

BATCH_SIZE = 500

TABLE_EXCLUDE = {"alembic_version", "sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}
COLUMN_TYPE_MAP = {
    "DATETIME": "TIMESTAMP",
    "BOOLEAN": "BOOLEAN",
}


def _drop_target_tables(target: Engine) -> None:
    """Drop all tables in the target PostgreSQL database."""
    from app.db.session import Base
    from app.models import (  # noqa: F401
        BatchExtractionItem, BatchExtractionJob,
        Book, BookProgress,
        ChatMessage, ChatMessageSource, ChatSession,
        Collection,
        Document, DocumentAsset, DocumentChunk, DocumentClaim, DocumentEvent, DocumentTag,
        ExtractionEvidence, ExtractionItem, ExtractionJob, ExtractionResult, ExtractionRun,
        FileCleanupJob,
        JobRun,
        KgEntity, KgRelation,
        OAuthAccount,
        PaperTable, ParseJob,
        Tag, Task,
        User,
    )
    Base.metadata.drop_all(bind=target)
    logger.info("Existing target tables dropped")


def _ensure_target_tables(target: Engine) -> None:
    """Create target tables from SQLAlchemy metadata on the target engine."""
    from app.db.session import Base
    from app.models import (  # noqa: F401
        BatchExtractionItem, BatchExtractionJob,
        Book, BookProgress,
        ChatMessage, ChatMessageSource, ChatSession,
        Collection,
        Document, DocumentAsset, DocumentChunk, DocumentClaim, DocumentEvent, DocumentTag,
        ExtractionEvidence, ExtractionItem, ExtractionJob, ExtractionResult, ExtractionRun,
        FileCleanupJob,
        JobRun,
        KgEntity, KgRelation,
        OAuthAccount,
        PaperTable, ParseJob,
        Tag, Task,
        User,
    )
    Base.metadata.create_all(bind=target)
    logger.info("Target tables created from SQLAlchemy metadata")


def _migrate_table(source: Engine, target: Engine, table_name: str) -> int:
    """Migrate all rows from source table to target table. Returns row count."""
    with source.connect() as src_conn:
        src_conn.execution_options(isolation_level="AUTOCOMMIT")
        inspector = inspect(source)
        columns = [col for col in inspector.get_columns(table_name) if col["name"] not in ("", None)]
        col_names = [col["name"] for col in columns]

        target_columns = {col["name"]: col for col in inspect(target).get_columns(table_name)}
        boolean_cols = {
            name for name, col in target_columns.items()
            if str(col.get("type", "")).lower() in ("bool", "boolean")
        }

        total = src_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        if total == 0:
            logger.info("  [SKIP] %s: empty table", table_name)
            return 0

        migrated = 0
        offset = 0
        while offset < total:
            rows = src_conn.execute(
                text(f"SELECT * FROM {table_name} LIMIT {BATCH_SIZE} OFFSET {offset}")
            ).fetchall()
            if not rows:
                break

            with target.begin() as tgt_conn:
                for row in rows:
                    row_dict = dict(zip(col_names, row._mapping.values()))
                    cleaned = {}
                    for k, v in row_dict.items():
                        if isinstance(v, datetime):
                            cleaned[k] = v
                        elif k in boolean_cols:
                            cleaned[k] = bool(v) if v is not None else None
                        elif isinstance(v, bool):
                            cleaned[k] = v
                        elif v is None:
                            cleaned[k] = None
                        else:
                            cleaned[k] = v

                    placeholders = ", ".join(f":{c}" for c in col_names)
                    quoted_cols = ", ".join(f'"{c}"' for c in col_names)
                    tgt_conn.execute(
                        text(f"INSERT INTO {table_name} ({quoted_cols}) VALUES ({placeholders})"),
                        cleaned,
                    )
            migrated += len(rows)
            offset += len(rows)
            logger.info("  [%s] %d/%d rows migrated", table_name, offset, total)

    return migrated


def _reset_sequences(target: Engine) -> None:
    """Reset PostgreSQL sequences to match max id values.

    Uses information_schema.sequences for robust sequence name resolution.
    """
    with target.connect() as tgt_conn:
        seqs = tgt_conn.execute(text("""
            SELECT sequence_name FROM information_schema.sequences
            WHERE sequence_schema = 'public'
        """)).fetchall()
        for (seq_name,) in seqs:
            parts = seq_name.rsplit("_", 2)
            if len(parts) != 3:
                continue
            table_name, col_name = parts[0], parts[1]
            try:
                max_id = tgt_conn.execute(
                    text(f'SELECT COALESCE(MAX("{col_name}"), 0) FROM "{table_name}"')
                ).scalar()
                curr_val = tgt_conn.execute(
                    text(f'SELECT last_value FROM "{seq_name}"')
                ).scalar()
                if max_id >= curr_val:
                    new_val = max_id + 1
                    tgt_conn.execute(
                        text("SELECT setval(:seq, :val, false)"),
                        {"seq": seq_name, "val": new_val},
                    )
                    logger.info("  [SEQUENCE] %s: curr=%d, max=%d → set to %d", seq_name, curr_val, max_id, new_val)
            except Exception:
                logger.debug("  [SEQUENCE] %s skipped", seq_name, exc_info=True)
        tgt_conn.commit()


def main():
    source = create_engine(SOURCE_URL, connect_args={"check_same_thread": False})
    target = create_engine(TARGET_URL)

    logger.info("Source: %s", SOURCE_URL)
    logger.info("Target: %s", TARGET_URL)

    inspector = inspect(source)
    tables = [t for t in inspector.get_table_names() if t not in TABLE_EXCLUDE]

    if not tables:
        logger.warning("No tables found in source database")
        return

    logger.info("Dropping existing target tables...")
    _drop_target_tables(target)

    logger.info("Creating target tables...")
    _ensure_target_tables(target)

    logger.info("Disabling FK constraints for import...")
    with target.connect() as conn:
        conn.execute(text("SET session_replication_role = replica"))
        conn.commit()

    total_rows = 0
    for table_name in tables:
        try:
            count = _migrate_table(source, target, table_name)
            total_rows += count
        except Exception as e:
            logger.error("Failed to migrate table %s: %s", table_name, e)
            raise

    logger.info("Resetting sequences...")
    _reset_sequences(target)

    logger.info("Re-enabling FK constraints...")
    with target.connect() as conn:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()

    logger.info("Migration complete! Migrated %d rows across %d tables.", total_rows, len(tables))


if __name__ == "__main__":
    main()
