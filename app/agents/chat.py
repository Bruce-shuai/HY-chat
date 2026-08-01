"""Primary conversational LangGraph and its policy/tracing middleware.

Request flow:

1. LangGraph receives messages plus ``ChatState``.
2. ``PolicyTraceMiddleware`` authorizes each model/tool call and records traces.
3. The selected model may call tools from ``app.tools.registry``.
4. Without a model API key, a deterministic mock graph keeps the full transport
   and authorization path usable in local development and tests.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
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
from langchain.agents.middleware import human_in_the_loop as hitl_module
from langchain.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pypdf import filters as pypdf_filters
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_contact import append_admin_contact
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.types import JsonObject, ToolInvocationStatus
from app.db.models import Conversation, TraceSpan
from app.db.session import SessionLocal
from app.models.catalog import get_chat_model, model_supports_images, resolve_model
from app.policies.service import (
    PolicyViolation,
    authorize_model_access,
    enforce_model,
    enforce_tool,
    record_token_usage,
    runtime_user_id,
)
from app.services.memory_service import (
    build_memory_system_prompt,
    message_to_text,
    remember_from_messages,
    user_memory_map,
)
from app.services.tool_invocation_service import (
    ApprovalDecision,
    ToolInvocationClaim,
    ToolInvocationConflict,
    ToolInvocationOwnershipError,
    claim_tool_invocation,
    complete_tool_invocation,
    ensure_pending_approvals,
    fail_tool_invocation,
    record_approval_decisions,
)
from app.services.chat_response_cache import (
    acquire_response_lock,
    build_cache_key as build_chat_response_cache_key,
    build_request_cache_key,
    get_cached_response,
    release_response_lock,
    store_response,
    wait_for_cached_response,
)
from app.tools.registry import get_agent_tools
from app.tracing.service import safe_json

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

PDF_TEXT_MAX_CHARS = 120_000
PDF_MAX_PAGES = 100
PDF_MAX_ATTACHMENTS_PER_HISTORY = 3
PDF_TOTAL_MAX_DECODED_BYTES = 8 * 1024 * 1024
PDF_STREAM_MAX_BYTES = 16 * 1024 * 1024
PYPDF_STREAM_LIMIT_NAMES = (
    "MAX_DECLARED_STREAM_LENGTH",
    "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
    "JBIG2_MAX_OUTPUT_LENGTH",
    "LZW_MAX_OUTPUT_LENGTH",
    "RUN_LENGTH_MAX_OUTPUT_LENGTH",
    "ZLIB_MAX_OUTPUT_LENGTH",
    "FLATE_MAX_BUFFER_SIZE",
)

for _pypdf_limit_name in PYPDF_STREAM_LIMIT_NAMES:
    if hasattr(pypdf_filters, _pypdf_limit_name):
        setattr(pypdf_filters, _pypdf_limit_name, PDF_STREAM_MAX_BYTES)


@dataclass
class _PdfNormalizationBudget:
    decoded_bytes: int = 0
    extracted_chars: int = 0


class ChatState(AgentState):
    selected_model: NotRequired[str]
    auth_user_id: NotRequired[str]
    conversation_id: NotRequired[str]


SYSTEM_PROMPT = f"""你是 HY-Agent，一个具备通用对话、知识库检索、代码分析、图片生成、联网搜索、天气查询和股票查询能力的智能助手。

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
    return PersistentHumanInTheLoopMiddleware(
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


def _runtime_run_id(runtime: object) -> str | None:
    execution_info = getattr(runtime, "execution_info", None)
    execution_run_id = getattr(execution_info, "run_id", None)
    if execution_run_id:
        return str(execution_run_id)
    config = getattr(runtime, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    run_id = configurable.get("run_id")
    return str(run_id) if run_id else None


class PersistentHumanInTheLoopMiddleware(HumanInTheLoopMiddleware):
    """Persist HITL requests before interrupt and decisions before execution."""

    def after_model(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, object] | None:
        messages = state["messages"]
        if not messages:
            return None

        last_ai_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, AIMessage)
            ),
            None,
        )
        if not last_ai_message or not last_ai_message.tool_calls:
            return None

        action_requests: list[object] = []
        review_configs: list[object] = []
        interrupted: list[tuple[int, dict[str, object]]] = []
        for index, tool_call in enumerate(last_ai_message.tool_calls):
            config = self.interrupt_on.get(tool_call["name"])
            if config is None or not self._should_interrupt(
                tool_call,
                config,
                state,
                runtime,
            ):
                continue
            action_request, review_config = self._create_action_and_config(
                tool_call,
                config,
                state,
                runtime,
            )
            action_requests.append(action_request)
            review_configs.append(review_config)
            interrupted.append((index, tool_call))

        if not interrupted:
            return None

        state_user_id = state.get("auth_user_id")
        user_id = runtime_user_id(runtime) or (
            str(state_user_id) if state_user_id else None
        )
        thread_id = _runtime_thread_id(runtime)
        runtime_run_id = _runtime_run_id(runtime)
        if user_id:
            db = SessionLocal()
            try:
                ensure_pending_approvals(
                    db,
                    user_id=user_id,
                    thread_id=thread_id,
                    runtime_run_id=runtime_run_id,
                    tool_calls=[tool_call for _, tool_call in interrupted],
                )
            finally:
                db.close()

        decisions = hitl_module.interrupt(
            {
                "action_requests": action_requests,
                "review_configs": review_configs,
            }
        )["decisions"]
        if len(decisions) != len(interrupted):
            raise ValueError(
                "人工审批决定数量与待审批工具调用数量不一致："
                f"{len(decisions)} != {len(interrupted)}"
            )

        revised_tool_calls: list[dict[str, object]] = []
        artificial_tool_messages: list[ToolMessage] = []
        durable_decisions: list[ApprovalDecision] = []
        decision_index = 0
        interrupted_indices = {index for index, _ in interrupted}
        for index, tool_call in enumerate(last_ai_message.tool_calls):
            if index not in interrupted_indices:
                revised_tool_calls.append(tool_call)
                continue

            config = self.interrupt_on[tool_call["name"]]
            decision = decisions[decision_index]
            decision_index += 1
            revised_tool_call, tool_message = self._process_decision(
                decision,
                tool_call,
                config,
            )
            effective_tool_call = revised_tool_call or tool_call
            decision_type = str(decision["type"])
            requested_args = tool_call.get("args")
            effective_args = effective_tool_call.get("args")
            durable_decisions.append(
                ApprovalDecision(
                    tool_call_id=str(tool_call.get("id") or ""),
                    tool_name=str(tool_call.get("name") or "unknown"),
                    requested_input=(
                        requested_args if isinstance(requested_args, Mapping) else {}
                    ),
                    decision_type=decision_type,
                    effective_tool_name=str(
                        effective_tool_call.get("name") or "unknown"
                    ),
                    effective_input=(
                        effective_args if isinstance(effective_args, Mapping) else {}
                    ),
                    decision_payload=decision,
                )
            )
            if revised_tool_call is not None:
                revised_tool_calls.append(revised_tool_call)
            if tool_message is not None:
                artificial_tool_messages.append(tool_message)

        if user_id:
            db = SessionLocal()
            try:
                record_approval_decisions(
                    db,
                    user_id=user_id,
                    thread_id=thread_id,
                    runtime_run_id=runtime_run_id,
                    decisions=durable_decisions,
                )
            finally:
                db.close()

        last_ai_message.tool_calls = revised_tool_calls
        return {"messages": [last_ai_message, *artificial_tool_messages]}

    async def aafter_model(
        self,
        state: AgentState,
        runtime: Runtime,
    ) -> dict[str, object] | None:
        return self.after_model(state, runtime)


