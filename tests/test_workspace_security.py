from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from redis.exceptions import RedisError

import app.api.routers.coding_agent as coding_agent_module
import app.tools.builtin as builtin_tools
from app.auth.dependencies import get_current_user
from app.core.types import UserRole
from app.db.session import get_db
from app.main import app
from app.policies.service import PolicyViolation, WORKSPACE_READ_TOOLS, enforce_tool


class FakeSession:
    def __init__(self, user=None):
        self.user = user
        self.closed = False

    def get(self, _model, _identity):
        return self.user

    def close(self):
        self.closed = True


def test_coding_agent_status_cache_is_best_effort(monkeypatch):
    monkeypatch.setattr(
        coding_agent_module.redis_client,
        "setex",
        Mock(side_effect=RedisError("redis unavailable")),
    )

    coding_agent_module._set_cached_run_status("run:1", "running")


@pytest.mark.parametrize(
    "tool_name",
    [
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_code",
    ],
)
def test_workspace_tools_are_admin_only_in_policy_middleware(tool_name):
    regular_user = SimpleNamespace(is_active=True, role=UserRole.USER)
    with pytest.raises(PolicyViolation, match="仅限管理员"):
        enforce_tool(FakeSession(regular_user), "user-id", tool_name)

    admin = SimpleNamespace(is_active=True, role=UserRole.ADMIN)
    enforce_tool(FakeSession(admin), "admin-id", tool_name)


def test_high_cost_tool_policy_error_is_explicit():
    policy = SimpleNamespace(
        quota_reset_at=datetime(2026, 8, 1),
        tokens_used=0,
        allow_high_cost_tools=False,
    )
    regular_user = SimpleNamespace(
        is_active=True,
        role=UserRole.USER,
        policy=policy,
    )

    enforce_tool(FakeSession(regular_user), "user-id", "web_search")

    with pytest.raises(PolicyViolation, match="高成本工具权限拦截"):
        enforce_tool(FakeSession(regular_user), "user-id", "get_stock_quote")


@pytest.mark.parametrize(
    ("tool", "arguments", "backend_name"),
    [
        (builtin_tools.list_workspace_files, {"path": "."}, "list_files"),
        (
            builtin_tools.read_workspace_file,
            {"path": "README.md"},
            "read_file",
        ),
        (
            builtin_tools.search_workspace_code,
            {"query": "secret", "path": "."},
            "search_code",
        ),
    ],
)
def test_workspace_tools_recheck_runtime_user_before_file_access(
    monkeypatch, tool, arguments, backend_name
):
    user = SimpleNamespace(is_active=True, role=UserRole.USER)
    session = FakeSession(user)
    backend = Mock(return_value={"status": "ok"})
    monkeypatch.setattr(builtin_tools, "SessionLocal", lambda: session)
    monkeypatch.setattr(builtin_tools, backend_name, backend)
    runtime = SimpleNamespace(state={"auth_user_id": "user-id"})

    with pytest.raises(PolicyViolation, match="仅限管理员"):
        tool.func(runtime=runtime, **arguments)

    backend.assert_not_called()
    assert session.closed


def test_workspace_tool_runtime_allows_admin(monkeypatch):
    admin = SimpleNamespace(is_active=True, role=UserRole.ADMIN)
    session = FakeSession(admin)
    backend = Mock(return_value={"files": ["README.md"]})
    monkeypatch.setattr(builtin_tools, "SessionLocal", lambda: session)
    monkeypatch.setattr(builtin_tools, "list_files", backend)
    runtime = SimpleNamespace(state={"auth_user_id": "admin-id"})

    result = builtin_tools.list_workspace_files.func(runtime=runtime, path=".")

    assert result == {"files": ["README.md"]}
    backend.assert_called_once_with(".")
    assert session.closed


@pytest.mark.asyncio
async def test_tool_manifest_marks_workspace_tools_disabled_for_regular_users():
    policy = SimpleNamespace(
        allowed_models=[],
        rpm_limit=30,
        monthly_token_quota=1000,
        tokens_used=0,
        quota_reset_at=None,
        allow_high_cost_tools=True,
    )
    regular_user = SimpleNamespace(id="user-id", role=UserRole.USER, policy=policy)
    app.dependency_overrides[get_current_user] = lambda: regular_user
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/tools")

        assert response.status_code == 200
        tools = {item["name"]: item["enabled"] for item in response.json()["tools"]}
        assert all(tools[name] is False for name in WORKSPACE_READ_TOOLS)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_coding_agent_run_endpoints_require_admin(monkeypatch):
    regular_user = SimpleNamespace(id="user-id", role=UserRole.USER)
    fake_db = SimpleNamespace()
    app.dependency_overrides[get_current_user] = lambda: regular_user
    app.dependency_overrides[get_db] = lambda: fake_db
    graph_call = Mock(side_effect=AssertionError("coding graph must not run"))
    monkeypatch.setattr(coding_agent_module, "run_agent_graph", graph_call)
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            responses = [
                await client.get("/coding-agent/runs"),
                await client.get("/coding-agent/runs/other-run"),
                await client.post(
                    "/coding-agent/runs",
                    json={"task": "read the workspace"},
                ),
            ]

            assert [response.status_code for response in responses] == [403, 403, 403]
            assert all(
                response.json()["detail"] == "需要管理员权限" for response in responses
            )
            graph_call.assert_not_called()

            admin = SimpleNamespace(id="admin-id", role=UserRole.ADMIN)
            admin_db = SimpleNamespace(
                scalars=lambda _statement: SimpleNamespace(all=lambda: [])
            )
            app.dependency_overrides[get_current_user] = lambda: admin
            app.dependency_overrides[get_db] = lambda: admin_db

            allowed = await client.get("/coding-agent/runs")
            assert allowed.status_code == 200
            assert allowed.json() == []
    finally:
        app.dependency_overrides.clear()
