from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, AIMessageChunk

from app.agents.chat import graph
from app.auth.dependencies import get_current_user
from app.cache.service import cache
from app.core.config import get_settings
from app.core.types import JsonObject
from app.db.models import Conversation, User
from app.db.session import get_db
from app.models.catalog import resolve_model
from app.policies.service import enforce_model
from app.schemas.chat import ChatStreamRequest
from sqlalchemy.orm import Session

router = APIRouter(prefix="/chat", tags=["chat"])
settings = get_settings()


def _sse(event: str, data: JsonObject) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


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
    if not settings.zhipu_api_key:
        try:
            enforce_model(db, user.id, model)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    messages = request.normalized_messages()
    thread_id = (
        request.thread_id
        or (conversation.thread_id if conversation else None)
        or str(uuid.uuid4())
    )
    cache_key = f"chat:response:{cache.digest(user.id, model, messages)}"

    async def event_stream() -> AsyncIterator[str]:
        cached = cache.get_json(cache_key) if request.use_cache else None
        if cached is not None:
            yield _sse("metadata", {"model": model, "cache_hit": True})
            yield _sse("token", {"content": cached["content"]})
            yield _sse("done", {"model": model, "cache_hit": True})
            return

        yield _sse("metadata", {"model": model, "cache_hit": False})
        content_parts: list[str] = []
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
                if isinstance(message, (AIMessage, AIMessageChunk)) and isinstance(
                    message.content, str
                ):
                    if message.content:
                        content_parts.append(message.content)
                        yield _sse("token", {"content": message.content})
            content = "".join(content_parts)
            if request.use_cache and content:
                cache.set_json(cache_key, {"content": content}, ttl=600)
            yield _sse("done", {"model": model, "cache_hit": False})
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
