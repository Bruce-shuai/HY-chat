"""add user long-term memories

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260720_0002"
down_revision: str | Sequence[str] | None = "20260719_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("memory_key", sa.String(length=80), nullable=False),
        sa.Column("memory_value", sa.Text(), nullable=False),
        sa.Column("source_thread_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "memory_key",
            name="uq_user_memories_user_key",
        ),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])
    op.create_index(
        "ix_user_memories_source_thread_id",
        "user_memories",
        ["source_thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_memories_source_thread_id", table_name="user_memories")
    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_table("user_memories")
