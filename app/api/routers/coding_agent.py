from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.graph import run_agent_graph
from app.auth.dependencies import get_current_user, require_admin
from app.core.config import get_settings
from app.core.types import UserRole
from app.db.models import AgentRun, ModelCall, ToolCall, User
from app.db.session import get_db
from app.policies.service import enforce_model
from app.schemas.agent import (
    AgentRunDetail,
    AgentRunRequest,
    AgentRunResponse,
    AgentRunSummary,
    ModelCallSummary,
    ToolCallSummary,
)
from app.services.redis_client import redis_client
from app.tools.file_tools import safe_path

router = APIRouter(
    prefix="/coding-agent",
    tags=["coding-agent"],
    dependencies=[Depends(require_admin)],
)
settings = get_settings()
logger = logging.getLogger(__name__)


def _set_cached_run_status(status_key: str, status: str) -> None:
    """Keep Redis status best-effort; PostgreSQL remains the source of truth."""

    try:
        redis_client.setex(
            status_key,
            settings.agent_run_status_ttl_seconds,
            status,
        )
    except RedisError:
        logger.warning(
            "Coding Agent status cache unavailable key=%s status=%s",
            status_key,
            status,
            exc_info=True,
        )


@router.post("/runs", response_model=AgentRunResponse, status_code=201)
def create_coding_agent_run(
    request: AgentRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = str(safe_path(request.workspace or settings.workspace_root))
    selected_model = request.model or settings.zhipu_chat_model
    try:
        enforce_model(db, user.id, selected_model)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    run = AgentRun(
        user_id=user.id,
        task=request.task,
        workspace=workspace,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    status_key = f"coding_agent_run:{run.id}:status"
    _set_cached_run_status(status_key, "running")

    try:
        output = run_agent_graph(
            db=db,
            run_id=run.id,
            task=request.task,
            workspace=workspace,
            model=request.model,
        )
        run.status = "success"
        run.final_output = output
        db.commit()
        _set_cached_run_status(status_key, "success")
        return AgentRunResponse(run_id=run.id, status="success", output=output)
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        db.commit()
        _set_cached_run_status(status_key, "failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/runs", response_model=list[AgentRunSummary])
def list_coding_agent_runs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentRunSummary]:
    statement = select(AgentRun)
    if user.role != UserRole.ADMIN:
        statement = statement.where(AgentRun.user_id == user.id)
    rows = db.scalars(
        statement.order_by(AgentRun.created_at.desc()).limit(
            settings.agent_run_list_limit
        )
    ).all()
    return [
        AgentRunSummary(
            id=row.id,
            task=row.task,
            workspace=row.workspace,
            status=row.status,
            final_output=row.final_output,
            error_message=row.error_message,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_coding_agent_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentRunDetail:
    run = db.get(AgentRun, run_id)
    if not run or (run.user_id != user.id and user.role != UserRole.ADMIN):
        raise HTTPException(status_code=404, detail="代码智能体运行记录不存在")
    tools = db.scalars(
        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.id.asc())
    ).all()
    models = db.scalars(
        select(ModelCall).where(ModelCall.run_id == run_id).order_by(ModelCall.id.asc())
    ).all()
    return AgentRunDetail(
        id=run.id,
        task=run.task,
        workspace=run.workspace,
        status=run.status,
        final_output=run.final_output,
        error_message=run.error_message,
        created_at=run.created_at,
        tool_calls=[
            ToolCallSummary(
                tool_name=call.tool_name,
                input=call.input,
                output=call.output,
                status=call.status,
                created_at=call.created_at,
            )
            for call in tools
        ],
        model_calls=[
            ModelCallSummary(
                provider=call.provider,
                model_name=call.model_name,
                status=call.status,
                latency_ms=call.latency_ms,
                created_at=call.created_at,
            )
            for call in models
        ],
    )
