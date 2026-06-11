"""add concepts.origin for seed prune protection

Revision ID: 0013_concept_origin
Revises: 0012_concept_graph
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_concept_origin"
down_revision: str | None = "0012_concept_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "concepts",
        sa.Column(
            "origin",
            sa.Text(),
            server_default=sa.text("'extracted'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("concepts", "origin")
