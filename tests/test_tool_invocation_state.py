from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, ToolMessage
from langgraph.runtime import ExecutionInfo, Runtime, ServerInfo
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.chat as chat_module
from app.agents.chat import PolicyTraceMiddleware, build_hitl_middleware
from app.core.types import ApprovalStatus, ToolInvocationStatus
from app.db.models import Approval, Conversation, ToolInvocation
from app.db.session import Base
from app.services.tool_invocation_service import (
    ApprovalConflict,
    ApprovalDecision,
    ToolInvocationConflict,
    ToolInvocationOwnershipError,
    claim_tool_invocation,
    complete_tool_invocation,
    ensure_pending_approvals,
    invocation_idempotency_key,
    record_approval_decisions,
)


@pytest.fixture
def state_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield testing_session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _tool_call(
    *,
    call_id: str = "call-1",
    query: str = "HY-Agent",
) -> dict[str, object]:
    return {
        "id": call_id,
        "name": "web_search",
        "args": {"query": query},
        "type": "tool_call",
    }


def _approval_decision(
    decision_type: str,
    *,
    query: str = "HY-Agent",
    effective_query: str | None = None,
) -> ApprovalDecision:
    effective_query = effective_query or query
    payload: dict[str, object] = {"type": decision_type}
    if decision_type == "edit":
        payload["edited_action"] = {
            "name": "web_search",
            "args": {"query": effective_query},
        }
    if decision_type == "reject":
        payload["message"] = "用户拒绝联网"
    return ApprovalDecision(
        tool_call_id="call-1",
        tool_name="web_search",
        requested_input={"query": query},
        decision_type=decision_type,
        effective_tool_name="web_search",
        effective_input={"query": effective_query},
        decision_payload=payload,
    )


def _create_pending_approval(testing_session, *, user_id: str = "user-a") -> None:
    with testing_session() as db:
        ensure_pending_approvals(
            db,
            user_id=user_id,
            thread_id="thread-1",
            runtime_run_id="run-1",
            tool_calls=[_tool_call()],
        )


@pytest.mark.parametrize(
    ("decision_type", "expected_approval", "expected_invocation"),
    [
        ("approve", ApprovalStatus.APPROVED, ToolInvocationStatus.APPROVED),
        ("edit", ApprovalStatus.EDITED, ToolInvocationStatus.APPROVED),
        ("reject", ApprovalStatus.REJECTED, ToolInvocationStatus.REJECTED),
    ],
)
def test_approval_state_machine_is_idempotent_and_immutable(
    state_db,
    decision_type,
    expected_approval,
    expected_invocation,
):
    _create_pending_approval(state_db)
    decision = _approval_decision(
        decision_type,
        effective_query="edited query" if decision_type == "edit" else None,
    )

    with state_db() as db:
        record_approval_decisions(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-resume",
            decisions=[decision],
        )
        # An identical resume is a no-op, not a second decision.
        record_approval_decisions(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-resume-2",
            decisions=[decision],
        )

        invocation = db.scalar(select(ToolInvocation))
        approval = db.scalar(select(Approval))
        assert invocation is not None
        assert approval is not None
        assert invocation.status == expected_invocation
        assert approval.status == expected_approval
        assert invocation.runtime_run_id == "run-1"
        if decision_type == "edit":
            assert invocation.effective_input == {"query": "edited query"}

        conflicting = (
            _approval_decision("reject")
            if decision_type != "reject"
            else _approval_decision("approve")
        )
        with pytest.raises(ApprovalConflict):
            record_approval_decisions(
                db,
                user_id="user-a",
                thread_id="thread-1",
                runtime_run_id="run-conflict",
                decisions=[conflicting],
            )


