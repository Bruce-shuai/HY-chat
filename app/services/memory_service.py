from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from langchain_core.messages import BaseMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TraceSpan, UserMemory

MAX_MEMORY_ITEMS = 20
MAX_MEMORY_VALUE_CHARS = 240

MEMORY_LABELS = {
    "profile.name": "用户姓名",
}

NAME_PATTERNS = [
    re.compile(
        r"(?:我叫|我的名字是|我的姓名是|叫我)\s*"
        r"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-·]{0,39})"
    ),
    re.compile(
        r"(?:my name is|call me)\s+"
        r"(?P<name>[A-Za-z][A-Za-z0-9_\-.' ]{0,39})",
        re.IGNORECASE,
    ),
]

FORGET_NAME_PATTERN = re.compile(
    r"(?:忘记|别记|不要记|不用记|删除|清除).{0,8}(?:我的)?(?:名字|姓名|name)",
    re.IGNORECASE,
)

INVALID_NAME_PREFIXES = (
    "一个",
    "一名",
    "不是",
    "不叫",
    "来自",
    "现在",
)


def content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, Sequence) and not isinstance(
        content, str | bytes | bytearray
    ):
        return "\n".join(
            text for item in content for text in [content_to_text(item)] if text.strip()
        )
    return ""


def message_to_text(message: BaseMessage | Mapping[str, object]) -> str:
    content = (
        message.get("content", "")
        if isinstance(message, Mapping)
        else getattr(message, "content", "")
    )
    return content_to_text(content)


def is_human_message(message: BaseMessage | Mapping[str, object]) -> bool:
    if isinstance(message, Mapping):
        message_type = message.get("type") or message.get("role")
    else:
        message_type = getattr(message, "type", None)
    return message_type in {"human", "user"}


def clean_memory_value(value: str) -> str:
    return " ".join(value.strip(" \t\r\n，。,.!?！？；;:：\"'“”‘’").split())[
        :MAX_MEMORY_VALUE_CHARS
    ]


def is_valid_name(value: str) -> bool:
    if not value or any(value.startswith(prefix) for prefix in INVALID_NAME_PREFIXES):
        return False
    if any(mark in value for mark in ("?", "？", "吗", "什么")):
        return False
    return len(value) <= 40


def extract_memory_updates(text: str) -> tuple[dict[str, str], set[str]]:
    upserts: dict[str, str] = {}
    deletes: set[str] = set()

    if FORGET_NAME_PATTERN.search(text):
        deletes.add("profile.name")

    for pattern in NAME_PATTERNS:
        for match in pattern.finditer(text):
            name = clean_memory_value(match.group("name"))
            if is_valid_name(name):
                upserts["profile.name"] = name

    return upserts, deletes


def remember_from_messages(
    db: Session,
    user_id: str,
    messages: Sequence[BaseMessage | Mapping[str, object]],
    *,
    source_thread_id: str | None = None,
) -> set[str]:
    upserts: dict[str, str] = {}
    deletes: set[str] = set()

    for message in messages:
        if not is_human_message(message):
            continue
        next_upserts, next_deletes = extract_memory_updates(message_to_text(message))
        deletes.update(next_deletes)
        upserts.update(next_upserts)

    if not upserts and not deletes:
        return set()

    changed = False
    for memory_key in deletes:
        row = db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.memory_key == memory_key,
            )
        )
        if row:
            db.delete(row)
            changed = True

    now = datetime.utcnow()
    for memory_key, memory_value in upserts.items():
        row = db.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.memory_key == memory_key,
            )
        )
        if row:
            if (
                row.memory_value == memory_value
                and row.source_thread_id == source_thread_id
            ):
                continue
            row.memory_value = memory_value
            row.source_thread_id = source_thread_id
            row.updated_at = now
        else:
            db.add(
                UserMemory(
                    user_id=user_id,
                    memory_key=memory_key,
                    memory_value=memory_value,
                    source_thread_id=source_thread_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        changed = True

    if changed:
        db.commit()
    return deletes


def backfill_memories_from_traces(
    db: Session,
    user_id: str,
    *,
    limit: int = 200,
) -> None:
    traces = list(
        db.scalars(
            select(TraceSpan)
            .where(TraceSpan.user_id == user_id, TraceSpan.span_type == "model")
            .order_by(TraceSpan.started_at.desc())
            .limit(limit)
        ).all()
    )
    for trace in reversed(traces):
        trace_input = trace.input if isinstance(trace.input, Mapping) else {}
        messages = trace_input.get("messages")
        if isinstance(messages, Sequence) and not isinstance(
            messages, str | bytes | bytearray
        ):
            remember_from_messages(
                db,
                user_id,
                messages,
                source_thread_id=trace.thread_id,
            )


def list_user_memories(
    db: Session,
    user_id: str,
    *,
    backfill_from_traces: bool = False,
) -> list[UserMemory]:
    memories = list(
        db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(MAX_MEMORY_ITEMS)
        ).all()
    )
    if memories or not backfill_from_traces:
        return memories

    backfill_memories_from_traces(db, user_id)
    return list(
        db.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(MAX_MEMORY_ITEMS)
        ).all()
    )


def user_memory_map(
    db: Session,
    user_id: str,
    *,
    backfill_from_traces: bool = False,
) -> dict[str, str]:
    return {
        memory.memory_key: memory.memory_value
        for memory in list_user_memories(
            db,
            user_id,
            backfill_from_traces=backfill_from_traces,
        )
    }


def build_memory_system_prompt(
    db: Session,
    user_id: str,
    *,
    backfill_from_traces: bool = False,
) -> str | None:
    memories = list_user_memories(
        db,
        user_id,
        backfill_from_traces=backfill_from_traces,
    )
    if not memories:
        return None

    lines = [
        "长期记忆（同一账号跨会话有效，仅在相关时使用；如果用户在当前消息中更新或否定这些信息，以当前消息为准）："
    ]
    for memory in memories:
        label = MEMORY_LABELS.get(memory.memory_key, memory.memory_key)
        lines.append(f"- {label}：{memory.memory_value}")
    return "\n".join(lines)
