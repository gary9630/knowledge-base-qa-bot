"""add rag indexing support indexes

Revision ID: 0003_rag_indexing_indexes
Revises: 0002_ingestion_jobs
Create Date: 2026-05-26 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_rag_indexing_indexes"
down_revision: str | None = "0002_ingestion_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_documents_filename", "documents", ["filename"])
    op.create_index("ix_documents_source_type", "documents", ["source_type"])
    op.create_index(
        "ix_indexing_jobs_status_created_at",
        "indexing_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ux_chunks_section_id_chunk_index",
        "chunks",
        ["section_id", "chunk_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_chunks_section_id_chunk_index", table_name="chunks")
    op.drop_index("ix_indexing_jobs_status_created_at", table_name="indexing_jobs")
    op.drop_index("ix_documents_source_type", table_name="documents")
    op.drop_index("ix_documents_filename", table_name="documents")
