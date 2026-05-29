"""add eval tables

Revision ID: 0004_eval_tables
Revises: 0003_rag_indexing_indexes
Create Date: 2026-05-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_eval_tables"
down_revision: str | None = "0003_rag_indexing_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVAL_TABLES = ("eval_cases", "eval_runs", "eval_results")


def upgrade() -> None:
    op.create_table(
        "eval_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_decision", sa.Text(), nullable=False),
        sa.Column(
            "expected_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_cases_active", "eval_cases", ["active"])
    op.create_index("ix_eval_cases_created_at", "eval_cases", ["created_at"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "stats_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_status", "eval_runs", ["status"])
    op.create_index(
        "ix_eval_runs_status_created_at",
        "eval_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_decision", sa.Text(), nullable=False),
        sa.Column("actual_decision", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "expected_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "selected_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cited_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "unexpected_sources_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_id"], ["eval_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_case_id", "eval_results", ["case_id"])
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index("ix_eval_results_passed", "eval_results", ["passed"])
    _create_updated_at_triggers()


def downgrade() -> None:
    _drop_updated_at_triggers()
    op.drop_index("ix_eval_results_passed", table_name="eval_results")
    op.drop_index("ix_eval_results_run_id", table_name="eval_results")
    op.drop_index("ix_eval_results_case_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_status_created_at", table_name="eval_runs")
    op.drop_index("ix_eval_runs_status", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_created_at", table_name="eval_cases")
    op.drop_index("ix_eval_cases_active", table_name="eval_cases")
    op.drop_table("eval_cases")


def _create_updated_at_triggers() -> None:
    for table_name in EVAL_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION kb_set_updated_at()
            """
        )


def _drop_updated_at_triggers() -> None:
    for table_name in EVAL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_updated_at ON {table_name}")