def test_user_scoped_idempotency_and_payload_conflict(state_db):
    with state_db() as db:
        first = claim_tool_invocation(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-a",
            tool_call_id="call-shared",
            tool_name="web_search",
            requested_input={"query": "one"},
        )
        second_user = claim_tool_invocation(
            db,
            user_id="user-b",
            thread_id="thread-1",
            runtime_run_id="run-b",
            tool_call_id="call-shared",
            tool_name="web_search",
            requested_input={"query": "one"},
        )

        assert first.should_execute
        assert second_user.should_execute
        assert first.invocation_id != second_user.invocation_id
        assert invocation_idempotency_key(
            "user-a", "thread-1", "call-shared"
        ) != invocation_idempotency_key("user-b", "thread-1", "call-shared")

        with pytest.raises(ToolInvocationConflict):
            claim_tool_invocation(
                db,
                user_id="user-a",
                thread_id="thread-1",
                runtime_run_id="run-a-retry",
                tool_call_id="call-shared",
                tool_name="web_search",
                requested_input={"query": "different"},
            )


def test_cross_user_thread_is_rejected_before_state_is_created(state_db):
    with state_db() as db:
        db.add(
            Conversation(
                id="conversation-a",
                user_id="user-a",
                thread_id="thread-owned-by-a",
            )
        )
        db.commit()

        with pytest.raises(ToolInvocationOwnershipError):
            claim_tool_invocation(
                db,
                user_id="user-b",
                thread_id="thread-owned-by-a",
                runtime_run_id="run-b",
                tool_call_id="call-b",
                tool_name="web_search",
                requested_input={"query": "private"},
            )
        assert db.scalar(select(ToolInvocation)) is None


def test_completed_invocation_reuses_result_without_second_claim(state_db):
    with state_db() as db:
        claim = claim_tool_invocation(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-1",
            tool_call_id="call-1",
            tool_name="web_search",
            requested_input={"query": "HY-Agent"},
        )
        complete_tool_invocation(
            db,
            claim=claim,
            result=ToolMessage(
                content='{"answer":"once"}',
                name="web_search",
                tool_call_id="call-1",
            ),
            error_message=None,
        )
        db.commit()

        replay = claim_tool_invocation(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-retry",
            tool_call_id="call-1",
            tool_name="web_search",
            requested_input={"query": "HY-Agent"},
        )
        invocation = db.get(ToolInvocation, claim.invocation_id)

        assert replay.should_execute is False
        assert replay.status == ToolInvocationStatus.SUCCEEDED
        assert replay.output["content"] == '{"answer":"once"}'
        assert invocation is not None
        assert invocation.attempt_count == 1


def test_same_approval_resume_is_valid_after_tool_completed(state_db):
    _create_pending_approval(state_db)
    decision = _approval_decision("approve")
    with state_db() as db:
        record_approval_decisions(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-resume",
            decisions=[decision],
        )
        claim = claim_tool_invocation(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-execute",
            tool_call_id="call-1",
            tool_name="web_search",
            requested_input={"query": "HY-Agent"},
        )
        complete_tool_invocation(
            db,
            claim=claim,
            result=ToolMessage(
                content="done",
                name="web_search",
                tool_call_id="call-1",
            ),
            error_message=None,
        )
        db.commit()

        record_approval_decisions(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-replay",
            decisions=[decision],
        )
        invocation = db.get(ToolInvocation, claim.invocation_id)
        assert invocation is not None
        assert invocation.status == ToolInvocationStatus.SUCCEEDED


