"""add eval automation provenance

Revision ID: 0005_eval_automation
Revises: 0004_eval_tables
Create Date: 2026-05-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_eval_automation"
down_revision: str | None = "0004_eval_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_cases",
        sa.Column(
            "source_kind",
            sa.Text(),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
    )
    op.add_column("eval_cases", sa.Column("seed_key", sa.Text(), nullable=True))
    op.add_column(
        "eval_cases",
        sa.Column("promoted_feedback_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_eval_cases_promoted_feedback_id_feedback",
        "eval_cases",
        "feedback",
        ["promoted_feedback_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_eval_cases_source_kind", "eval_cases", ["source_kind"])
    op.create_index("ux_eval_cases_seed_key", "eval_cases", ["seed_key"], unique=True)
    op.create_index(
        "ux_eval_cases_promoted_feedback_id",
        "eval_cases",
        ["promoted_feedback_id"],
        unique=True,
    )

    op.add_column(
        "eval_runs",
        sa.Column("trigger", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    )
    op.create_index(
        "ix_eval_runs_trigger_created_at",
        "eval_runs",
        ["trigger", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_runs_trigger_created_at", table_name="eval_runs")
    op.drop_column("eval_runs", "trigger")

    op.drop_index("ux_eval_cases_promoted_feedback_id", table_name="eval_cases")
    op.drop_index("ux_eval_cases_seed_key", table_name="eval_cases")
    op.drop_index("ix_eval_cases_source_kind", table_name="eval_cases")
    op.drop_constraint(
        "fk_eval_cases_promoted_feedback_id_feedback",
        "eval_cases",
        type_="foreignkey",
    )
    op.drop_column("eval_cases", "promoted_feedback_id")
    op.drop_column("eval_cases", "seed_key")
    op.drop_column("eval_cases", "source_kind")
