from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.types import (
    ApprovalStatus,
    JsonObject,
    JsonValue,
    ToolInvocationStatus,
)
from app.db.models import Approval, Conversation, ToolInvocation
from app.tracing.service import safe_json

TOOL_STATE_PAYLOAD_MAX_CHARS = 200_000


class ToolInvocationConflict(ValueError):
    """The same idempotency scope was reused with different tool input."""


class ToolInvocationOwnershipError(PermissionError):
    """The supplied thread belongs to another user."""


class ApprovalConflict(ValueError):
    """An approval was already finalized with a different decision."""


class _ConcurrentDecision(RuntimeError):
    pass


@dataclass(frozen=True)
class ApprovalDecision:
    tool_call_id: str
    tool_name: str
    requested_input: Mapping[str, object]
    decision_type: str
    effective_tool_name: str
    effective_input: Mapping[str, object]
    decision_payload: Mapping[str, object]


@dataclass(frozen=True)
class ToolInvocationClaim:
    invocation_id: str
    conversation_id: str | None
    tool_call_id: str
    tool_name: str
    status: ToolInvocationStatus
    should_execute: bool
    output: JsonObject
    error_message: str | None


def _json_object(value: object) -> JsonObject:
    normalized = safe_json(value, max_length=TOOL_STATE_PAYLOAD_MAX_CHARS)
    if isinstance(normalized, dict):
        return normalized
    return {"value": normalized}


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_object(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def invocation_idempotency_key(
    user_id: str,
    thread_id: str | None,
    tool_call_id: str,
) -> str:
    """Build an opaque key scoped to the authenticated user and thread."""

    scope = json.dumps(
        [user_id, thread_id or "<direct>", tool_call_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _validate_identity(
    thread_id: str | None,
    runtime_run_id: str | None,
    tool_call_id: str,
) -> None:
    if thread_id is not None and len(thread_id) > 64:
        raise ToolInvocationConflict("thread_id 超过 64 个字符")
    if runtime_run_id is not None and len(runtime_run_id) > 128:
        raise ToolInvocationConflict("runtime_run_id 超过 128 个字符")
    if not tool_call_id:
        raise ToolInvocationConflict("工具调用缺少 tool_call_id")
    if len(tool_call_id) > 255:
        raise ToolInvocationConflict("tool_call_id 超过 255 个字符")


def _conversation_id_for_user(
    db: Session,
    user_id: str,
    thread_id: str | None,
) -> str | None:
    if not thread_id:
        return None
    conversation = db.scalar(
        select(Conversation).where(Conversation.thread_id == thread_id)
    )
    if conversation is None:
        return None
    if conversation.user_id != user_id:
        raise ToolInvocationOwnershipError("无权访问该工具调用所属会话")
    return conversation.id


def _insert_do_nothing(
    db: Session,
    model: type[ToolInvocation] | type[Approval],
    values: dict[str, object],
    *,
    index_elements: Sequence[str],
) -> None:
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(model).values(**values)
        db.execute(statement.on_conflict_do_nothing(index_elements=index_elements))
        return
    if dialect_name == "sqlite":
        statement = sqlite_insert(model).values(**values)
        db.execute(statement.on_conflict_do_nothing(index_elements=index_elements))
        return

    try:
        with db.begin_nested():
            db.add(model(**values))
            db.flush()
    except IntegrityError:
        pass


def _ensure_invocation(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    runtime_run_id: str | None,
    tool_call_id: str,
    tool_name: str,
    requested_input: Mapping[str, object],
    approval_required: bool,
    allow_effective_match: bool = False,
) -> ToolInvocation:
    _validate_identity(thread_id, runtime_run_id, tool_call_id)
    requested = _json_object(requested_input)
    idempotency_key = invocation_idempotency_key(user_id, thread_id, tool_call_id)
    now = datetime.utcnow()
    initial_status = (
        ToolInvocationStatus.PENDING_APPROVAL
        if approval_required
        else ToolInvocationStatus.PENDING
    )
    _insert_do_nothing(
        db,
        ToolInvocation,
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": _conversation_id_for_user(db, user_id, thread_id),
            "thread_id": thread_id,
            "runtime_run_id": runtime_run_id,
            "tool_call_id": tool_call_id,
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "effective_tool_name": tool_name,
            "requested_input": requested,
            "effective_input": requested,
            "output": {},
            "status": initial_status,
            "attempt_count": 0,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=("user_id", "idempotency_key"),
    )
    invocation = db.scalar(
        select(ToolInvocation).where(
            ToolInvocation.user_id == user_id,
            ToolInvocation.idempotency_key == idempotency_key,
        )
    )
    if invocation is None:
        raise RuntimeError("无法创建或读取工具调用状态")
    original_payload_matches = invocation.tool_name == tool_name and _canonical_json(
        invocation.requested_input
    ) == _canonical_json(requested)
    effective_payload_matches = (
        allow_effective_match
        and invocation.effective_tool_name == tool_name
        and _canonical_json(invocation.effective_input) == _canonical_json(requested)
    )
    if (
        invocation.thread_id != thread_id
        or invocation.tool_call_id != tool_call_id
        or not (original_payload_matches or effective_payload_matches)
    ):
        raise ToolInvocationConflict(
            "同一幂等键已用于不同的工具名称或参数，已阻止重复执行"
        )
    if not invocation.runtime_run_id and runtime_run_id:
        invocation.runtime_run_id = runtime_run_id
        invocation.updated_at = now
        db.flush()

    if (
        approval_required
        and invocation.status == ToolInvocationStatus.PENDING
        and invocation.attempt_count == 0
    ):
        invocation.status = ToolInvocationStatus.PENDING_APPROVAL
        invocation.updated_at = now
        db.flush()
    return invocation


def ensure_pending_approvals(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    runtime_run_id: str | None,
    tool_calls: Sequence[Mapping[str, object]],
) -> None:
    """Idempotently create pending invocation and approval rows before interrupt."""

    try:
        for tool_call in tool_calls:
            tool_call_id = str(tool_call.get("id") or "")
            tool_name = str(tool_call.get("name") or "unknown")
            args = tool_call.get("args")
            requested_input = args if isinstance(args, Mapping) else {}
            invocation = _ensure_invocation(
                db,
                user_id=user_id,
                thread_id=thread_id,
                runtime_run_id=runtime_run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                requested_input=requested_input,
                approval_required=True,
            )
            _insert_do_nothing(
                db,
                Approval,
                {
                    "id": str(uuid.uuid4()),
                    "invocation_id": invocation.id,
                    "user_id": user_id,
                    "idempotency_key": invocation.idempotency_key,
                    "status": ApprovalStatus.PENDING,
                    "decision_payload": {},
                    "requested_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
                index_elements=("user_id", "idempotency_key"),
            )
            approval = db.scalar(
                select(Approval).where(
                    Approval.user_id == user_id,
                    Approval.idempotency_key == invocation.idempotency_key,
                )
            )
            if approval is None or approval.invocation_id != invocation.id:
                raise ApprovalConflict("审批幂等键已绑定到其他工具调用")
        db.commit()
    except Exception:
        db.rollback()
        raise


def _approval_status(decision_type: str) -> ApprovalStatus:
    status_by_decision = {
        "approve": ApprovalStatus.APPROVED,
        "edit": ApprovalStatus.EDITED,
        "reject": ApprovalStatus.REJECTED,
    }
    try:
        return status_by_decision[decision_type]
    except KeyError as exc:
        raise ApprovalConflict(f"不支持的审批决定：{decision_type}") from exc


def _decision_matches(
    approval: Approval,
    invocation: ToolInvocation,
    decision: ApprovalDecision,
) -> bool:
    expected_approval_status = _approval_status(decision.decision_type)
    allowed_invocation_statuses = (
        {ToolInvocationStatus.REJECTED}
        if expected_approval_status == ApprovalStatus.REJECTED
        else {
            ToolInvocationStatus.APPROVED,
            ToolInvocationStatus.RUNNING,
            ToolInvocationStatus.SUCCEEDED,
            ToolInvocationStatus.FAILED,
        }
    )
    return (
        approval.status == expected_approval_status
        and _canonical_json(approval.decision_payload)
        == _canonical_json(decision.decision_payload)
        and invocation.status in allowed_invocation_statuses
        and invocation.effective_tool_name == decision.effective_tool_name
        and _canonical_json(invocation.effective_input)
        == _canonical_json(decision.effective_input)
    )


def _load_decision_rows(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    runtime_run_id: str | None,
    decision: ApprovalDecision,
) -> tuple[ToolInvocation, Approval]:
    invocation = _ensure_invocation(
        db,
        user_id=user_id,
        thread_id=thread_id,
        runtime_run_id=runtime_run_id,
        tool_call_id=decision.tool_call_id,
        tool_name=decision.tool_name,
        requested_input=decision.requested_input,
        approval_required=True,
    )
    approval = db.scalar(
        select(Approval).where(
            Approval.invocation_id == invocation.id,
            Approval.user_id == user_id,
        )
    )
    if approval is None:
        raise ApprovalConflict("工具调用没有待处理的审批记录")
    return invocation, approval


def record_approval_decisions(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    runtime_run_id: str | None,
    decisions: Sequence[ApprovalDecision],
) -> None:
    """Finalize a resumed HITL decision batch once, without last-writer-wins."""

    now = datetime.utcnow()
    try:
        for decision in decisions:
            invocation, approval = _load_decision_rows(
                db,
                user_id=user_id,
                thread_id=thread_id,
                runtime_run_id=runtime_run_id,
                decision=decision,
            )
            if approval.status != ApprovalStatus.PENDING:
                if not _decision_matches(approval, invocation, decision):
                    raise ApprovalConflict("审批已使用不同决定完成，不能覆盖")
                continue

            approval_status = _approval_status(decision.decision_type)
            invocation_status = (
                ToolInvocationStatus.REJECTED
                if approval_status == ApprovalStatus.REJECTED
                else ToolInvocationStatus.APPROVED
            )
            approval_result = db.execute(
                update(Approval)
                .where(
                    Approval.id == approval.id,
                    Approval.user_id == user_id,
                    Approval.status == ApprovalStatus.PENDING,
                )
                .values(
                    status=approval_status,
                    decision_payload=_json_object(decision.decision_payload),
                    decided_by_user_id=user_id,
                    decided_at=now,
                    updated_at=now,
                )
            )
            if approval_result.rowcount != 1:
                raise _ConcurrentDecision

            invocation_values: dict[str, object] = {
                "status": invocation_status,
                "effective_tool_name": decision.effective_tool_name,
                "effective_input": _json_object(decision.effective_input),
                "updated_at": now,
            }
            if invocation_status == ToolInvocationStatus.REJECTED:
                invocation_values["completed_at"] = now
                invocation_values["error_message"] = "用户拒绝了工具调用"
            invocation_result = db.execute(
                update(ToolInvocation)
                .where(
                    ToolInvocation.id == invocation.id,
                    ToolInvocation.user_id == user_id,
                    ToolInvocation.status == ToolInvocationStatus.PENDING_APPROVAL,
                )
                .values(**invocation_values)
            )
            if invocation_result.rowcount != 1:
                raise _ConcurrentDecision
        db.commit()
        return
    except _ConcurrentDecision:
        db.rollback()
    except Exception:
        db.rollback()
        raise

    # A racing resume may have committed the same decision. Treat only an exact
    # match as idempotent; a different decision is a hard conflict.
    try:
        for decision in decisions:
            invocation, approval = _load_decision_rows(
                db,
                user_id=user_id,
                thread_id=thread_id,
                runtime_run_id=runtime_run_id,
                decision=decision,
            )
            if not _decision_matches(approval, invocation, decision):
                raise ApprovalConflict("审批已并发完成且决定不同，已阻止覆盖")
        db.commit()
    except Exception:
        db.rollback()
        raise


def _claim_snapshot(
    invocation: ToolInvocation,
    *,
    should_execute: bool,
) -> ToolInvocationClaim:
    return ToolInvocationClaim(
        invocation_id=invocation.id,
        conversation_id=invocation.conversation_id,
        tool_call_id=invocation.tool_call_id,
        tool_name=invocation.effective_tool_name,
        status=invocation.status,
        should_execute=should_execute,
        output=dict(invocation.output or {}),
        error_message=invocation.error_message,
    )


def claim_tool_invocation(
    db: Session,
    *,
    user_id: str,
    thread_id: str | None,
    runtime_run_id: str | None,
    tool_call_id: str,
    tool_name: str,
    requested_input: Mapping[str, object],
) -> ToolInvocationClaim:
    """Atomically claim one invocation or return its existing durable state."""

    try:
        invocation = _ensure_invocation(
            db,
            user_id=user_id,
            thread_id=thread_id,
            runtime_run_id=runtime_run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            requested_input=requested_input,
            approval_required=False,
            allow_effective_match=True,
        )
        effective_input = _json_object(requested_input)
        if invocation.effective_tool_name != tool_name or _canonical_json(
            invocation.effective_input
        ) != _canonical_json(effective_input):
            raise ToolInvocationConflict("待执行工具与已审批内容不一致，已阻止执行")

        if invocation.status not in {
            ToolInvocationStatus.PENDING,
            ToolInvocationStatus.APPROVED,
        }:
            db.commit()
            return _claim_snapshot(invocation, should_execute=False)

        expected_status = invocation.status
        now = datetime.utcnow()
        claim_result = db.execute(
            update(ToolInvocation)
            .where(
                ToolInvocation.id == invocation.id,
                ToolInvocation.user_id == user_id,
                ToolInvocation.status == expected_status,
            )
            .values(
                status=ToolInvocationStatus.RUNNING,
                attempt_count=ToolInvocation.attempt_count + 1,
                started_at=now,
                updated_at=now,
            )
        )
        if claim_result.rowcount == 1:
            db.commit()
            invocation = db.get(ToolInvocation, invocation.id)
            if invocation is None:
                raise RuntimeError("工具调用状态在抢占后丢失")
            return _claim_snapshot(invocation, should_execute=True)
        db.rollback()
    except Exception:
        db.rollback()
        raise

    idempotency_key = invocation_idempotency_key(user_id, thread_id, tool_call_id)
    invocation = db.scalar(
        select(ToolInvocation).where(
            ToolInvocation.user_id == user_id,
            ToolInvocation.idempotency_key == idempotency_key,
        )
    )
    if invocation is None:
        raise RuntimeError("工具调用状态在并发抢占后丢失")
    return _claim_snapshot(invocation, should_execute=False)


def serialize_tool_result(result: object) -> JsonObject:
    content: JsonValue = safe_json(
        getattr(result, "content", result),
        max_length=TOOL_STATE_PAYLOAD_MAX_CHARS,
    )
    status = str(getattr(result, "status", "success") or "success")
    return {
        "content": content,
        "status": status,
        "name": str(getattr(result, "name", "") or ""),
    }


def complete_tool_invocation(
    db: Session,
    *,
    claim: ToolInvocationClaim,
    result: object,
    error_message: str | None,
) -> None:
    now = datetime.utcnow()
    final_status = (
        ToolInvocationStatus.FAILED if error_message else ToolInvocationStatus.SUCCEEDED
    )
    db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == claim.invocation_id,
            ToolInvocation.status == ToolInvocationStatus.RUNNING,
        )
        .values(
            status=final_status,
            output=serialize_tool_result(result),
            error_message=error_message,
            completed_at=now,
            updated_at=now,
        )
    )


def fail_tool_invocation(
    db: Session,
    *,
    claim: ToolInvocationClaim,
    error_message: str,
) -> None:
    now = datetime.utcnow()
    db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == claim.invocation_id,
            ToolInvocation.status == ToolInvocationStatus.RUNNING,
        )
        .values(
            status=ToolInvocationStatus.FAILED,
            error_message=error_message,
            completed_at=now,
            updated_at=now,
        )
    )
