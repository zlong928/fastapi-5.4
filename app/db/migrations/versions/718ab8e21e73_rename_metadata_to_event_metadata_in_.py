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


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite doesn't support direct ALTER COLUMN RENAME, so we need to recreate the table
    # This is a safe operation since we're just renaming a column
    op.execute("""
    CREATE TABLE document_events_new (
        id INTEGER NOT NULL,
        document_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        message VARCHAR(500) NOT NULL,
        event_metadata TEXT,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(document_id) REFERENCES documents (id),
        FOREIGN KEY(user_id) REFERENCES users (id)
    )
    """)
    op.execute("""
    INSERT INTO document_events_new 
    SELECT id, document_id, user_id, event_type, message, metadata, created_at
    FROM document_events
    """)
    op.execute("DROP TABLE document_events")
    op.execute("ALTER TABLE document_events_new RENAME TO document_events")
    
    # Recreate indexes
    op.create_index('ix_document_events_document_id', 'document_events', ['document_id'], unique=False)
    op.create_index('ix_document_events_user_id', 'document_events', ['user_id'], unique=False)
    op.create_index('ix_document_events_event_type', 'document_events', ['event_type'], unique=False)
    op.create_index('ix_document_events_created_at', 'document_events', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse the rename
    op.execute("""
    CREATE TABLE document_events_new (
        id INTEGER NOT NULL,
        document_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        message VARCHAR(500) NOT NULL,
        metadata TEXT,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(document_id) REFERENCES documents (id),
        FOREIGN KEY(user_id) REFERENCES users (id)
    )
    """)
    op.execute("""
    INSERT INTO document_events_new 
    SELECT id, document_id, user_id, event_type, message, event_metadata, created_at
    FROM document_events
    """)
    op.execute("DROP TABLE document_events")
    op.execute("ALTER TABLE document_events_new RENAME TO document_events")
    
    # Recreate indexes
    op.create_index('ix_document_events_document_id', 'document_events', ['document_id'], unique=False)
    op.create_index('ix_document_events_user_id', 'document_events', ['user_id'], unique=False)
    op.create_index('ix_document_events_event_type', 'document_events', ['event_type'], unique=False)
    op.create_index('ix_document_events_created_at', 'document_events', ['created_at'], unique=False)
