"""add provider_call_logs for full LLM request/response auditing

Revision ID: 0015_provider_call_logs
Revises: 0014_runtime_settings
Create Date: 2026-06-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0015_provider_call_logs"
down_revision: str | None = "0014_runtime_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_call_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("retrieval_event_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("client_request_id", sa.Text(), nullable=True),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("usage_json", JSONB(), nullable=True),
        sa.Column("request_json", JSONB(), nullable=True),
        sa.Column("response_json", JSONB(), nullable=True),
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
    )
    op.create_index(
        "ix_provider_call_logs_conversation_id",
        "provider_call_logs",
        ["conversation_id"],
    )
    op.create_index(
        "ix_provider_call_logs_retrieval_event_id",
        "provider_call_logs",
        ["retrieval_event_id"],
    )
    op.create_index("ix_provider_call_logs_operation", "provider_call_logs", ["operation"])
    op.create_index("ix_provider_call_logs_status", "provider_call_logs", ["status"])
    op.create_index("ix_provider_call_logs_created_at", "provider_call_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("provider_call_logs")