def test_concurrent_claim_allows_only_one_executor(tmp_path):
    database_path = tmp_path / "tool-state.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    _create_pending_approval(testing_session)
    decision = _approval_decision("approve")
    with testing_session() as db:
        record_approval_decisions(
            db,
            user_id="user-a",
            thread_id="thread-1",
            runtime_run_id="run-resume",
            decisions=[decision],
        )

    def claim_once(run_id: str) -> bool:
        with testing_session() as db:
            return claim_tool_invocation(
                db,
                user_id="user-a",
                thread_id="thread-1",
                runtime_run_id=run_id,
                tool_call_id="call-1",
                tool_name="web_search",
                requested_input={"query": "HY-Agent"},
            ).should_execute

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim_once, ("run-a", "run-b")))
        assert sorted(results) == [False, True]
        with testing_session() as db:
            invocation = db.scalar(select(ToolInvocation))
            assert invocation is not None
            assert invocation.status == ToolInvocationStatus.RUNNING
            assert invocation.attempt_count == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_hitl_edit_persists_before_tool_execution(state_db, monkeypatch):
    monkeypatch.setattr(chat_module, "SessionLocal", state_db)
    monkeypatch.setattr(
        chat_module.hitl_module,
        "interrupt",
        lambda _request: {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": "web_search",
                        "args": {"query": "edited query"},
                    },
                }
            ]
        },
    )
    middleware = build_hitl_middleware()
    state = {
        "auth_user_id": "user-a",
        "messages": [AIMessage(content="", tool_calls=[_tool_call()])],
    }
    runtime = Runtime(
        execution_info=ExecutionInfo(
            checkpoint_id="checkpoint-1",
            checkpoint_ns="",
            task_id="task-1",
            thread_id="thread-1",
            run_id="run-1",
        ),
        server_info=ServerInfo(assistant_id="assistant-1", graph_id="hy-chat"),
    )

    result = middleware.after_model(state, runtime)

    assert result is not None
    revised_message = result["messages"][0]
    assert revised_message.tool_calls[0]["args"] == {"query": "edited query"}
    with state_db() as db:
        invocation = db.scalar(select(ToolInvocation))
        approval = db.scalar(select(Approval))
        assert invocation is not None
        assert approval is not None
        assert invocation.status == ToolInvocationStatus.APPROVED
        assert invocation.effective_input == {"query": "edited query"}
        assert approval.status == ApprovalStatus.EDITED


def test_policy_middleware_executes_same_tool_only_once(state_db, monkeypatch):
    monkeypatch.setattr(chat_module, "SessionLocal", state_db)
    monkeypatch.setattr(chat_module, "enforce_tool", lambda *_args: None)
    middleware = PolicyTraceMiddleware()
    request = SimpleNamespace(
        state={"auth_user_id": "user-a"},
        runtime=SimpleNamespace(
            execution_info=SimpleNamespace(thread_id="thread-1", run_id="run-1"),
            config={},
        ),
        tool_call=_tool_call(),
    )
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(
            content='{"answer":"once"}',
            name="web_search",
            tool_call_id="call-1",
        )

    first = middleware.wrap_tool_call(request, handler)
    second = middleware.wrap_tool_call(request, handler)

    assert first.content == '{"answer":"once"}'
    assert second.content == '{"answer":"once"}'
    assert calls == 1
    with state_db() as db:
        invocation = db.scalar(select(ToolInvocation))
        assert invocation is not None
        assert invocation.status == ToolInvocationStatus.SUCCEEDED
        assert invocation.attempt_count == 1


@pytest.mark.asyncio
async def test_async_policy_middleware_uses_same_idempotent_path(
    state_db,
    monkeypatch,
):
    monkeypatch.setattr(chat_module, "SessionLocal", state_db)
    monkeypatch.setattr(chat_module, "enforce_tool", lambda *_args: None)
    middleware = PolicyTraceMiddleware()
    request = SimpleNamespace(
        state={"auth_user_id": "user-a"},
        runtime=SimpleNamespace(
            execution_info=SimpleNamespace(
                thread_id="thread-async",
                run_id="run-async",
            ),
            config={},
        ),
        tool_call=_tool_call(call_id="call-async"),
    )
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return ToolMessage(
            content="async once",
            name="web_search",
            tool_call_id="call-async",
        )

    first = await middleware.awrap_tool_call(request, handler)
    second = await middleware.awrap_tool_call(request, handler)

    assert first.content == "async once"
    assert second.content == "async once"
    assert calls == 1
