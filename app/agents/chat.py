"""Primary conversational LangGraph and its policy/tracing middleware.

Request flow:

1. LangGraph receives messages plus ``ChatState``.
2. ``PolicyTraceMiddleware`` authorizes each model/tool call and records traces.
3. The selected model may call tools from ``app.tools.registry``.
4. Without a model API key, a deterministic mock graph keeps the full transport
   and authorization path usable in local development and tests.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain.messages import AIMessage
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.types import JsonObject
from app.db.models import Conversation, TraceSpan
from app.db.session import SessionLocal
from app.models.catalog import get_chat_model, resolve_model
from app.policies.service import (
    enforce_model,
    enforce_tool,
    record_token_usage,
    runtime_user_id,
)
from app.tools.registry import get_agent_tools
from app.tracing.service import safe_json

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class ChatState(AgentState):
    selected_model: NotRequired[str]
    auth_user_id: NotRequired[str]
    conversation_id: NotRequired[str]


SYSTEM_PROMPT = f"""你是 HY-chat，一个具备通用对话、RAG 知识库检索、代码分析、联网搜索、天气查询、股票查询和图片生成能力的 AI 助手。

当前日期：{date.today().isoformat()}。

工具使用规则：
1. 用户询问上传文档或知识库内容时，先调用 search_knowledge_base，并引用文件名及页码、幻灯片或工作表信息。
2. 用户询问代码项目时，先使用工作区工具读取真实文件，不要编造未读取的内容。
3. 用户询问最新信息或明确要求联网时，使用 web_search，并在回答中提供来源链接。
4. 天气问题使用 get_weather；股票行情使用 get_stock_quote，并明确行情可能延迟且不构成投资建议。
5. 用户要求文生图时直接使用 generate_image；要求图生图时先用 list_stored_images 找到 source_file_id，再调用 generate_image。
6. 工具返回错误时，清楚说明缺少的配置或外部服务问题，不要虚构结果。