def _message_preview(messages: Sequence[BaseMessage]) -> list[JsonObject]:
    return [
        {
            "type": getattr(message, "type", message.__class__.__name__),
            "content": safe_json(getattr(message, "content", ""), max_length=2_000),
        }
        for message in messages[-8:]
    ]


def _normalize_frontend_multimodal_block(
    block: Mapping[str, object],
) -> dict[str, object]:
    normalized = dict(block)
    block_type = normalized.get("type")
    mime_type = normalized.get("mime_type") or normalized.get("mimeType")
    data = normalized.get("data")

    if (
        block_type in {"image", "file"}
        and isinstance(mime_type, str)
        and isinstance(data, str)
        and "source_type" not in normalized
        and "base64" not in normalized
    ):
        normalized["source_type"] = "base64"
        normalized["mime_type"] = mime_type

        metadata = normalized.get("metadata")
        filename = None
        if isinstance(metadata, Mapping):
            candidate = metadata.get("filename") or metadata.get("name")
            if isinstance(candidate, str) and candidate.strip():
                filename = candidate
        if block_type == "file" and filename and "filename" not in normalized:
            normalized["filename"] = filename

    return normalized


def _is_image_content_block(block: Mapping[str, object]) -> bool:
    def is_image_mime(value: object) -> bool:
        return isinstance(value, str) and value.strip().lower().startswith("image/")

    def is_image_data_url(value: object) -> bool:
        return isinstance(value, str) and value.strip().lower().startswith(
            "data:image/"
        )

    block_type = block.get("type")
    if block_type in {"image", "image_url", "input_image"}:
        return True
    mime_type = (
        block.get("mime_type")
        or block.get("mimeType")
        or block.get("media_type")
        or block.get("mediaType")
        or block.get("content_type")
        or block.get("contentType")
    )
    source = block.get("source")
    if not mime_type and isinstance(source, Mapping):
        mime_type = (
            source.get("media_type")
            or source.get("mediaType")
            or source.get("mime_type")
            or source.get("mimeType")
        )
    nested_file = block.get("file")
    if block_type == "file" and isinstance(nested_file, Mapping):
        nested_mime_type = (
            nested_file.get("media_type")
            or nested_file.get("mediaType")
            or nested_file.get("mime_type")
            or nested_file.get("mimeType")
            or nested_file.get("content_type")
            or nested_file.get("contentType")
        )
        nested_data = nested_file.get("file_data") or nested_file.get("url")
        if is_image_mime(nested_mime_type) or is_image_data_url(nested_data):
            return True
    direct_url = block.get("url")
    if block_type == "file" and is_image_data_url(direct_url):
        return True
    return block_type in {"file", "media"} and is_image_mime(mime_type)


