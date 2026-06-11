"""add concept graph tables

Revision ID: 0012_concept_graph
Revises: 0011_section_position
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_concept_graph"
down_revision: str | None = "0011_section_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONCEPT_TABLES = (
    "concept_clusters",
    "concepts",
    "concept_edges",
    "concept_sources",
    "concept_extraction_state",
)


def upgrade() -> None:
    op.create_table(
        "concept_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_concept_clusters_name", "concept_clusters", ["name"], unique=True)

    op.create_table(
        "concepts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["cluster_id"], ["concept_clusters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_concepts_slug", "concepts", ["slug"], unique=True)

    op.create_table(
        "concept_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_concept_edges_source_target_kind",
        "concept_edges",
        ["source_concept_id", "target_concept_id", "kind"],
        unique=True,
    )
    op.create_index(
        "ix_concept_edges_source_concept_id", "concept_edges", ["source_concept_id"]
    )
    op.create_index(
        "ix_concept_edges_target_concept_id", "concept_edges", ["target_concept_id"]
    )

    op.create_table(
        "concept_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_concept_sources_concept_section",
        "concept_sources",
        ["concept_id", "section_id"],
        unique=True,
    )
    op.create_index("ix_concept_sources_concept_id", "concept_sources", ["concept_id"])
    op.create_index("ix_concept_sources_section_id", "concept_sources", ["section_id"])

    op.create_table(
        "concept_extraction_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_concept_extraction_state_document",
        "concept_extraction_state",
        ["document_id"],
        unique=True,
    )
    _create_updated_at_triggers()


def downgrade() -> None:
    _drop_updated_at_triggers()
    op.drop_index("ux_concept_extraction_state_document", table_name="concept_extraction_state")
    op.drop_table("concept_extraction_state")
    op.drop_index("ix_concept_sources_section_id", table_name="concept_sources")
    op.drop_index("ix_concept_sources_concept_id", table_name="concept_sources")
    op.drop_index("ux_concept_sources_concept_section", table_name="concept_sources")
    op.drop_table("concept_sources")
    op.drop_index("ix_concept_edges_target_concept_id", table_name="concept_edges")
    op.drop_index("ix_concept_edges_source_concept_id", table_name="concept_edges")
    op.drop_index("ux_concept_edges_source_target_kind", table_name="concept_edges")
    op.drop_table("concept_edges")
    op.drop_index("ux_concepts_slug", table_name="concepts")
    op.drop_table("concepts")
    op.drop_index("ux_concept_clusters_name", table_name="concept_clusters")
    op.drop_table("concept_clusters")


def _create_updated_at_triggers() -> None:
    for table_name in CONCEPT_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION kb_set_updated_at()
            """
        )


def _drop_updated_at_triggers() -> None:
    for table_name in CONCEPT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at ON {table_name}")
