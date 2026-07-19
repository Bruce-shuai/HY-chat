import logging
import time
from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime, ServerInfo
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.chat as chat_module
from app.agents.chat import (
    HITL_TOOL_CONFIG,
    PolicyTraceMiddleware,
    _build_mock_graph,
    _conversation_title_from_state,
    build_hitl_middleware,
)
from app.cache.service import CacheService
from app.core.logging import configure_logging
from app.db.models import Conversation, TraceSpan
from app.db.session import Base
from app.models.catalog import list_models, resolve_model
from app.rag.embeddings import EmbeddingService
from app.tools.registry import tool_manifest
from app.storage.service import storage


def test_logging_configuration_sets_root_level():
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    configure_logging("INFO")


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def scan_iter(self, match, count=200):
        prefix = match.removesuffix("*")
        return [key for key in self.values if key.startswith(prefix)]

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def ping(self):
        return True


def test_model_catalog_and_tool_registry():
    models = list_models()
    assert models
    assert resolve_model(None) in {model.id for model in models}
    assert {tool["name"] for tool in tool_manifest()} >= {
        "search_knowledge_base",
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
