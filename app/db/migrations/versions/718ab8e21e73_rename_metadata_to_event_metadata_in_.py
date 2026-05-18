"""Rename metadata to event_metadata in document_events

Revision ID: 718ab8e21e73
Revises: e95a4b081e64
Create Date: 2026-05-12 06:57:57.604354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '718ab8e21e73'
down_revision: Union[str, Sequence[str], None] = 'e95a4b081e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _rename_column_if_present(table_name: str, old_name: str, new_name: str) -> None:
    columns = _column_names(table_name)
    if old_name not in columns or new_name in columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            old_name,
            new_column_name=new_name,
            existing_type=sa.Text(),
            existing_nullable=True,
        )


def upgrade() -> None:
    """Upgrade schema."""
    _rename_column_if_present("document_events", "metadata", "event_metadata")


def downgrade() -> None:
    """Downgrade schema."""
    _rename_column_if_present("document_events", "event_metadata", "metadata")
