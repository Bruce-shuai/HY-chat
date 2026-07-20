"""Primary conversational LangGraph and its policy/tracing middleware.

Request flow:

1. LangGraph receives messages plus ``ChatState``.
2. ``PolicyTraceMiddleware`` authorizes each model/tool call and records traces.
3. The selected model may call tools from ``app.tools.registry``.
4. Without a model API key, a deterministic mock graph keeps the full transport
   and authorization path usable in local development and tests.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain.messages import AIMessage, ToolMessage
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
    PolicyViolation,
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


SYSTEM_PROMPT = f"""你是 HY-chat，一个具备通用对话、知识库检索、代码分析、图片生成、联网搜索、天气查询和股票查询能力的智能助手。

当前日期：{date.today().isoformat()}。

工具使用规则：
1. 用户询问上传文档或知识库内容时，先调用 search_knowledge_base，并引用文件名及页码、幻灯片或工作表信息。
2. 用户询问代码项目时，先使用工作区工具读取真实文件，不要编造未读取的内容。
3. 用户要求生成图片、画图、制作海报或视觉创意时，使用 generate_image。工具返回 image_url 或 markdown 后，最终回复必须用 Markdown 图片语法展示图片，并简短说明可以继续调整风格、构图或尺寸；不要改口说自己没有图片生成能力。
4. 用户询问最新信息或明确要求联网时，使用 web_search，并在回答中提供来源链接。
5. 天气问题使用 get_weather；股票行情使用 get_stock_quote，并明确行情可能延迟且不构成投资建议。用户用中文名称查询股票或指数时，先传入常见名称或对应代码，例如：标普500/S&P500 用 SPY，纳斯达克100/纳指用 QQQ，道琼斯/道指用 DIA。
6. 工具返回错误时，清楚说明缺少的配置或外部服务问题，不要虚构结果。

