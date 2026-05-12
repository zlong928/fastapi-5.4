"""Create documents, document_events, and chunks tables

Revision ID: e95a4b081e64
Revises: 
Create Date: 2026-05-12 06:50:01.881537

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e95a4b081e64'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('original_file_path', sa.String(length=512), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('parsed_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_user_id'), 'documents', ['user_id'], unique=False)
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)
    op.create_index(op.f('ix_documents_created_at'), 'documents', ['created_at'], unique=False)

    # Create document_events table
    op.create_table(
        'document_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('event_metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_events_document_id'), 'document_events', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_events_user_id'), 'document_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_document_events_event_type'), 'document_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_document_events_created_at'), 'document_events', ['created_at'], unique=False)

    # Create chunks table
    op.create_table(
        'chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chunks_document_id'), 'chunks', ['document_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_chunks_document_id'), table_name='chunks')
    op.drop_table('chunks')
    op.drop_index(op.f('ix_document_events_created_at'), table_name='document_events')
    op.drop_index(op.f('ix_document_events_event_type'), table_name='document_events')
    op.drop_index(op.f('ix_document_events_user_id'), table_name='document_events')
    op.drop_index(op.f('ix_document_events_document_id'), table_name='document_events')
    op.drop_table('document_events')
    op.drop_index(op.f('ix_documents_created_at'), table_name='documents')
    op.drop_index(op.f('ix_documents_status'), table_name='documents')
    op.drop_index(op.f('ix_documents_user_id'), table_name='documents')
    op.drop_table('documents')
