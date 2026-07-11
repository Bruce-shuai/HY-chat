from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

import app.api.routers.chat as chat_module
from app.agents.chat import _build_mock_graph
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_system_endpoints_and_sse(monkeypatch):
    monkeypatch.setattr(chat_module, "graph", _build_mock_graph())
    monkeypatch.setattr(chat_module, "enforce_model", lambda *_args, **_kwargs: None)
    policy = SimpleNamespace(
        allowed_models=chat_module.settings.available_chat_models,
        rpm_limit=30,
        monthly_token_quota=1000,
        tokens_used=0,
        quota_reset_at=datetime.utcnow(),
        allow_image_generation=True,
        allow_high_cost_tools=True,
    )
    user = SimpleNamespace(id="test-user", role="user", policy=policy)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            models = await client.get("/models")
            assert models.status_code == 200
            assert models.json()["current_model"]

            tools = await client.get("/tools")
            assert tools.status_code == 200
            assert len(tools.json()["tools"]) == 9

            formats = await client.get("/rag/formats")
            assert ".pdf" in formats.json()["extensions"]

            response = await client.post(
                "/chat/stream",
                json={"message": "hello", "use_cache": False},
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "event: token" in response.text
            assert "event: done" in response.text
    finally:
        app.dependency_overrides.clear()
