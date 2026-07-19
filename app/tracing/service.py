from __future__ import annotations

from collections.abc import Mapping, Sequence
from pydantic import BaseModel

from app.core.constants import DEFAULT_TRACE_PAYLOAD_MAX_CHARS
from app.core.types import JsonObject, JsonValue
from app.db.models import TraceSpan

REDACTED_VALUE = "[REDACTED]"
SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "id_token",
    "password",
    "refresh_token",
    "secret",
    "set_cookie",
    "token",
    "access_token",
}


def _is_sensitive_field(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith("_secret")


def safe_json(
    value: object,
    max_length: int = DEFAULT_TRACE_PAYLOAD_MAX_CHARS,
) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > max_length:
            return value[:max_length] + "…"
        return value
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED_VALUE
                if _is_sensitive_field(key)
                else safe_json(item, max_length)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [safe_json(item, max_length) for item in value]
    if isinstance(value, BaseModel):
        return safe_json(value.model_dump(), max_length)
    return safe_json(str(value), max_length)


def serialize_span(span: TraceSpan, include_payload: bool = True) -> JsonObject:
    result: JsonObject = {
        "id": span.id,
        "user_id": span.user_id,
        "conversation_id": span.conversation_id,
        "thread_id": span.thread_id,
        "run_id": span.run_id,
        "parent_run_id": span.parent_run_id,
        "name": span.name,
        "span_type": span.span_type,
        "status": span.status,
        "model_name": span.model_name,
        "tool_name": span.tool_name,
        "prompt_tokens": span.prompt_tokens,
        "completion_tokens": span.completion_tokens,
        "total_tokens": span.total_tokens,
        "latency_ms": span.latency_ms,
        "error_message": span.error_message,
        "started_at": span.started_at.isoformat(),
        "ended_at": span.ended_at.isoformat() if span.ended_at else None,
    }
    if include_payload:
        result.update({"input": span.input, "output": span.output})
    return result
