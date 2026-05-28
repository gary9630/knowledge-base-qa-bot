"""add background worker heartbeats

Revision ID: 0009_worker_heartbeats
Revises: 0008_background_jobs
Create Date: 2026-05-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_worker_heartbeats"
down_revision: str | None = "0008_background_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_worker_heartbeats",
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'starting'"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_jobs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("current_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_task_type", sa.Text(), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_task_type", sa.Text(), nullable=True),
        sa.Column("last_job_status", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_background_worker_heartbeats_last_seen_at",
        "background_worker_heartbeats",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_background_worker_heartbeats_last_seen_at",
        table_name="background_worker_heartbeats",
    )
    op.drop_table("background_worker_heartbeats")
