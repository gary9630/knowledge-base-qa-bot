"""add document lifecycle state

Revision ID: 0007_document_lifecycle
Revises: 0006_audit_events
Create Date: 2026-05-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_document_lifecycle"
down_revision: str | None = "0006_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "lifecycle_status",
            sa.Text(),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
    )
    op.add_column("documents", sa.Column("lifecycle_reason", sa.Text(), nullable=True))
    op.create_index("ix_documents_lifecycle_status", "documents", ["lifecycle_status"])


def downgrade() -> None:
    op.drop_index("ix_documents_lifecycle_status", table_name="documents")
    op.drop_column("documents", "lifecycle_reason")
    op.drop_column("documents", "lifecycle_status")
