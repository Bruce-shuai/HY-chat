import base64
from io import BytesIO
import logging
import time
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime, ServerInfo
from pypdf import PdfWriter
from redis.exceptions import RedisError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.chat as chat_module
import app.cache.service as cache_service_module
import app.db.session as db_session_module
import app.entrypoint as entrypoint_module
from app.agents.chat import (
    HITL_TOOL_CONFIG,
    PolicyTraceMiddleware,
    _build_mock_graph,
    _conversation_title_from_state,
    _normalize_multimodal_messages,
    build_hitl_middleware,
)
from app.cache.service import CacheService
from app.core.logging import configure_logging
from app.db.models import Conversation, TraceSpan, UserMemory
from app.db.session import Base
import app.models.catalog as catalog_module
import app.services.chat_response_cache as chat_cache_module
from app.models.catalog import resolve_model
from app.rag.embeddings import EmbeddingService
from app.storage.service import storage
from app.tools import external as external_tools
from app.tools import image_tools
from app.tools.registry import tool_manifest


def test_logging_configuration_sets_root_level():
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    configure_logging("INFO")


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def scan_iter(self, match, count=200):
        prefix = match.removesuffix("*")
        return [key for key in self.values if key.startswith(prefix)]

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def ping(self):
        return True

    def eval(self, _script, _numkeys, key, token):
        if self.values.get(key) == token:
            self.delete(key)
            return 1
        return 0


def test_model_catalog_and_tool_registry(monkeypatch):
    monkeypatch.setattr(catalog_module.settings, "zhipu_chat_model", "glm-5.2")
    monkeypatch.setattr(
        catalog_module.settings,
        "zhipu_chat_models",
        "glm-5.2,glm-5.1,glm-5-turbo",
    )

    models = catalog_module.list_models()
    assert models
    assert catalog_module.resolve_model(None) in {model.id for model in models}
    assert [model.id for model in models] == [
        "glm-5.2",
        "glm-5.1",
        "glm-5-turbo",
    ]
    assert models[0].tier == "旗舰"
    assert "推荐" in models[0].label
    assert models[1].tier == "高性能"
    assert models[2].tier == "工具增强"
    assert all(model.label != model.id for model in models)
    assert all(not model.supports_images for model in models)
    assert catalog_module.model_supports_images("glm-5v-turbo")
    assert catalog_module.normalize_model_allowlist(
        ["glm-5.2", "glm-4-flash", "glm-4-plus", "glm-4.5"]
    ) == ["glm-5.2", "glm-5.1", "glm-5-turbo"]
    assert catalog_module.normalize_model_allowlist(["glm-5.1"]) == ["glm-5.1"]
    assert {tool["name"] for tool in tool_manifest()} >= {
        "search_knowledge_base",
        "generate_image",
        "web_search",
        "get_weather",
        "get_stock_quote",
    }


def test_chat_model_has_bounded_provider_requests(monkeypatch):
    monkeypatch.setattr(catalog_module.settings, "zhipu_api_key", "test-api-key")
    monkeypatch.setattr(catalog_module.settings, "zhipu_request_timeout", 120.0)
    monkeypatch.setattr(catalog_module.settings, "zhipu_max_retries", 0)
    catalog_module.get_chat_model.cache_clear()

    try:
        model = catalog_module.get_chat_model("glm-5.2")

        assert model.request_timeout == 120.0
        assert model.max_retries == 0
    finally:
        catalog_module.get_chat_model.cache_clear()


def test_postgres_engine_bounds_blocking_database_io(monkeypatch):
    monkeypatch.setattr(
        db_session_module.settings,
        "database_connect_timeout_seconds",
        10,
    )
    monkeypatch.setattr(
        db_session_module.settings,
        "database_pool_timeout_seconds",
        10,
    )
    monkeypatch.setattr(
        db_session_module.settings,
        "database_statement_timeout_ms",
        120_000,
    )
    monkeypatch.setattr(
        db_session_module.settings,
        "database_tcp_user_timeout_ms",
        60_000,
    )

    options = db_session_module._database_engine_options(
        "postgresql+psycopg://user:password@postgres/database"
    )

    assert options == {
        "pool_pre_ping": True,
        "pool_timeout": 10,
        "connect_args": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=120000",
            "tcp_user_timeout": 60_000,
        },
    }
    assert db_session_module._database_engine_options("sqlite://") == {
        "pool_pre_ping": True
    }