def _unsupported_image_text_block(
    block: Mapping[str, object],
) -> dict[str, str]:
    metadata = block.get("metadata")
    filename = block.get("filename") or block.get("name")
    nested_file = block.get("file")
    if not filename and isinstance(nested_file, Mapping):
        filename = nested_file.get("filename") or nested_file.get("name")
    if not filename and isinstance(metadata, Mapping):
        filename = metadata.get("filename") or metadata.get("name")
    label = (
        str(filename).strip()
        if isinstance(filename, str) and filename.strip()
        else "图片附件"
    )
    return {
        "type": "text",
        "text": (
            f"[用户上传了图片：{label}。当前所选模型不支持读取图片内容。"
            "请不要推测图片内容，并提示用户改用文字描述。]"
        ),
    }


def _attachment_filename(block: Mapping[str, object]) -> str:
    candidate = block.get("filename")
    metadata = block.get("metadata")
    if not candidate and isinstance(metadata, Mapping):
        candidate = metadata.get("filename") or metadata.get("name")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return "document.pdf"


def _is_pdf_file_block(block: Mapping[str, object]) -> bool:
    block_type = block.get("type")
    mime_type = block.get("mime_type") or block.get("mimeType")
    return block_type == "file" and mime_type == "application/pdf"


def _base64_decoded_size(data: str) -> int:
    """Return the decoded size for valid Base64, or a safe upper bound otherwise."""

    groups, remainder = divmod(len(data), 4)
    if remainder:
        return (groups + 1) * 3
    padding = min(len(data) - len(data.rstrip("=")), 2)
    return groups * 3 - padding


def _upload_limit_label(limit_bytes: int) -> str:
    if limit_bytes < 1024:
        return f"{limit_bytes} 字节"
    limit_mb = limit_bytes / (1024 * 1024)
    return f"{limit_mb:g} 兆字节"


def _pdf_history_byte_limit() -> int:
    return min(settings.max_upload_bytes, PDF_TOTAL_MAX_DECODED_BYTES)


def _validate_pdf_history_blocks(blocks: Sequence[Mapping[str, object]]) -> None:
    pdf_blocks = [block for block in blocks if _is_pdf_file_block(block)]
    if len(pdf_blocks) > PDF_MAX_ATTACHMENTS_PER_HISTORY:
        raise ValueError(
            "整段消息历史最多支持 "
            f"{PDF_MAX_ATTACHMENTS_PER_HISTORY} 个 PDF 附件，"
            f"当前包含 {len(pdf_blocks)} 个"
        )

    byte_limit = _pdf_history_byte_limit()
    estimated_total = 0
    for block in pdf_blocks:
        data = block.get("data") or block.get("base64")
        if not isinstance(data, str):
            continue
        estimated_size = _base64_decoded_size(data)
        if estimated_size > byte_limit:
            filename = _attachment_filename(block)
            limit = _upload_limit_label(byte_limit)
            raise ValueError(f"PDF 附件 {filename} 超过 {limit}限制")
        estimated_total += estimated_size

    if estimated_total > byte_limit:
        limit = _upload_limit_label(byte_limit)
        raise ValueError(f"整段消息历史中的 PDF 附件解码后总大小超过 {limit}限制")


