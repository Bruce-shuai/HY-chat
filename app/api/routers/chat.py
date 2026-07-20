from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, AIMessageChunk, ToolMessage

from app.agents.chat import graph
from app.auth.dependencies import get_current_user
from app.cache.service import cache
from app.core.config import get_settings
from app.core.types import JsonObject
from app.db.models import Conversation, User
from app.db.session import get_db
from app.models.catalog import resolve_model
from app.policies.service import authorize_model_access
from app.schemas.chat import ChatStreamRequest
from sqlalchemy.orm import Session

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _sse(event: str, data: JsonObject) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


def _tool_error_from_content(content: object) -> str | None:
    parsed = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None

    if isinstance(parsed, Mapping) and parsed.get("error"):
        return str(parsed["error"])
    return None


def _empty_response_fallback(tool_errors: list[str]) -> str:
    if tool_errors:
        reason = "；".join(dict.fromkeys(tool_errors))
        return f"查询失败。\n\n原因：{reason}"
    return "本次请求没有生成可展示的回答，请稍后重试。"


@router.post("/stream")
async def stream_chat(
    request: ChatStreamRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        model = resolve_model(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conversation = None
    if request.conversation_id:
        conversation = db.get(Conversation, request.conversation_id)
        if not conversation or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")

    messages = request.normalized_messages()
    thread_id = (
        request.thread_id
        or (conversation.thread_id if conversation else None)
        or str(uuid.uuid4())
    )
    cache_key = f"chat:response:{cache.digest(user.id, model, messages)}"
    request_id = str(uuid.uuid4())
    cached = cache.get_json(cache_key) if request.use_cache else None
    try:
        authorize_model_access(db, user.id, model)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        if cached is not None:
            yield _sse(
                "metadata",
                {"model": model, "cache_hit": True, "request_id": request_id},
            )
            yield _sse("token", {"content": cached["content"]})
            yield _sse(
                "done", {"model": model, "cache_hit": True, "request_id": request_id}
            )
            return

        yield _sse(
            "metadata",
            {"model": model, "cache_hit": False, "request_id": request_id},
        )
        content_parts: list[str] = []
        tool_errors: list[str] = []
        try:
            async for chunk in graph.astream(
                {
                    "messages": messages,
                    "selected_model": model,
                    "auth_user_id": user.id,
                    "conversation_id": request.conversation_id,
                },
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            ):
                message = chunk[0] if isinstance(chunk, tuple) else chunk
                if isinstance(message, ToolMessage):
                    error_message = _tool_error_from_content(message.content)
                    if error_message:
                        tool_errors.append(error_message)
                if isinstance(message, (AIMessage, AIMessageChunk)) and isinstance(
                    message.content, str
                ):
                    if message.content:
                        content_parts.append(message.content)
                        yield _sse("token", {"content": message.content})
            content = "".join(content_parts)
            if not content:
                content = _empty_response_fallback(tool_errors)
                content_parts.append(content)
                yield _sse("token", {"content": content})
            if request.use_cache and content:
                cache.set_json(
                    cache_key,
                    {"content": content},
                    ttl=settings.chat_response_cache_ttl,
                )
            yield _sse(
                "done",
                {"model": model, "cache_hit": False, "request_id": request_id},
            )
        except Exception:
            logger.exception(
                "Chat stream failed request_id=%s user_id=%s model=%s",
                request_id,
                user.id,
                model,
            )
            if not content_parts:
                yield _sse(
                    "token",
                    {"content": "查询失败。\n\n原因：聊天服务暂时不可用，请稍后重试。"},
                )
            yield _sse(
                "error",
                {
                    "message": "聊天服务暂时不可用，请稍后重试",
                    "request_id": request_id,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
