import logging

from app.agents.chat import _build_mock_graph
from app.cache.service import CacheService
from app.core.logging import configure_logging
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