def _pdf_file_block_to_text(
    block: Mapping[str, object],
    *,
    budget: _PdfNormalizationBudget | None = None,
) -> dict[str, str] | None:
    data = block.get("data") or block.get("base64")
    if not _is_pdf_file_block(block) or not isinstance(data, str):
        return None

    if budget is None:
        budget = _PdfNormalizationBudget()
    filename = _attachment_filename(block)
    try:
        pdf_bytes = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"PDF 附件 {filename} 的 Base64 数据无效") from exc

    byte_limit = _pdf_history_byte_limit()
    if len(pdf_bytes) > byte_limit:
        limit = _upload_limit_label(byte_limit)
        raise ValueError(f"PDF 附件 {filename} 超过 {limit}限制")
    budget.decoded_bytes += len(pdf_bytes)
    if budget.decoded_bytes > byte_limit:
        limit = _upload_limit_label(byte_limit)
        raise ValueError(f"整段消息历史中的 PDF 附件解码后总大小超过 {limit}限制")

    if budget.extracted_chars >= PDF_TEXT_MAX_CHARS:
        return {
            "type": "text",
            "text": (
                f"已上传 PDF 文件：{filename}\n\n"
                "整段消息历史的 PDF 文本提取总量已达到 "
                f"{PDF_TEXT_MAX_CHARS} 个字符限制，未继续解析此附件。"
            ),
        }

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        extracted_prefix = (
            f"已上传 PDF 文件：{filename}\n\n以下是从 PDF 中提取的文本：\n\n"
        )
        page_texts: list[str] = []
        text_truncated = False
        pages_truncated = False
        for page_number, page in enumerate(reader.pages, start=1):
            if page_number > PDF_MAX_PAGES:
                pages_truncated = True
                break
            text = (page.extract_text() or "").strip()
            if not text:
                continue

            section = f"[第 {page_number} 页]\n{text}"
            separator_size = 2 if page_texts else 0
            remaining_chars = (
                PDF_TEXT_MAX_CHARS - budget.extracted_chars - separator_size
            )
            if remaining_chars <= 0:
                text_truncated = True
                break
            if len(section) > remaining_chars:
                page_texts.append(section[:remaining_chars])
                budget.extracted_chars = PDF_TEXT_MAX_CHARS
                text_truncated = True
                break

            page_texts.append(section)
            budget.extracted_chars += separator_size + len(section)
    except Exception as exc:
        raise ValueError(f"PDF 附件 {filename} 无法解析：{exc}") from exc

    if not page_texts:
        extracted = (
            f"已上传 PDF 文件：{filename}\n\n"
            "该 PDF 没有可提取的文字，可能是扫描件或纯图片文档。"
        )
    else:
        extracted = extracted_prefix + "\n\n".join(page_texts)

    if text_truncated:
        extracted += (
            f"\n\n[整段消息历史的 PDF 内容过长，已截取前 {PDF_TEXT_MAX_CHARS} 个字符。]"
        )
    elif pages_truncated:
        extracted += f"\n\n[PDF 页数过多，仅提取前 {PDF_MAX_PAGES} 页。]"
    return {"type": "text", "text": extracted}


def _normalize_content_block(
    block: Mapping[str, object],
    *,
    budget: _PdfNormalizationBudget | None = None,
    supports_images: bool,
) -> dict[str, object]:
    pdf_text_block = _pdf_file_block_to_text(
        block,
        budget=budget,
    )
    if pdf_text_block is not None:
        return pdf_text_block
    if not supports_images and _is_image_content_block(block):
        return _unsupported_image_text_block(block)
    return _normalize_frontend_multimodal_block(block)


def _multimodal_content_blocks(content: object) -> list[Mapping[str, object]]:
    if isinstance(content, Mapping):
        return [content]
    if isinstance(content, Sequence) and not isinstance(
        content, str | bytes | bytearray
    ):
        return [block for block in content if isinstance(block, Mapping)]
    return []