def test_agent_entrypoint_configures_worker_concurrency(monkeypatch):
    runtime_settings = SimpleNamespace(app_env="local", agent_jobs_per_worker=3)
    exec_call = {}
    monkeypatch.setattr(entrypoint_module, "get_settings", lambda: runtime_settings)
    monkeypatch.setenv("SERVICE_ROLE", "agent")
    monkeypatch.setattr(
        entrypoint_module.os,
        "execvp",
        lambda executable, arguments: exec_call.update(
            executable=executable,
            arguments=arguments,
        ),
    )

    entrypoint_module.main()

    assert exec_call["executable"] == "langgraph"
    arguments = exec_call["arguments"]
    jobs_option = arguments.index("--n-jobs-per-worker")
    assert arguments[jobs_option + 1] == "3"


def test_hitl_tools_are_registered_and_require_review():
    registered = {tool["name"] for tool in tool_manifest()}
    assert set(HITL_TOOL_CONFIG) <= registered
    assert all(
        config["allowed_decisions"] == ["approve", "edit", "reject"]
        for config in HITL_TOOL_CONFIG.values()
    )


def test_hitl_interrupts_server_runs_and_skips_direct_runs(monkeypatch):
    captured = []

    def approve(interrupt_value):
        captured.append(interrupt_value)
        return {"decisions": [{"type": "approve"}]}

    monkeypatch.setattr(
        "langchain.agents.middleware.human_in_the_loop.interrupt", approve
    )
    middleware = build_hitl_middleware()
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "LangGraph HITL"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }

    assert middleware.after_model(state, Runtime()) is None
    assert captured == []

    result = middleware.after_model(
        state,
        Runtime(server_info=ServerInfo(assistant_id="assistant-1", graph_id="hy-chat")),
    )
    assert captured[0]["action_requests"][0]["name"] == "web_search"
    assert captured[0]["review_configs"][0]["allowed_decisions"] == [
        "approve",
        "edit",
        "reject",
    ]
    assert result is not None
    assert result["messages"][0].tool_calls[0]["name"] == "web_search"


def test_hash_embeddings_are_deterministic():
    service = EmbeddingService()
    first = service._hash_embedding("HY-Agent RAG")
    second = service._hash_embedding("HY-Agent RAG")
    assert first == second
    assert len(first) == service.dimensions


def test_json_cache_round_trip_and_invalidation():
    cache = CacheService(FakeRedis())
    assert cache.set_json("rag:query:one", {"answer": 42}, ttl=60)
    assert cache.get_json("rag:query:one") == {"answer": 42}
    assert cache.delete_pattern("rag:query:*") == 1
    assert cache.get_json("rag:query:one") is None


def test_cache_ttl_jitter_and_negative_cache(monkeypatch):
    fake_redis = FakeRedis()
    cache = CacheService(fake_redis)
    monkeypatch.setattr(cache_service_module.settings, "cache_ttl_jitter_ratio", 0.2)

    assert cache.set_json("regular", {"answer": 42}, ttl=100)
    assert 80 <= fake_redis.ttls["regular"] <= 120

    assert cache.set_negative_json("missing", [], ttl=30)
    lookup = cache.get_json_lookup("missing")
    assert lookup.hit
    assert lookup.is_negative
    assert lookup.value == []
    assert cache.get_json("missing") == []


def test_cache_get_or_set_uses_negative_cache_and_lock(monkeypatch):
    fake_redis = FakeRedis()
    cache = CacheService(fake_redis)
    calls = 0
    monkeypatch.setattr(cache_service_module.settings, "cache_ttl_jitter_ratio", 0)

    def produce_empty():
        nonlocal calls
        calls += 1
        return []

    first = cache.get_or_set_json(
        "empty-query",
        produce_empty,
        ttl=300,
        negative_ttl=15,
        should_cache_negative=lambda value: value == [],
    )
    second = cache.get_or_set_json(
        "empty-query",
        lambda: pytest.fail("negative cache should satisfy repeated lookups"),
        ttl=300,
        negative_ttl=15,
        should_cache_negative=lambda value: value == [],
    )

    assert first.created
    assert first.is_negative
    assert first.value == []
    assert second.hit
    assert not second.created
    assert second.is_negative
    assert second.value == []
    assert fake_redis.ttls["empty-query"] == 15
    assert calls == 1