默认使用中文回复，除非用户明确要求其他语言。
"""


HITL_TOOL_CONFIG: dict[str, InterruptOnConfig] = {
    "generate_image": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "即将生成图片，请确认图片描述和尺寸。",
    },
    "web_search": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "即将联网搜索，请确认搜索关键词和结果数量。",
    },
    "get_stock_quote": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "即将访问外部股票行情服务，请确认股票代码或指数名称。",
    },
}


def _supports_hitl_resume(request: ToolCallRequest) -> bool:
    """Only interrupt runs served by LangGraph Server, which supports resume."""

    return getattr(request.runtime, "server_info", None) is not None


def build_hitl_middleware() -> HumanInTheLoopMiddleware:
    interrupt_on: dict[str, InterruptOnConfig] = {
        tool_name: {**config, "when": _supports_hitl_resume}
        for tool_name, config in HITL_TOOL_CONFIG.items()
    }
    return HumanInTheLoopMiddleware(
        interrupt_on=interrupt_on,
        description_prefix="该工具需要人工确认",
    )


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


def _content_title(content: object) -> str:
    if isinstance(content, str):
        return " ".join(content.split())
    if isinstance(content, Mapping):
        text = content.get("text")
        return " ".join(text.split()) if isinstance(text, str) else ""
    if isinstance(content, Sequence) and not isinstance(
        content, str | bytes | bytearray
    ):
        texts: list[str] = []
        has_non_text_block = False
        for block in content:
            if isinstance(block, str):
                if block.strip():
                    texts.append(block.strip())
                continue
            if not isinstance(block, Mapping):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            elif block.get("type"):
                has_non_text_block = True
        if texts:
            return " ".join(" ".join(texts).split())
        return "附件消息" if has_non_text_block else ""
    return ""


def _conversation_title_from_state(state: ChatState) -> str:
    for message in state.get("messages", []):
        message_type = getattr(message, "type", None)
        content = getattr(message, "content", "")
        if isinstance(message, Mapping):
            message_type = message.get("type") or message.get("role")
            content = message.get("content", "")
        if message_type not in {"human", "user"}:
            continue
        title = _content_title(content)
        if title:
            return title[:80]
    return "新会话"


def _tool_error_message(result: object) -> str | None:
    """Extract structured tool failures so traces do not report false success."""

    status = getattr(result, "status", None)
    content = getattr(result, "content", result)
    parsed = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = content

    if isinstance(parsed, Mapping) and parsed.get("error"):
        return str(parsed["error"])
    if status == "error":
        return str(content)[:2_000] or "Tool call failed"
    return None


def _tool_failure_message(request: ToolCallRequest, message: str) -> ToolMessage:
    tool_name = str(request.tool_call.get("name") or "unknown")
    tool_call_id = str(request.tool_call.get("id") or uuid.uuid4())
    return ToolMessage(
        content=json.dumps({"error": message}, ensure_ascii=False),
        tool_call_id=tool_call_id,
        name=tool_name,
    )


def _policy_violation_response(message: str) -> ModelResponse:
    if message.startswith("请求过于频繁"):
        content = (
            "发送太频繁了。\n\n"
            f"{message}。请稍等一分钟后再继续发送。"
        )
    elif "本月标记配额已用尽" in message:
        content = "本月额度已用尽。\n\n当前账号的本月标记配额已经用完，请联系管理员调整额度后再继续使用。"
    elif message.startswith("当前账号无权使用模型"):
        content = f"当前账号没有这个模型的使用权限。\n\n{message}。请切换其他模型，或联系管理员开通权限。"
    else:
        content = f"当前请求被权限策略拦截。\n\n原因：{message}"

    return ModelResponse(result=[AIMessage(content=content)])


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
        conversation = Conversation(
            user_id=user_id,
            thread_id=thread_id,
            title=_conversation_title_from_state(state),
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
        try:
            overridden, db, user_id, trace = self._prepare_model_call(request)
        except PolicyViolation as exc:
            logger.warning("Model call blocked by policy: %s", exc)
            return _policy_violation_response(str(exc))
        try:
            response = handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            return response
        except PolicyViolation as exc:
            self._fail_trace(db, trace, exc, started)
            return _policy_violation_response(str(exc))
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()

    async def awrap_model_call(self, request: ModelRequest, handler):
        started = time.perf_counter()
        try:
            overridden, db, user_id, trace = self._prepare_model_call(request)
        except PolicyViolation as exc:
            logger.warning("Model call blocked by policy: %s", exc)
            return _policy_violation_response(str(exc))
        try:
            response = await handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            return response
        except PolicyViolation as exc:
            self._fail_trace(db, trace, exc, started)
            return _policy_violation_response(str(exc))
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            db.close()

    @staticmethod
    def _prepare_tool_call(request: ToolCallRequest):
        state_user_id = (
            request.state.get("auth_user_id")
            if isinstance(request.state, Mapping)
            else None
        )
        user_id = runtime_user_id(request.runtime) or state_user_id
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
        error_message = _tool_error_message(result)
        if trace:
            trace.status = "error" if error_message else "success"
            trace.output = {"result": safe_json(getattr(result, "content", result))}
            trace.error_message = error_message
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
        db = None
        trace = None
        try:
            db, trace = self._prepare_tool_call(request)
            result = handler(request)
            self._finish_tool_call(db, trace, result, started)
            return result
        except PolicyViolation as exc:
            if db:
                self._fail_trace(db, trace, exc, started)
            return _tool_failure_message(request, str(exc))
        except Exception as exc:
            if db:
                self._fail_trace(db, trace, exc, started)
            raise
        finally:
            if db:
                db.close()

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = time.perf_counter()
        db = None
        trace = None
        try:
            db, trace = self._prepare_tool_call(request)
            result = await handler(request)
            self._finish_tool_call(db, trace, result, started)
            return result
        except PolicyViolation as exc:
            if db:
                self._fail_trace(db, trace, exc, started)
            return _tool_failure_message(request, str(exc))
        except Exception as exc:
            if db:
                self._fail_trace(db, trace, exc, started)
            raise
        finally:
            if db:
                db.close()


def _build_mock_graph():
    """Keep all transport and model-selection paths testable without an API key."""

    def mock_chat(state: ChatState, runtime: Runtime) -> dict[str, object]:
        last_message = state["messages"][-1] if state["messages"] else None
        content = getattr(last_message, "content", "")
        selected = state.get("selected_model") or settings.zhipu_chat_model
        message = AIMessage(
            content=(
                "【模拟模型输出】\n\n"
                f"当前模型：`{selected}`。HY-chat 的聊天链路已连接成功。配置真实模型密钥后即可"
                "使用真实模型、工具调用与知识库检索回答。\n\n"
                f"你刚才发送的是：{content}"
            )
        )
        server_user_id = runtime_user_id(runtime)
        user_id = server_user_id or state.get("auth_user_id")
        if user_id:
            db = SessionLocal()
            try:
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

    middleware: list[AgentMiddleware] = [PolicyTraceMiddleware()]
    if settings.hitl_enabled:
        middleware.append(build_hitl_middleware())

    return create_agent(
        model=get_chat_model(settings.zhipu_chat_model, streaming=True),
        tools=get_agent_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
        state_schema=ChatState,
        name="hy-chat",
    )


graph = build_chat_graph()
