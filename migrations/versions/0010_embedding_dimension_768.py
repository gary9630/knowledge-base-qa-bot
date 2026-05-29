"""switch embeddings to 768 dimensions

Revision ID: 0010_embedding_dimension_768
Revises: 0009_worker_heartbeats
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_embedding_dimension_768"
down_revision: str | None = "0009_worker_heartbeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute(
        "ALTER TABLE chunks "
        "ALTER COLUMN embedding TYPE vector(768) "
        "USING NULL::vector(768)"
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.execute(
        "ALTER TABLE chunks "
        "ALTER COLUMN embedding TYPE vector(1536) "
        "USING NULL::vector(1536)"
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