def test_cache_get_or_set_degrades_without_waiting_on_redis_error(monkeypatch):
    class FailingRedis(FakeRedis):
        def get(self, key):
            raise RedisError("redis unavailable")

        def set(self, key, value, nx=False, ex=None):
            raise RedisError("redis unavailable")

        def setex(self, key, ttl, value):
            raise RedisError("redis unavailable")

    cache = CacheService(FailingRedis())
    calls = 0
    monkeypatch.setattr(cache_service_module.settings, "cache_lock_wait_seconds", 2)
    started = time.perf_counter()

    def produce_value():
        nonlocal calls
        calls += 1
        return {"ok": True}

    lookup = cache.get_or_set_json("unstable", produce_value)

    assert lookup.created
    assert lookup.value == {"ok": True}
    assert calls == 1
    assert time.perf_counter() - started < 0.5


def test_policy_middleware_returns_cached_plain_model_response(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    fake_cache = CacheService(FakeRedis())
    model = resolve_model(None)
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="hello")],
        system_message=SystemMessage(content="system"),
        state={"selected_model": model, "auth_user_id": "user-1"},
        runtime=SimpleNamespace(config={"configurable": {"thread_id": "thread-1"}}),
    )
    middleware = PolicyTraceMiddleware()
    calls = 0

    def first_handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(content="cached answer")])

    def unexpected_handler(_request):
        raise AssertionError("cached response should skip model handler")

    monkeypatch.setattr(chat_module, "SessionLocal", testing_session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", lambda *_args: None)
    monkeypatch.setattr(chat_module, "get_chat_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat_cache_module, "cache", fake_cache)

    try:
        first = middleware.wrap_model_call(request, first_handler)
        second = middleware.wrap_model_call(request, unexpected_handler)

        assert first.result[0].content == "cached answer"
        assert second.result[0].content == "cached answer"
        assert second.result[0].response_metadata["cache_hit"] is True
        assert calls == 1
        with testing_session() as db:
            traces = db.scalars(select(TraceSpan).order_by(TraceSpan.started_at)).all()
            assert len(traces) == 2
            assert traces[-1].output["cache_hit"] is True
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_policy_middleware_does_not_cache_tool_call_response(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    fake_cache = CacheService(FakeRedis())
    model = resolve_model(None)
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="search latest news")],
        system_message=SystemMessage(content="system"),
        state={"selected_model": model, "auth_user_id": "user-1"},
        runtime=SimpleNamespace(config={"configurable": {"thread_id": "thread-1"}}),
    )
    middleware = PolicyTraceMiddleware()
    calls = 0

    def tool_call_handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(
            result=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "web_search",
                            "args": {"query": "latest news"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        )

    def final_handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(content="fresh answer")])

    monkeypatch.setattr(chat_module, "SessionLocal", testing_session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", lambda *_args: None)
    monkeypatch.setattr(chat_module, "get_chat_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat_cache_module, "cache", fake_cache)

    try:
        first = middleware.wrap_model_call(request, tool_call_handler)
        second = middleware.wrap_model_call(request, final_handler)

        assert first.result[0].tool_calls
        assert second.result[0].content == "fresh answer"
        assert calls == 2
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_chat_response_cache_payload_hashes_large_binary_blocks():
    payload = chat_cache_module._message_payload(
        HumanMessage(
            content=[
                {"type": "text", "text": "识别图片里的文字"},
                {
                    "type": "image",
                    "mimeType": "image/png",
                    "data": "a" * 2048,
                },
            ]
        )
    )

    image_block = payload["content"][1]
    assert image_block["data"][chat_cache_module.CACHE_HASHED_STRING_MARKER] is True
    assert image_block["data"]["chars"] == 2048
    assert image_block["data"]["sha256"]


def test_chat_response_cache_key_uses_full_hash_for_large_strings():
    prefix = "a" * 2048
    first_key = chat_cache_module.build_cache_key(
        "user-1",
        "glm-5.2",
        [HumanMessage(content=[{"type": "image", "data": prefix + "x"}])],
    )
    second_key = chat_cache_module.build_cache_key(
        "user-1",
        "glm-5.2",
        [HumanMessage(content=[{"type": "image", "data": prefix + "y"}])],
    )

    assert first_key
    assert second_key
    assert first_key != second_key


def test_mock_graph_keeps_selected_model():
    model = resolve_model(None)
    result = _build_mock_graph().invoke(
        {"messages": [{"role": "user", "content": "hello"}], "selected_model": model}
    )
    assert result["selected_model"] == model
    assert model in result["messages"][-1].content


def test_conversation_title_extracts_text_from_content_blocks():
    title = _conversation_title_from_state(
        {
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "  你好，帮我总结这个项目\n"},
                        {"type": "image", "source_type": "base64"},
                    ]
                )
            ]
        }
    )

    assert title == "你好，帮我总结这个项目"


