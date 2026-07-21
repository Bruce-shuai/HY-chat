import logging
import time
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime, ServerInfo
from redis.exceptions import RedisError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.chat as chat_module
import app.cache.service as cache_service_module
from app.agents.chat import (
    HITL_TOOL_CONFIG,
    PolicyTraceMiddleware,
    _build_mock_graph,
    _conversation_title_from_state,
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
    first = service._hash_embedding("HY-chat RAG")
    second = service._hash_embedding("HY-chat RAG")
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
    source.write_text("HY-chat storage", encoding="utf-8")
    root = tmp_path / "objects"
    monkeypatch.setattr(storage, "backend", "local")
    monkeypatch.setattr(storage, "local_root", root)

    result = storage.put_path(source, "user-1", "notes.txt", "text/plain")
    stored = storage.open_local(result.object_key)
    assert stored.read_text(encoding="utf-8") == "HY-chat storage"
    assert len(result.sha256) == 64

    storage.delete(result.object_key)
    assert not stored.exists()