def _normalize_multimodal_content(
    content: object,
    *,
    budget: _PdfNormalizationBudget | None = None,
    supports_images: bool,
) -> object:
    if budget is None:
        budget = _PdfNormalizationBudget()
        _validate_pdf_history_blocks(_multimodal_content_blocks(content))
    if isinstance(content, Mapping):
        return _normalize_content_block(
            content,
            budget=budget,
            supports_images=supports_images,
        )
    if isinstance(content, Sequence) and not isinstance(
        content, str | bytes | bytearray
    ):
        return [
            _normalize_content_block(
                block,
                budget=budget,
                supports_images=supports_images,
            )
            if isinstance(block, Mapping)
            else block
            for block in content
        ]
    return content


def _normalize_multimodal_messages(
    messages: Sequence[BaseMessage | Mapping[str, object]],
    *,
    supports_images: bool = False,
) -> list[BaseMessage | dict[str, object]]:
    message_list = list(messages)
    pdf_blocks: list[Mapping[str, object]] = []
    for message in message_list:
        content = (
            message.get("content", "")
            if isinstance(message, Mapping)
            else getattr(message, "content", "")
        )
        pdf_blocks.extend(_multimodal_content_blocks(content))
    _validate_pdf_history_blocks(pdf_blocks)

    budget = _PdfNormalizationBudget()
    normalized_messages: list[BaseMessage | dict[str, object]] = []
    for message in message_list:
        if isinstance(message, Mapping):
            normalized = dict(message)
            normalized["content"] = _normalize_multimodal_content(
                normalized.get("content", ""),
                budget=budget,
                supports_images=supports_images,
            )
            normalized_messages.append(normalized)
        else:
            normalized_messages.append(
                message.model_copy(
                    update={
                        "content": _normalize_multimodal_content(
                            getattr(message, "content", ""),
                            budget=budget,
                            supports_images=supports_images,
                        )
                    }
                )
            )
    return normalized_messages


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


def _existing_invocation_message(
    request: ToolCallRequest,
    claim: ToolInvocationClaim,
) -> ToolMessage:
    tool_name = str(request.tool_call.get("name") or claim.tool_name)
    tool_call_id = str(request.tool_call.get("id") or claim.tool_call_id)
    if claim.status in {
        ToolInvocationStatus.SUCCEEDED,
        ToolInvocationStatus.FAILED,
    }:
        content: object = claim.output.get("content")
        if content is None:
            content = {
                "error": claim.error_message or "工具调用已结束，但没有可复用的输出"
            }
        if not isinstance(content, str | list):
            content = json.dumps(content, ensure_ascii=False)
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status=(
                "error" if claim.status == ToolInvocationStatus.FAILED else "success"
            ),
        )

    state_messages = {
        ToolInvocationStatus.PENDING_APPROVAL: "工具调用仍在等待人工审批",
        ToolInvocationStatus.REJECTED: "工具调用已被用户拒绝",
        ToolInvocationStatus.RUNNING: "相同工具调用已在执行中，已阻止重复执行",
    }
    message = state_messages.get(
        claim.status,
        f"工具调用当前状态为 {claim.status.value}，不能重复执行",
    )
    return _tool_failure_message(request, message)


def _policy_violation_response(message: str) -> ModelResponse:
    if message.startswith("请求过于频繁"):
        content = f"发送太频繁了。\n\n{message}。请稍等一分钟后再继续发送。"
    elif "本月标记配额已用尽" in message:
        content = append_admin_contact(
            "本月额度已用尽。\n\n当前账号的本月标记配额已经用完，请联系管理员调整额度后再继续使用。"
        )
    elif message.startswith("当前账号无权使用模型"):
        content = append_admin_contact(
            f"当前账号没有这个模型的使用权限。\n\n{message}。请切换其他模型，或联系管理员开通权限。"
        )
    else:
        content = append_admin_contact(f"当前请求被权限策略拦截。\n\n原因：{message}")

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