def test_frontend_image_blocks_are_normalized_for_chat_models():
    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": "识别图片里的文字"},
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "data": "abc123",
                        "metadata": {"name": "screenshot.png"},
                    },
                ]
            )
        ],
        supports_images=True,
    )

    assert isinstance(message, HumanMessage)
    assert message.content == [
        {"type": "text", "text": "识别图片里的文字"},
        {
            "type": "image",
            "mimeType": "image/png",
            "data": "abc123",
            "metadata": {"name": "screenshot.png"},
            "source_type": "base64",
            "mime_type": "image/png",
        },
    ]


def test_text_models_replace_images_across_message_history():
    messages = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": "识别图片里的文字"},
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "data": "abc123",
                        "metadata": {"name": "screenshot.png"},
                    },
                ]
            ),
            AIMessage(content="请补充说明"),
            HumanMessage(content=[{"type": "text", "text": "继续分析"}]),
        ],
        supports_images=False,
    )

    first_content = messages[0].content
    assert [block["type"] for block in first_content] == ["text", "text"]
    assert "screenshot.png" in first_content[1]["text"]
    assert "不支持读取图片内容" in first_content[1]["text"]
    assert "data" not in first_content[1]
    assert messages[2].content == [{"type": "text", "text": "继续分析"}]


def test_text_models_replace_openai_and_legacy_image_blocks():
    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                    },
                    {
                        "type": "file",
                        "mimeType": "image/jpeg",
                        "data": "def",
                        "metadata": {"filename": "legacy.jpg"},
                    },
                ]
            )
        ],
        supports_images=False,
    )

    assert [block["type"] for block in message.content] == ["text", "text"]
    assert all(
        "image_url" not in block and "data" not in block for block in message.content
    )
    assert "legacy.jpg" in message.content[1]["text"]


def test_text_models_replace_additional_provider_image_block_formats():
    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,abc",
                    },
                    {
                        "type": "media",
                        "media_type": "image/webp",
                        "data": "def",
                    },
                    {
                        "type": "file",
                        "media_type": "image/jpeg",
                        "data": "ghi",
                        "name": "camera.jpg",
                    },
                    {
                        "type": "media",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "jkl",
                        },
                    },
                    {
                        "type": "file",
                        "file": {
                            "filename": "nested.png",
                            "file_data": "data:IMAGE/PNG;base64,mno",
                        },
                    },
                    {
                        "type": "media",
                        "media_type": " IMAGE/PNG ",
                        "data": "pqr",
                    },
                ]
            )
        ],
        supports_images=False,
    )

    assert [block["type"] for block in message.content] == ["text"] * 6
    assert all(
        "image_url" not in block and "data" not in block for block in message.content
    )
    assert "camera.jpg" in message.content[2]["text"]
    assert "nested.png" in message.content[4]["text"]


def test_text_blocks_with_image_url_metadata_are_not_misclassified_as_images():
    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "图片链接仅用于业务展示",
                        "image_url": None,
                    }
                ]
            )
        ],
        supports_images=False,
    )

    assert message.content == [
        {
            "type": "text",
            "text": "图片链接仅用于业务展示",
            "image_url": None,
        }
    ]


def test_frontend_pdf_blocks_are_converted_to_text_for_chat_models():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)

    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "file",
                        "mimeType": "application/pdf",
                        "data": base64.b64encode(output.getvalue()).decode(),
                        "metadata": {"filename": "report.pdf"},
                    }
                ]
            )
        ]
    )

    assert isinstance(message, HumanMessage)
    assert len(message.content) == 1
    assert message.content[0]["type"] == "text"
    assert "report.pdf" in message.content[0]["text"]
    assert "没有可提取的文字" in message.content[0]["text"]


