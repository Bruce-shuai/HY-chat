from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.messages import AIMessage
from langchain_core.messages import BaseMessage

from app.cache.service import CacheLock, cache
from app.core.config import get_settings
from app.core.types import JsonObject, JsonValue
from app.tracing.service import safe_json

settings = get_settings()

CHAT_RESPONSE_CACHE_VERSION = "v1"
CHAT_RESPONSE_CACHE_PREFIX = "chat:graph_response"


def _message_payload(message: BaseMessage | Mapping[str, object]) -> JsonObject:
    if isinstance(message, Mapping):
        message_type = str(message.get("type") or message.get("role") or "")
        content = message.get("content", "")
        name = message.get("name")
        tool_calls = message.get("tool_calls")
        tool_call_id = message.get("tool_call_id")
    else:
        message_type = str(getattr(message, "type", message.__class__.__name__))
        content = getattr(message, "content", "")
        name = getattr(message, "name", None)
        tool_calls = getattr(message, "tool_calls", None)
        tool_call_id = getattr(message, "tool_call_id", None)

    payload: JsonObject = {
        "type": message_type,
        "content": safe_json(content),
    }
    if name:
        payload["name"] = str(name)
    if tool_calls:
        payload["tool_calls"] = safe_json(tool_calls)
    if tool_call_id:
        payload["tool_call_id"] = str(tool_call_id)
    return payload


def build_cache_key(
    user_id: str | None,
    model_name: str,
    messages: Sequence[BaseMessage | Mapping[str, object]],
    *,
    system_message: BaseMessage | Mapping[str, object] | None = None,
    extra_context: JsonValue | None = None,
) -> str | None:
    """Build a user-scoped key for deterministic plain-text model responses."""

    if not user_id:
        return None

    digest = cache.digest(
        CHAT_RESPONSE_CACHE_VERSION,
        user_id,
        model_name,
        _message_payload(system_message) if system_message else None,
        [_message_payload(message) for message in messages],
        extra_context,
    )
    return f"{CHAT_RESPONSE_CACHE_PREFIX}:{digest}"


def build_request_cache_key(
    request: ModelRequest,
    user_id: str | None,
    model_name: str,
) -> str | None:
    return build_cache_key(
        user_id,
        model_name,
        request.messages,
        system_message=request.system_message,
    )


def get_cached_response(cache_key: str | None) -> ModelResponse | None:
    if not cache_key:
        return None

    return _cached_response_from_value(cache.get_json(cache_key))


def _cached_response_from_value(value: object) -> ModelResponse | None:
    if not isinstance(value, Mapping):
        return None

    content = value.get("content")
    if not isinstance(content, str) or not content:
        return None

    return ModelResponse(
        result=[
            AIMessage(
                content=content,
                response_metadata={"cache_hit": True},
            )
        ]
    )


def acquire_response_lock(cache_key: str | None) -> CacheLock | None:
    if not cache_key:
        return None
    return cache.acquire_lock(cache_key, ttl=settings.cache_lock_ttl)


def wait_for_cached_response(cache_key: str | None) -> ModelResponse | None:
    if not cache_key:
        return None
    lookup = cache.wait_for_json(cache_key)
    if not lookup.hit:
        return None
    return _cached_response_from_value(lookup.value)


def release_response_lock(lock: CacheLock | None) -> bool:
    return cache.release_lock(lock)


def cacheable_response_content(response: ModelResponse) -> str | None:
    if response.structured_response is not None or len(response.result) != 1:
        return None

    message = response.result[0]
    if not isinstance(message, AIMessage):
        return None
    if getattr(message, "tool_calls", None) or getattr(
        message, "invalid_tool_calls", None
    ):
        return None
    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    if isinstance(additional_kwargs, Mapping) and additional_kwargs.get("tool_calls"):
        return None

    content = message.content
    return content if isinstance(content, str) and content else None


def store_response(cache_key: str | None, response: ModelResponse) -> bool:
    content = cacheable_response_content(response)
    if not cache_key or not content:
        return False
    return cache.set_json(
        cache_key,
        {"content": content},
        ttl=settings.chat_response_cache_ttl,
    )
