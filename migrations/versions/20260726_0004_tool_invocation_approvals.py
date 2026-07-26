"""add durable tool invocation and approval state

Revision ID: 20260726_0004
Revises: 20260721_0003
Create Date: 2026-07-26 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260726_0004"
down_revision: str | Sequence[str] | None = "20260721_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOOL_INVOCATION_STATUSES = (
    "pending",
    "pending_approval",
    "approved",
    "running",
    "succeeded",
    "failed",
    "rejected",
)
APPROVAL_STATUSES = ("pending", "approved", "edited", "rejected")


def _quoted_values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("runtime_run_id", sa.String(length=128), nullable=True),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("effective_tool_name", sa.String(length=128), nullable=False),
        sa.Column("requested_input", sa.JSON(), nullable=False),
        sa.Column("effective_input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_quoted_values(TOOL_INVOCATION_STATUSES)})",
            name="ck_tool_invocations_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_tool_invocations_user_idempotency_key",
        ),
    )
    op.create_index(
        "ix_tool_invocations_conversation_id",
        "tool_invocations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_tool_invocations_runtime_run_id",
        "tool_invocations",
        ["runtime_run_id"],
    )
    op.create_index(
        "ix_tool_invocations_status",
        "tool_invocations",
        ["status"],
    )
    op.create_index(
        "ix_tool_invocations_thread_id",
        "tool_invocations",
        ["thread_id"],
    )
    op.create_index(
        "ix_tool_invocations_tool_call_id",
        "tool_invocations",
        ["tool_call_id"],
    )
    op.create_index(
        "ix_tool_invocations_user_id",
        "tool_invocations",
        ["user_id"],
    )

    op.create_table(
        "tool_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invocation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision_payload", sa.JSON(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_quoted_values(APPROVAL_STATUSES)})",
            name="ck_tool_approvals_status",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invocation_id"],
            ["tool_invocations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "invocation_id",
            name="uq_tool_approvals_invocation_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_tool_approvals_user_idempotency_key",
        ),
    )
    op.create_index(
        "ix_tool_approvals_status",
        "tool_approvals",
        ["status"],
    )
    op.create_index(
        "ix_tool_approvals_user_id",
        "tool_approvals",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_approvals_user_id", table_name="tool_approvals")
    op.drop_index("ix_tool_approvals_status", table_name="tool_approvals")
    op.drop_table("tool_approvals")

    op.drop_index("ix_tool_invocations_user_id", table_name="tool_invocations")
    op.drop_index(
        "ix_tool_invocations_tool_call_id",
        table_name="tool_invocations",
    )
    op.drop_index("ix_tool_invocations_thread_id", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_status", table_name="tool_invocations")
    op.drop_index(
        "ix_tool_invocations_runtime_run_id",
        table_name="tool_invocations",
    )
    op.drop_index(
        "ix_tool_invocations_conversation_id",
        table_name="tool_invocations",
    )
    op.drop_table("tool_invocations")