def test_invalid_pdf_base64_is_rejected_before_model_call():
    with pytest.raises(ValueError, match="Base64 数据无效"):
        _normalize_multimodal_messages(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "file",
                            "mimeType": "application/pdf",
                            "data": "not-valid-base64!",
                            "metadata": {"filename": "broken.pdf"},
                        }
                    ]
                )
            ]
        )


def test_pdf_attachment_count_is_limited_across_message_history():
    pdf_blocks = [
        {
            "type": "file",
            "mimeType": "application/pdf",
            "data": base64.b64encode(b"pdf").decode(),
            "metadata": {"filename": f"report-{index}.pdf"},
        }
        for index in range(chat_module.PDF_MAX_ATTACHMENTS_PER_HISTORY + 1)
    ]
    messages = [HumanMessage(content=[block]) for block in pdf_blocks]

    with pytest.raises(ValueError, match="整段消息历史最多支持 3 个 PDF 附件"):
        _normalize_multimodal_messages(messages)


def test_pdf_decoded_bytes_are_limited_across_message_history(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "max_upload_bytes", 6)
    pdf_blocks = [
        {
            "type": "file",
            "mimeType": "application/pdf",
            "data": base64.b64encode(b"1234").decode(),
            "metadata": {"filename": f"report-{index}.pdf"},
        }
        for index in range(2)
    ]
    messages = [HumanMessage(content=[block]) for block in pdf_blocks]

    with pytest.raises(ValueError, match="PDF 附件解码后总大小超过 6 字节限制"):
        _normalize_multimodal_messages(messages)


def test_pdf_history_has_eight_megabyte_decoded_limit(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "max_upload_bytes", 50 * 1024 * 1024)

    assert chat_module._pdf_history_byte_limit() == 8 * 1024 * 1024


def test_pypdf_stream_limits_are_reduced_for_chat_attachments():
    assert all(
        getattr(chat_module.pypdf_filters, limit_name)
        == chat_module.PDF_STREAM_MAX_BYTES
        == 16 * 1024 * 1024
        for limit_name in chat_module.PYPDF_STREAM_LIMIT_NAMES
    )


def test_pdf_text_extraction_stops_at_page_limit(monkeypatch):
    extracted_pages = []

    class FakePage:
        def __init__(self, page_number):
            self.page_number = page_number

        def extract_text(self):
            extracted_pages.append(self.page_number)
            return f"第 {self.page_number} 页内容"

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage(index) for index in range(1, 5)]

    monkeypatch.setattr(chat_module, "PDF_MAX_PAGES", 2)
    monkeypatch.setattr(chat_module, "PdfReader", FakeReader)
    encoded = base64.b64encode(b"fake-pdf").decode()

    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "file",
                        "mimeType": "application/pdf",
                        "data": encoded,
                        "metadata": {"filename": "pages.pdf"},
                    }
                ]
            )
        ]
    )

    assert extracted_pages == [1, 2]
    assert "仅提取前 2 页" in message.content[0]["text"]


def test_pdf_text_extraction_stops_at_character_limit(monkeypatch):
    extracted_pages = []

    class FakePage:
        def __init__(self, page_number):
            self.page_number = page_number

        def extract_text(self):
            extracted_pages.append(self.page_number)
            return str(self.page_number) * 60

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage(index) for index in range(1, 5)]

    monkeypatch.setattr(chat_module, "PDF_TEXT_MAX_CHARS", 100)
    monkeypatch.setattr(chat_module, "PdfReader", FakeReader)
    encoded = base64.b64encode(b"fake-pdf").decode()

    [message] = _normalize_multimodal_messages(
        [
            HumanMessage(
                content=[
                    {
                        "type": "file",
                        "mimeType": "application/pdf",
                        "data": encoded,
                        "metadata": {"filename": "long.pdf"},
                    }
                ]
            )
        ]
    )

    extracted = message.content[0]["text"]
    assert extracted_pages == [1, 2]
    assert "已截取前 100 个字符" in extracted
    assert "整段消息历史" in extracted