def _append_memory_to_request(
    request: ModelRequest,
    db: Session,
    user_id: str,
    thread_id: str | None,
) -> ModelRequest:
    try:
        deleted_memory_keys = remember_from_messages(
            db,
            user_id,
            request.messages,
            source_thread_id=thread_id,
        )
        memory_prompt = build_memory_system_prompt(
            db,
            user_id,
            backfill_from_traces="profile.name" not in deleted_memory_keys,
        )
    except Exception:
        logger.warning(
            "Long-term memory unavailable user_id=%s", user_id, exc_info=True
        )
        return request
    if not memory_prompt:
        return request

    if request.system_message:
        existing = request.system_message.content
        existing_text = existing if isinstance(existing, str) else str(existing)
        return request.override(
            system_message=SystemMessage(content=f"{existing_text}\n\n{memory_prompt}")
        )

    return request.override(
        messages=[SystemMessage(content=memory_prompt), *request.messages]
    )


def _asks_user_name(content: object) -> bool:
    text = _content_title(content).lower()
    if not text:
        return False
    return any(
        phrase in text
        for phrase in (
            "我叫什么",
            "我的名字",
            "我是谁",
            "what is my name",
            "who am i",
        )
    )


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
    ) -> tuple[ModelRequest, Session, str | None, TraceSpan | None, str, str | None]:
        selected = resolve_model(request.state.get("selected_model"))
        user_id = runtime_user_id(request.runtime) or request.state.get("auth_user_id")
        db = SessionLocal()
        try:
            original_messages = request.messages
            thread_id = _runtime_thread_id(request.runtime)
            conversation = None
            if user_id:
                authorize_model_access(db, user_id, selected)
                conversation = _ensure_conversation(
                    db,
                    user_id,
                    thread_id,
                    request.state,
                    selected,
                )
                request = _append_memory_to_request(request, db, user_id, thread_id)
            request = request.override(
                messages=_normalize_multimodal_messages(
                    request.messages,
                    supports_images=model_supports_images(selected),
                )
            )
            cache_key = build_request_cache_key(request, user_id, selected)
            trace = None
            if user_id:
                trace = TraceSpan(
                    user_id=user_id,
                    conversation_id=(
                        conversation.id
                        if conversation
                        else request.state.get("conversation_id")
                    ),
                    thread_id=thread_id,
                    run_id=str(uuid.uuid4()),
                    name=f"model:{selected}",
                    span_type="model",
                    model_name=selected,
                    input={"messages": _message_preview(original_messages)},
                )
                db.add(trace)
                db.commit()
                db.refresh(trace)
            logger.info(
                "Model call started user_id=%s thread_id=%s model=%s",
                user_id,
                thread_id,
                selected,
            )
            return request, db, user_id, trace, selected, cache_key
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
        *,
        cache_hit: bool = False,
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
            trace.output = {
                "messages": _message_preview(response.result),
                "cache_hit": cache_hit,
            }
            trace.ended_at = datetime.utcnow()
            db.commit()
        logger.info(
            "Model call completed user_id=%s model=%s latency_ms=%s tokens=%s cache_hit=%s",
            user_id,
            trace.model_name if trace else None,
            latency_ms,
            total,
            cache_hit,
        )

    @staticmethod
    def _fail_trace(
        db: Session,
        trace: TraceSpan | None,
        exc: Exception,
        started: float,
        claim: ToolInvocationClaim | None = None,
    ) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        if claim and claim.should_execute:
            fail_tool_invocation(db, claim=claim, error_message=str(exc))
        if trace:
            trace.status = "error"
            trace.error_message = str(exc)
            trace.latency_ms = latency_ms
            trace.ended_at = datetime.utcnow()
        if trace or claim:
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
            prepared, db, user_id, trace, selected, cache_key = (
                self._prepare_model_call(request)
            )
        except PolicyViolation as exc:
            logger.warning("Model call blocked by policy: %s", exc)
            return _policy_violation_response(str(exc))
        cache_lock = None
        try:
            if cached := get_cached_response(cache_key):
                self._finish_model_call(
                    db,
                    user_id,
                    trace,
                    cached,
                    started,
                    cache_hit=True,
                )
                return cached

            cache_lock = acquire_response_lock(cache_key)
            if cache_key and not cache_lock:
                if cached := wait_for_cached_response(cache_key):
                    self._finish_model_call(
                        db,
                        user_id,
                        trace,
                        cached,
                        started,
                        cache_hit=True,
                    )
                    return cached
            elif cache_lock and (cached := get_cached_response(cache_key)):
                self._finish_model_call(
                    db,
                    user_id,
                    trace,
                    cached,
                    started,
                    cache_hit=True,
                )
                return cached

            if user_id:
                enforce_model(db, user_id, selected)
            overridden = prepared.override(
                model=get_chat_model(selected, streaming=True)
            )
            response = handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            store_response(cache_key, response)
            return response
        except PolicyViolation as exc:
            self._fail_trace(db, trace, exc, started)
            return _policy_violation_response(str(exc))
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            release_response_lock(cache_lock)
            db.close()

    async def awrap_model_call(self, request: ModelRequest, handler):
        started = time.perf_counter()
        try:
            prepared, db, user_id, trace, selected, cache_key = (
                self._prepare_model_call(request)
            )
        except PolicyViolation as exc:
            logger.warning("Model call blocked by policy: %s", exc)
            return _policy_violation_response(str(exc))
        cache_lock = None
        try:
            if cached := get_cached_response(cache_key):
                self._finish_model_call(
                    db,
                    user_id,
                    trace,
                    cached,
                    started,
                    cache_hit=True,
                )
                return cached

            cache_lock = acquire_response_lock(cache_key)
            if cache_key and not cache_lock:
                cached = await asyncio.to_thread(wait_for_cached_response, cache_key)
                if cached:
                    self._finish_model_call(
                        db,
                        user_id,
                        trace,
                        cached,
                        started,
                        cache_hit=True,
                    )
                    return cached
            elif cache_lock and (cached := get_cached_response(cache_key)):
                self._finish_model_call(
                    db,
                    user_id,
                    trace,
                    cached,
                    started,
                    cache_hit=True,
                )
                return cached

            if user_id:
                enforce_model(db, user_id, selected)
            overridden = prepared.override(
                model=get_chat_model(selected, streaming=True)
            )
            response = await handler(overridden)
            self._finish_model_call(db, user_id, trace, response, started)
            store_response(cache_key, response)
            return response
        except PolicyViolation as exc:
            self._fail_trace(db, trace, exc, started)
            return _policy_violation_response(str(exc))
        except Exception as exc:
            self._fail_trace(db, trace, exc, started)
            raise
        finally:
            release_response_lock(cache_lock)
            db.close()

    @staticmethod
    def _prepare_tool_call(request: ToolCallRequest):
        state_user_id = (
            request.state.get("auth_user_id")
            if isinstance(request.state, Mapping)
            else None
        )
        resolved_user_id = runtime_user_id(request.runtime) or state_user_id
        user_id = str(resolved_user_id) if resolved_user_id else None
        name = str(request.tool_call.get("name") or "unknown")
        db = SessionLocal()
        try:
            claim = None
            if user_id:
                enforce_tool(db, user_id, name)
            trace = None
            if user_id:
                thread_id = _runtime_thread_id(request.runtime)
                args = request.tool_call.get("args")
                claim = claim_tool_invocation(
                    db,
                    user_id=user_id,
                    thread_id=thread_id,
                    runtime_run_id=_runtime_run_id(request.runtime),
                    tool_call_id=str(request.tool_call.get("id") or ""),
                    tool_name=name,
                    requested_input=args if isinstance(args, Mapping) else {},
                )
                trace = TraceSpan(
                    user_id=user_id,
                    conversation_id=claim.conversation_id,
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
            return db, trace, claim
        except Exception:
            db.close()
            raise

    @staticmethod
    def _finish_tool_call(
        db,
        trace,
        result,
        started: float,
        claim: ToolInvocationClaim | None = None,
    ):
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_message = _tool_error_message(result)
        if claim and claim.should_execute:
            complete_tool_invocation(
                db,
                claim=claim,
                result=result,
                error_message=error_message,
            )
        if trace:
            trace.status = "error" if error_message else "success"
            trace.output = {"result": safe_json(getattr(result, "content", result))}
            trace.error_message = error_message
            trace.latency_ms = latency_ms
            trace.ended_at = datetime.utcnow()
        if trace or claim:
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
        claim = None
        try:
            db, trace, claim = self._prepare_tool_call(request)
            if claim and not claim.should_execute:
                result = _existing_invocation_message(request, claim)
                self._finish_tool_call(db, trace, result, started)
                return result
            result = handler(request)
            self._finish_tool_call(db, trace, result, started, claim)
            return result
        except (
            PolicyViolation,
            ToolInvocationConflict,
            ToolInvocationOwnershipError,
        ) as exc:
            if db:
                self._fail_trace(db, trace, exc, started, claim)
            return _tool_failure_message(request, str(exc))
        except Exception as exc:
            if db:
                self._fail_trace(db, trace, exc, started, claim)
            raise
        finally:
            if db:
                db.close()

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = time.perf_counter()
        db = None
        trace = None
        claim = None
        try:
            db, trace, claim = self._prepare_tool_call(request)
            if claim and not claim.should_execute:
                result = _existing_invocation_message(request, claim)
                self._finish_tool_call(db, trace, result, started)
                return result
            result = await handler(request)
            self._finish_tool_call(db, trace, result, started, claim)
            return result
        except (
            PolicyViolation,
            ToolInvocationConflict,
            ToolInvocationOwnershipError,
        ) as exc:
            if db:
                self._fail_trace(db, trace, exc, started, claim)
            return _tool_failure_message(request, str(exc))
        except Exception as exc:
            if db:
                self._fail_trace(db, trace, exc, started, claim)
            raise
        finally:
            if db:
                db.close()


def _build_mock_graph():
    """Keep all transport and model-selection paths testable without an API key."""

    def mock_chat(state: ChatState, runtime: Runtime) -> dict[str, object]:
        last_message = state["messages"][-1] if state["messages"] else None
        content = message_to_text(last_message) if last_message else ""
        selected = state.get("selected_model") or settings.zhipu_chat_model
        server_user_id = runtime_user_id(runtime)
        user_id = server_user_id or state.get("auth_user_id")
        memory_values: dict[str, str] = {}
        thread_id = _runtime_thread_id(runtime)
        cache_key = None
        cache_hit = False
        response_text = ""
        cache_lock = None
        if user_id:
            db = SessionLocal()
            try:
                authorize_model_access(db, user_id, selected)
                try:
                    deleted_memory_keys = remember_from_messages(
                        db,
                        user_id,
                        state["messages"],
                        source_thread_id=thread_id,
                    )
                    memory_values = user_memory_map(
                        db,
                        user_id,
                        backfill_from_traces="profile.name" not in deleted_memory_keys,
                    )
                except Exception:
                    logger.warning(
                        "Long-term memory unavailable user_id=%s",
                        user_id,
                        exc_info=True,
                    )
                cache_key = build_chat_response_cache_key(
                    user_id,
                    selected,
                    state["messages"],
                    extra_context={"memory": memory_values},
                )
                cached_response = get_cached_response(cache_key)
                if cached_response:
                    response_text = str(cached_response.result[0].content)
                    cache_hit = True
                else:
                    cache_lock = acquire_response_lock(cache_key)
                    if not cache_lock and (
                        cached_response := wait_for_cached_response(cache_key)
                    ):
                        response_text = str(cached_response.result[0].content)
                        cache_hit = True
                    else:
                        enforce_model(db, user_id, selected)
            finally:
                db.close()

        if cache_hit:
            pass
        elif memory_values.get("profile.name") and _asks_user_name(content):
            response_text = (
                "【模拟模型输出】\n\n"
                f"你叫{memory_values['profile.name']}。这是根据同一账号的长期记忆回答的。"
            )
        else:
            memory_text = (
                f"\n\n长期记忆：用户姓名是 {memory_values['profile.name']}。"
                if memory_values.get("profile.name")
                else ""
            )
            response_text = (
                "【模拟模型输出】\n\n"
                f"当前模型：`{selected}`。HY-Agent 的聊天链路已连接成功。配置真实模型密钥后即可"
                "使用真实模型、工具调用与知识库检索回答。"
                f"{memory_text}\n\n"
                f"你刚才发送的是：{content}"
            )
        message = AIMessage(
            content=response_text,
            response_metadata={"cache_hit": True} if cache_hit else {},
        )
        if user_id:
            db = SessionLocal()
            try:
                conversation = _ensure_conversation(
                    db,
                    user_id,
                    thread_id,
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
                        thread_id=thread_id,
                        run_id=str(uuid.uuid4()),
                        name=f"model:{selected}:mock",
                        span_type="model",
                        status="success",
                        model_name=selected,
                        input={"messages": _message_preview(state["messages"])},
                        output={
                            "messages": _message_preview([message]),
                            "cache_hit": cache_hit,
                        },
                        latency_ms=0,
                        ended_at=datetime.utcnow(),
                    )
                )
                db.commit()
            finally:
                db.close()
        if not cache_hit:
            store_response(cache_key, ModelResponse(result=[message]))
        release_response_lock(cache_lock)
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
