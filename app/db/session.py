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
    from app.models import OAuthAccount, Task, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_users_password_nullable()


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
