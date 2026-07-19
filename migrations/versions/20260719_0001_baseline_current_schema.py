"""baseline current schema

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa

revision: str = "20260719_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1024


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {
        column["name"] for column in _inspector().get_columns(table_name)
    }


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = _inspector().get_indexes(table_name)
    constraints = _inspector().get_unique_constraints(table_name)
    return index_name in {item["name"] for item in indexes + constraints}


def _create_table_if_missing(
    table_name: str, *columns: sa.Column, **kwargs: object
) -> None:
    if not _table_exists(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if not _column_exists(table_name, column_name):
        return
    if _is_postgres():
        op.drop_column(table_name, column_name)
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def _drop_table_if_exists(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _create_core_tables() -> None:
    _create_table_if_missing(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=5), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "user_policies",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("allowed_models", sa.JSON(), nullable=False),
        sa.Column("rpm_limit", sa.Integer(), nullable=False),
        sa.Column("monthly_token_quota", sa.BigInteger(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), nullable=False),
        sa.Column("quota_reset_at", sa.DateTime(), nullable=False),
        sa.Column("allow_high_cost_tools", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    _create_table_if_missing(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("selected_model", sa.String(length=128), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "stored_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    _create_table_if_missing(
        "trace_spans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("parent_run_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("span_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_agent_tables() -> None:
    _create_table_if_missing(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("final_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "tool_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "model_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_rag_tables() -> None:
    _create_table_if_missing(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("stored_file_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["stored_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "sha256", name="uq_knowledge_user_sha256"),
    )
    _create_table_if_missing(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _adopt_existing_schema() -> None:
    _add_column_if_missing(
        "agent_runs",
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "knowledge_documents",
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "knowledge_documents",
        sa.Column(
            "stored_file_id",
            sa.String(length=36),
            sa.ForeignKey("stored_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    if _is_postgres() and _table_exists("knowledge_documents"):
        op.execute(
            "ALTER TABLE knowledge_documents DROP CONSTRAINT IF EXISTS knowledge_documents_sha256_key"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_user_sha256 "
            "ON knowledge_documents (user_id, sha256)"
        )


def _create_indexes() -> None:
    _create_index_if_missing("ix_users_email", "users", ["email"], unique=True)
    _create_index_if_missing("ix_users_is_active", "users", ["is_active"])
    _create_index_if_missing("ix_users_role", "users", ["role"])
    _create_index_if_missing(
        "ix_conversations_is_archived", "conversations", ["is_archived"]
    )
    _create_index_if_missing(
        "ix_conversations_thread_id", "conversations", ["thread_id"], unique=True
    )
    _create_index_if_missing("ix_conversations_user_id", "conversations", ["user_id"])
    _create_index_if_missing(
        "ix_stored_files_conversation_id", "stored_files", ["conversation_id"]
    )
    _create_index_if_missing("ix_stored_files_sha256", "stored_files", ["sha256"])
    _create_index_if_missing("ix_stored_files_user_id", "stored_files", ["user_id"])
    _create_index_if_missing(
        "ix_trace_spans_conversation_id", "trace_spans", ["conversation_id"]
    )
    _create_index_if_missing("ix_trace_spans_run_id", "trace_spans", ["run_id"])
    _create_index_if_missing("ix_trace_spans_span_type", "trace_spans", ["span_type"])
    _create_index_if_missing("ix_trace_spans_status", "trace_spans", ["status"])
    _create_index_if_missing("ix_trace_spans_thread_id", "trace_spans", ["thread_id"])
    _create_index_if_missing("ix_trace_spans_user_id", "trace_spans", ["user_id"])
    _create_index_if_missing("ix_agent_runs_status", "agent_runs", ["status"])
    _create_index_if_missing("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    _create_index_if_missing("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    _create_index_if_missing("ix_model_calls_run_id", "model_calls", ["run_id"])
    _create_index_if_missing(
        "ix_knowledge_documents_sha256", "knowledge_documents", ["sha256"]
    )
    _create_index_if_missing(
        "ix_knowledge_documents_status", "knowledge_documents", ["status"]
    )
    _create_index_if_missing(
        "ix_knowledge_documents_user_id", "knowledge_documents", ["user_id"]
    )
    _create_index_if_missing(
        "ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"]
    )


def _remove_legacy_image_generation_schema() -> None:
    _drop_table_if_exists("image_generations")
    _drop_column_if_exists("user_policies", "allow_image_generation")


def upgrade() -> None:
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    _create_core_tables()
    _create_agent_tables()
    _create_rag_tables()
    _adopt_existing_schema()
    _create_indexes()
    _remove_legacy_image_generation_schema()


def downgrade() -> None:
    _drop_index_if_exists("ix_knowledge_chunks_document_id", "knowledge_chunks")
    _drop_index_if_exists("ix_knowledge_documents_user_id", "knowledge_documents")
    _drop_index_if_exists("ix_knowledge_documents_status", "knowledge_documents")
    _drop_index_if_exists("ix_knowledge_documents_sha256", "knowledge_documents")
    _drop_index_if_exists("ix_model_calls_run_id", "model_calls")
    _drop_index_if_exists("ix_tool_calls_run_id", "tool_calls")
    _drop_index_if_exists("ix_agent_runs_user_id", "agent_runs")
    _drop_index_if_exists("ix_agent_runs_status", "agent_runs")
    _drop_index_if_exists("ix_trace_spans_user_id", "trace_spans")
    _drop_index_if_exists("ix_trace_spans_thread_id", "trace_spans")
    _drop_index_if_exists("ix_trace_spans_status", "trace_spans")
    _drop_index_if_exists("ix_trace_spans_span_type", "trace_spans")
    _drop_index_if_exists("ix_trace_spans_run_id", "trace_spans")
    _drop_index_if_exists("ix_trace_spans_conversation_id", "trace_spans")
    _drop_index_if_exists("ix_stored_files_user_id", "stored_files")
    _drop_index_if_exists("ix_stored_files_sha256", "stored_files")
    _drop_index_if_exists("ix_stored_files_conversation_id", "stored_files")
    _drop_index_if_exists("ix_conversations_user_id", "conversations")
    _drop_index_if_exists("ix_conversations_thread_id", "conversations")
    _drop_index_if_exists("ix_conversations_is_archived", "conversations")
    _drop_index_if_exists("ix_users_role", "users")
    _drop_index_if_exists("ix_users_is_active", "users")
    _drop_index_if_exists("ix_users_email", "users")

    _drop_table_if_exists("knowledge_chunks")
    _drop_table_if_exists("knowledge_documents")
    _drop_table_if_exists("model_calls")
    _drop_table_if_exists("tool_calls")
    _drop_table_if_exists("agent_runs")
    _drop_table_if_exists("trace_spans")
    _drop_table_if_exists("stored_files")
    _drop_table_if_exists("conversations")
    _drop_table_if_exists("user_policies")
    _drop_table_if_exists("users")