默认使用中文回复，除非用户明确要求其他语言。
"""


def _runtime_thread_id(runtime: object) -> str | None:
    execution_info = getattr(runtime, "execution_info", None)
    execution_thread_id = getattr(execution_info, "thread_id", None)
    if execution_thread_id:
        return str(execution_thread_id)
    config = getattr(runtime, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else None


def _message_preview(messages: Sequence[BaseMessage]) -> list[JsonObject]:
    return [
        {
            "type": getattr(message, "type", message.__class__.__name__),
            "content": safe_json(getattr(message, "content", ""), max_length=2_000),
        }
        for message in messages[-8:]
    ]


def _token_usage(response: ModelResponse) -> tuple[int, int, int]:
    prompt = completion = total = 0
    for message in response.result:
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        token_usage = (
            metadata.get("token_usage", {}) if isinstance(metadata, dict) else {}
        )
        prompt += int(
            usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0
        )
        completion += int(
            usage.get("output_tokens") or token_usage.get("completion_tokens") or 0
        )
        total += int(usage.get("total_tokens") or token_usage.get("total_tokens") or 0)
    return prompt, completion, total or prompt + completion


def _ensure_conversation(
    db: Session,
    user_id: str,
    thread_id: str | None,
    state: ChatState,
    model_name: str,
) -> Conversation | None:
    if not thread_id:
        return None
    conversation = db.scalar(
        select(Conversation).where(Conversation.thread_id == thread_id)
    )
    if conversation and conversation.user_id != user_id:
        raise PermissionError("无权访问该会话")
    if not conversation:
        title = "新会话"
        for message in state.get("messages", []):
            if getattr(message, "type", None) in {"human", "user"}:
                title = str(getattr(message, "content", ""))[:80] or title
                break
        conversation = Conversation(
            user_id=user_id,
            thread_id=thread_id,
            title=title,
            selected_model=model_name,
        )
        db.add(conversation)
    else:
        conversation.selected_model = model_name
        conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    return conversation


class PolicyTraceMiddleware(AgentMiddleware):
    """Enforce server-side policy and persist observability around agent calls.

    Both synchronous and asynchronous hooks delegate to the same preparation
    and completion helpers so their behavior stays equivalent.
    """

    state_schema = ChatState

    def _prepare_model_call(
        self, request: ModelRequest
    ) -> tuple[ModelRequest, Session, str | None, TraceSpan | None]:
        selected = resolve_model(request.state.get("selected_model"))
        user_id = runtime_user_id(request.runtime) or request.state.get("auth_user_id")
        db = SessionLocal()
        try:
            conversation = None
            if user_id:
                enforce_model(db, user_id, selected)
                conversation = _ensure_conversation(
                    db,
                    user_id,
                    _runtime_thread_id(request.runtime),
                    request.state,
                    selected,
                )
            trace = None
            if user_id:
                trace = TraceSpan(
                    user_id=user_id,
                    conversation_id=(
                        conversation.id
                        if conversation
                        else request.state.get("conversation_id")
                    ),
                    thread_id=_runtime_thread_id(request.runtime),
                    run_id=str(uuid.uuid4()),
                    name=f"model:{selected}",
                    span_type="model",
                    model_name=selected,
                    input={"messages": _message_preview(request.messages)},
                )
                db.add(trace)
                db.commit()
                db.refresh(trace)
            logger.info(
                "Model call started user_id=%s thread_id=%s model=%s",
                user_id,
                _runtime_thread_id(request.runtime),
                selected,
            )
            return (
                request.override(model=get_chat_model(selected, streaming=True)),
                db,
                user_id,
                trace,
            )
        except Exception:
            db.close()
            raise

    @staticmethod
    def _finish_model_call(
        db: Session,
        user_id: str | None,
        trace: TraceSpan | None,
        response: ModelResponse,
        started: float,
    ) -> None:
        prompt, completion, total = _token_usage(response)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if user_id:
            record_token_usage(db, user_id, total)
        if trace:
            trace.status = "success"
            trace.prompt_tokens = prompt
            trace.completion_tokens = completion
            trace.total_tokens = total
            trace.latency_ms = latency_ms
            trace.output = {"messages": _message_preview(response.result)}
            trace.ended_at = datetime.utcnow()
            db.commit()
        logger.info(
            "Model call completed user_id=%s model=%s latency_ms=%s tokens=%s",
            user_id,
            trace.model_name if trace else None,
            latency_ms,
            total,
        )

    @staticmethod
    def _fail_trace(
        db: Session,
        trace: TraceSpan | None,
        exc: Exception,
        started: float,
    ) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        if trace:
            trace.status = "error"
            trace.error_message = str(exc)
            trace.latency_ms = latency_ms
            trace.ended_at = datetime.utcnow()
            db.commit()
        logger.warning(
            "Agent call failed span=%s model=%s tool=%s error=%s latency_ms=%s",
            trace.span_type if trace else None,
            trace.model_name if trace else None,
            trace.tool_name if trace else None,
            type(exc).__name__,
            latency_ms,
        )

    def wrap_model_call(self, request: ModelRequest, handler):
        started = time.perf_counter()
        overridden, db, user_id, trace = self._prepare_model_call(request)
        try:
            response = handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            return response
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()

    async def awrap_model_call(self, request: ModelRequest, handler):
        started = time.perf_counter()
        overridden, db, user_id, trace = self._prepare_model_call(request)
        try:
            response = await handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            return response
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()

    @staticmethod
    def _prepare_tool_call(request: ToolCallRequest):
        user_id = runtime_user_id(request.runtime)
        name = str(request.tool_call.get("name") or "unknown")
        db = SessionLocal()
        try:
            if user_id:
                enforce_tool(db, user_id, name)
            trace = None
            if user_id:
                thread_id = _runtime_thread_id(request.runtime)
                conversation = (
                    db.scalar(
                        select(Conversation).where(Conversation.thread_id == thread_id)
                    )
                    if thread_id
                    else None
                )
                trace = TraceSpan(
                    user_id=user_id,
                    conversation_id=conversation.id if conversation else None,
                    thread_id=thread_id,
                    run_id=str(request.tool_call.get("id") or uuid.uuid4()),
                    name=f"tool:{name}",
                    span_type="tool",
                    tool_name=name,
                    input=safe_json(request.tool_call.get("args") or {}),
                )
                db.add(trace)
                db.commit()
                db.refresh(trace)
            logger.info(
                "Tool call started user_id=%s thread_id=%s tool=%s",
                user_id,
                _runtime_thread_id(request.runtime),
                name,
            )
            return db, trace
        except Exception:
            db.close()
            raise

    @staticmethod
    def _finish_tool_call(db, trace, result, started: float):
        latency_ms = int((time.perf_counter() - started) * 1000)
        if trace:
            trace.status = "success"
            trace.output = {"result": safe_json(getattr(result, "content", result))}
            trace.latency_ms = latency_ms
            trace.ended_at = datetime.utcnow()
            db.commit()
        logger.info(
            "Tool call completed tool=%s latency_ms=%s",
            trace.tool_name if trace else None,
            latency_ms,
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        started = time.perf_counter()
        db, trace = self._prepare_tool_call(request)
        try:
            result = handler(request)
            self._finish_tool_call(db, trace, result, started)
            return result
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = time.perf_counter()
        db, trace = self._prepare_tool_call(request)
        try:
            result = await handler(request)
            self._finish_tool_call(db, trace, result, started)
            return result
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()


def _build_mock_graph():
    """Keep all transport and model-selection paths testable without an API key."""

    def mock_chat(state: ChatState, runtime: Runtime) -> dict[str, object]:
        last_message = state["messages"][-1] if state["messages"] else None
        content = getattr(last_message, "content", "")
        selected = state.get("selected_model") or settings.zhipu_chat_model
        message = AIMessage(
            content=(
                "【Mock 模型输出】\n\n"
                f"当前模型：`{selected}`。HY-chat 的聊天链路已连接成功。配置 `ZHIPU_API_KEY` 后即可"
                "使用真实模型、Tool Calling 与 RAG 回答。\n\n"
                f"你刚才发送的是：{content}"
            )
        )
        server_user_id = runtime_user_id(runtime)
        user_id = server_user_id
        if user_id:
            db = SessionLocal()
            try:
                if server_user_id:
                    enforce_model(db, user_id, selected)
                conversation = _ensure_conversation(
                    db,
                    user_id,
                    _runtime_thread_id(runtime),
                    state,
                    selected,
                )
                db.add(
                    TraceSpan(
                        user_id=user_id,
                        conversation_id=(
                            conversation.id
                            if conversation
                            else state.get("conversation_id")
                        ),
                        thread_id=_runtime_thread_id(runtime),
                        run_id=str(uuid.uuid4()),
                        name=f"model:{selected}:mock",
                        span_type="model",
                        status="success",
                        model_name=selected,
                        input={"messages": _message_preview(state["messages"])},
                        output={"messages": _message_preview([message])},
                        latency_ms=0,
                        ended_at=datetime.utcnow(),
                    )
                )
                db.commit()
            finally:
                db.close()
        return {
            "selected_model": selected,
            "messages": [message],
        }

    builder = StateGraph(ChatState)
    builder.add_node("mock_chat", mock_chat)
    builder.add_edge(START, "mock_chat")
    builder.add_edge("mock_chat", END)
    return builder.compile()


def build_chat_graph():
    """Create the production agent or the keyless development substitute."""

    if not settings.zhipu_api_key:
        return _build_mock_graph()

    return create_agent(
        model=get_chat_model(settings.zhipu_chat_model, streaming=True),
        tools=get_agent_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=[PolicyTraceMiddleware()],
        state_schema=ChatState,
        name="hy-chat",
    )


graph = build_chat_graph()
