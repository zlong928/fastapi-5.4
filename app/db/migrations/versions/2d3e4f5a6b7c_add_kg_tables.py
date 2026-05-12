"""Add knowledge graph tables

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-05-12 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d3e4f5a6b7c"
down_revision: Union[str, Sequence[str], None] = "1c2d3e4f5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kg_entities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kg_entities_chunk_id"), "kg_entities", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_kg_entities_document_id"), "kg_entities", ["document_id"], unique=False)
    op.create_index(op.f("ix_kg_entities_entity_type"), "kg_entities", ["entity_type"], unique=False)
    op.create_index(op.f("ix_kg_entities_id"), "kg_entities", ["id"], unique=False)
    op.create_index(op.f("ix_kg_entities_name"), "kg_entities", ["name"], unique=False)
    op.create_index(op.f("ix_kg_entities_normalized_name"), "kg_entities", ["normalized_name"], unique=False)

    op.create_table(
        "kg_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("subject_entity_id", sa.Integer(), nullable=True),
        sa.Column("object_entity_id", sa.Integer(), nullable=True),
        sa.Column("subject_text", sa.String(length=255), nullable=False),
        sa.Column("predicate", sa.String(length=120), nullable=False),
        sa.Column("object_text", sa.String(length=255), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["object_entity_id"], ["kg_entities.id"]),
        sa.ForeignKeyConstraint(["subject_entity_id"], ["kg_entities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kg_relations_chunk_id"), "kg_relations", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_kg_relations_document_id"), "kg_relations", ["document_id"], unique=False)
    op.create_index(op.f("ix_kg_relations_id"), "kg_relations", ["id"], unique=False)
    op.create_index(op.f("ix_kg_relations_object_text"), "kg_relations", ["object_text"], unique=False)
    op.create_index(op.f("ix_kg_relations_predicate"), "kg_relations", ["predicate"], unique=False)
    op.create_index(op.f("ix_kg_relations_subject_text"), "kg_relations", ["subject_text"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_kg_relations_subject_text"), table_name="kg_relations")
    op.drop_index(op.f("ix_kg_relations_predicate"), table_name="kg_relations")
    op.drop_index(op.f("ix_kg_relations_object_text"), table_name="kg_relations")
    op.drop_index(op.f("ix_kg_relations_id"), table_name="kg_relations")
    op.drop_index(op.f("ix_kg_relations_document_id"), table_name="kg_relations")
    op.drop_index(op.f("ix_kg_relations_chunk_id"), table_name="kg_relations")
    op.drop_table("kg_relations")
    op.drop_index(op.f("ix_kg_entities_normalized_name"), table_name="kg_entities")
    op.drop_index(op.f("ix_kg_entities_name"), table_name="kg_entities")
    op.drop_index(op.f("ix_kg_entities_id"), table_name="kg_entities")
    op.drop_index(op.f("ix_kg_entities_entity_type"), table_name="kg_entities")
    op.drop_index(op.f("ix_kg_entities_document_id"), table_name="kg_entities")
    op.drop_index(op.f("ix_kg_entities_chunk_id"), table_name="kg_entities")
    op.drop_table("kg_entities")
