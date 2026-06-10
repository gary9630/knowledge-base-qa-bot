"""add section document-order position

Revision ID: 0011_section_position
Revises: 0010_embedding_dimension_768
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_section_position"
down_revision: str | None = "0010_embedding_dimension_768"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sections", sa.Column("position", sa.Integer(), nullable=True))
    op.create_index("ix_sections_document_position", "sections", ["document_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_sections_document_position", table_name="sections")
    op.drop_column("sections", "position")