def test_pdf_character_budget_is_shared_across_message_history(monkeypatch):
    reader_calls = []
    extracted_pages = []

    class FakePage:
        def extract_text(self):
            extracted_pages.append(len(extracted_pages) + 1)
            return "文" * 50

    class FakeReader:
        def __init__(self, _stream):
            reader_calls.append(len(reader_calls) + 1)
            self.pages = [FakePage()]

    monkeypatch.setattr(chat_module, "PDF_TEXT_MAX_CHARS", 70)
    monkeypatch.setattr(chat_module, "PdfReader", FakeReader)
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "file",
                    "mimeType": "application/pdf",
                    "data": base64.b64encode(f"fake-pdf-{index}".encode()).decode(),
                    "metadata": {"filename": f"history-{index}.pdf"},
                }
            ]
        )
        for index in range(3)
    ]

    normalized = _normalize_multimodal_messages(messages)

    assert reader_calls == [1, 2]
    assert extracted_pages == [1, 2]
    assert "已截取前 70 个字符" in normalized[1].content[0]["text"]
    assert "未继续解析此附件" in normalized[2].content[0]["text"]


def test_mock_graph_persists_direct_fastapi_trace_and_conversation(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(chat_module, "SessionLocal", testing_session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", lambda *_args: None)

    try:
        _build_mock_graph().invoke(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "selected_model": resolve_model(None),
                "auth_user_id": "user-1",
            },
            config={"configurable": {"thread_id": "thread-1"}},
        )
        with testing_session() as db:
            conversation = db.scalar(select(Conversation))
            trace = db.scalar(select(TraceSpan))
            assert conversation is not None
            assert conversation.user_id == "user-1"
            assert conversation.thread_id == "thread-1"
            assert trace is not None
            assert trace.user_id == "user-1"
            assert trace.conversation_id == conversation.id
            assert trace.status == "success"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_mock_graph_uses_long_term_memory_across_threads(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(chat_module, "SessionLocal", testing_session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", lambda *_args: None)

    try:
        graph = _build_mock_graph()
        graph.invoke(
            {
                "messages": [{"role": "user", "content": "我叫何阳"}],
                "selected_model": resolve_model(None),
                "auth_user_id": "user-1",
            },
            config={"configurable": {"thread_id": "thread-1"}},
        )

        result = graph.invoke(
            {
                "messages": [{"role": "user", "content": "我叫什么名字？"}],
                "selected_model": resolve_model(None),
                "auth_user_id": "user-1",
            },
            config={"configurable": {"thread_id": "thread-2"}},
        )

        with testing_session() as db:
            memory = db.scalar(select(UserMemory))
            conversations = db.scalars(select(Conversation)).all()
            assert memory is not None
            assert memory.user_id == "user-1"
            assert memory.memory_key == "profile.name"
            assert memory.memory_value == "何阳"
            assert {conversation.thread_id for conversation in conversations} == {
                "thread-1",
                "thread-2",
            }
        assert "何阳" in result["messages"][-1].content
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_model_request_injects_long_term_memory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        with testing_session() as db:
            db.add(
                UserMemory(
                    user_id="user-1",
                    memory_key="profile.name",
                    memory_value="何阳",
                    source_thread_id="thread-1",
                )
            )
            db.commit()
            request = ModelRequest(
                model=SimpleNamespace(),
                messages=[HumanMessage(content="我叫什么？")],
                system_message=SystemMessage(content="系统提示"),
                state={},
                runtime=SimpleNamespace(),
            )

            updated = chat_module._append_memory_to_request(
                request,
                db,
                "user-1",
                "thread-2",
            )

            assert "系统提示" in updated.system_message.content
            assert "用户姓名：何阳" in updated.system_message.content
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_model_request_backfills_memory_from_existing_traces():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        with testing_session() as db:
            db.add(
                TraceSpan(
                    user_id="user-1",
                    thread_id="thread-1",
                    run_id="run-1",
                    name="model:glm-5.2",
                    span_type="model",
                    model_name="glm-5.2",
                    input={
                        "messages": [
                            {"type": "human", "content": "我叫何阳"},
                        ]
                    },
                )
            )
            db.commit()
            request = ModelRequest(
                model=SimpleNamespace(),
                messages=[HumanMessage(content="我叫什么？")],
                system_message=SystemMessage(content="系统提示"),
                state={},
                runtime=SimpleNamespace(),
            )

            updated = chat_module._append_memory_to_request(
                request,
                db,
                "user-1",
                "thread-2",
            )
            memory = db.scalar(select(UserMemory))

            assert memory is not None
            assert memory.memory_value == "何阳"
            assert "用户姓名：何阳" in updated.system_message.content
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_model_call_extracts_memory_before_normalizing_pdf_text(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(chat_module, "SessionLocal", testing_session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(
        chat_module,
        "_normalize_multimodal_messages",
        lambda _messages, **_kwargs: [HumanMessage(content="我叫 PDF文档名")],
    )
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[
            HumanMessage(
                content=[
                    {
                        "type": "file",
                        "mimeType": "application/pdf",
                        "data": base64.b64encode(b"fake-pdf").decode(),
                    }
                ]
            )
        ],
        system_message=SystemMessage(content="系统提示"),
        state={"auth_user_id": "user-1", "selected_model": resolve_model(None)},
        runtime=SimpleNamespace(config={}),
    )

    db = None
    try:
        prepared, db, *_rest = PolicyTraceMiddleware()._prepare_model_call(request)
        memory = db.scalar(select(UserMemory))
        trace = db.scalar(select(TraceSpan))

        assert prepared.messages[0].content == "我叫 PDF文档名"
        assert memory is None
        assert trace is not None
        assert "PDF文档名" not in str(trace.input)
    finally:
        if db is not None:
            db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_structured_tool_failure_is_recorded_as_trace_error():
    trace = SimpleNamespace(tool_name="web_search")
    db = SimpleNamespace(commit=lambda: None)
    result = ToolMessage(
        content='{"error":"Web Search is not configured"}',
        tool_call_id="call-1",
        name="web_search",
    )

    PolicyTraceMiddleware._finish_tool_call(db, trace, result, time.perf_counter())

    assert trace.status == "error"
    assert trace.error_message == "Web Search is not configured"
    assert trace.ended_at is not None


def test_tool_policy_violation_returns_structured_tool_message(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.closed = False

        def scalar(self, *_args):
            return None

        def add(self, *_args):
            pass

        def commit(self):
            pass

        def refresh(self, *_args):
            pass

        def close(self):
            self.closed = True

    session = FakeSession()

    def reject_tool(*_args):
        raise chat_module.PolicyViolation("已被高成本工具权限拦截")

    monkeypatch.setattr(chat_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(chat_module, "enforce_tool", reject_tool)
    request = SimpleNamespace(
        state={"auth_user_id": "user-1"},
        runtime=SimpleNamespace(),
        tool_call={
            "id": "call-stock",
            "name": "get_stock_quote",
            "args": {"symbol": "SPY"},
        },
    )

    def unexpected_handler(_request):
        raise AssertionError("权限失败时不应继续执行真实工具")

    result = PolicyTraceMiddleware().wrap_tool_call(request, unexpected_handler)

    assert isinstance(result, ToolMessage)
    assert result.name == "get_stock_quote"
    assert "已被高成本工具权限拦截" in result.content
    assert session.closed


def test_model_policy_violation_returns_user_facing_message(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.closed = False

        def scalar(self, *_args):
            return None

        def add(self, *_args):
            pass

        def commit(self):
            pass

        def refresh(self, *_args):
            pass

        def close(self):
            self.closed = True

    session = FakeSession()

    def reject_model(*_args):
        raise chat_module.PolicyViolation("请求过于频繁：每分钟最多 1 次")

    monkeypatch.setattr(chat_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", reject_model)
    monkeypatch.setattr(chat_cache_module, "cache", CacheService(FakeRedis()))
    monkeypatch.setattr(
        chat_module,
        "_append_memory_to_request",
        lambda request, *_args, **_kwargs: request,
    )
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="hello")],
        system_message=SystemMessage(content="system"),
        state={"auth_user_id": "user-1", "selected_model": "glm-5.2"},
        runtime=SimpleNamespace(),
    )

    def unexpected_handler(_request):
        raise AssertionError("限流时不应继续调用真实模型")

    result = PolicyTraceMiddleware().wrap_model_call(request, unexpected_handler)

    assert "发送太频繁了" in result.result[0].content
    assert "每分钟最多 1 次" in result.result[0].content
    assert session.closed


@pytest.mark.asyncio
async def test_async_model_policy_violation_returns_user_facing_message(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.closed = False

        def scalar(self, *_args):
            return None

        def add(self, *_args):
            pass

        def commit(self):
            pass

        def refresh(self, *_args):
            pass

        def close(self):
            self.closed = True

    session = FakeSession()

    def reject_model(*_args):
        raise chat_module.PolicyViolation("请求过于频繁：每分钟最多 1 次")

    monkeypatch.setattr(chat_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(chat_module, "authorize_model_access", lambda *_args: None)
    monkeypatch.setattr(chat_module, "enforce_model", reject_model)
    monkeypatch.setattr(chat_cache_module, "cache", CacheService(FakeRedis()))
    monkeypatch.setattr(
        chat_module,
        "_append_memory_to_request",
        lambda request, *_args, **_kwargs: request,
    )
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="hello")],
        system_message=SystemMessage(content="system"),
        state={"auth_user_id": "user-1", "selected_model": "glm-5.2"},
        runtime=SimpleNamespace(),
    )

    async def unexpected_handler(_request):
        raise AssertionError("限流时不应继续调用真实模型")

    result = await PolicyTraceMiddleware().awrap_model_call(request, unexpected_handler)

    assert "发送太频繁了" in result.result[0].content
    assert "每分钟最多 1 次" in result.result[0].content
    assert session.closed


def test_image_generation_tool_validates_missing_configuration(monkeypatch):
    monkeypatch.setattr(image_tools.settings, "image_generation_enabled", True)
    monkeypatch.setattr(image_tools.settings, "zhipu_api_key", "")

    result = image_tools.generate_image.func("雨天打伞的小狗")

    assert result["error"].startswith(
        "图片生成尚未配置，请联系管理员配置图片生成服务。"
    )


def test_stock_quote_maps_chinese_index_alias(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Global Quote": {
                    "01. symbol": "SPY",
                    "02. open": "620.0000",
                    "03. high": "622.0000",
                    "04. low": "618.0000",
                    "05. price": "621.5000",
                    "06. volume": "123456",
                    "07. latest trading day": "2026-07-20",
                    "08. previous close": "619.0000",
                    "09. change": "2.5000",
                    "10. change percent": "0.4039%",
                }
            }

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, params):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(external_tools.settings, "alpha_vantage_api_key", "test-key")
    monkeypatch.setattr(external_tools, "cache", CacheService(FakeRedis()))
    monkeypatch.setattr(external_tools.httpx, "Client", FakeClient)

    result = external_tools.get_stock_quote.func("标普500当前价格")

    assert captured["params"]["symbol"] == "SPY"
    assert result["requested_symbol"] == "标普500当前价格"
    assert result["resolved_symbol"] == "SPY"
    assert result["display_name"] == "标普500 ETF（SPY，跟踪标普500指数）"
    assert result["price"] == "621.5000"


def test_image_generation_tool_returns_markdown_from_service(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"url": "https://example.test/dog.png"}]}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(image_tools.settings, "image_generation_enabled", True)
    monkeypatch.setattr(image_tools.settings, "zhipu_api_key", "test-key")
    monkeypatch.setattr(image_tools.settings, "zhipu_base_url", "https://example.test")
    monkeypatch.setattr(image_tools.settings, "zhipu_image_model", "glm-image")
    monkeypatch.setattr(image_tools.settings, "image_api_timeout", 120.0)
    monkeypatch.setattr(image_tools.httpx, "Client", FakeClient)

    result = image_tools.generate_image.func("雨天打伞的小狗", "1280x1280")

    assert captured["url"] == "https://example.test/images/generations"
    assert captured["json"] == {
        "model": "glm-image",
        "prompt": "雨天打伞的小狗",
        "size": "1280x1280",
        "quality": "hd",
    }
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert result["image_url"] == "https://example.test/dog.png"
    assert result["markdown"] == "![生成图片](https://example.test/dog.png)"


def test_local_storage_round_trip(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("HY-Agent storage", encoding="utf-8")
    root = tmp_path / "objects"
    monkeypatch.setattr(storage, "backend", "local")
    monkeypatch.setattr(storage, "local_root", root)

    result = storage.put_path(source, "user-1", "notes.txt", "text/plain")
    stored = storage.open_local(result.object_key)
    assert stored.read_text(encoding="utf-8") == "HY-Agent storage"
    assert len(result.sha256) == 64

    storage.delete(result.object_key)
    assert not stored.exists()
