from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.types import UserRole
from app.db.models import TraceSpan, User
from app.db.session import get_db
from app.tracing.service import serialize_span

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("")
def list_traces(
    conversation_id: str | None = None,
    span_type: str | None = Query(default=None, pattern="^(model|tool)$"),
    status: str | None = Query(default=None, pattern="^(running|success|error)$"),
    all_users: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(TraceSpan)
    if not (all_users and user.role == UserRole.ADMIN):
        statement = statement.where(TraceSpan.user_id == user.id)
    if conversation_id:
        statement = statement.where(TraceSpan.conversation_id == conversation_id)
    if span_type:
        statement = statement.where(TraceSpan.span_type == span_type)
    if status:
        statement = statement.where(TraceSpan.status == status)
    rows = db.scalars(
        statement.order_by(TraceSpan.started_at.desc()).offset(offset).limit(limit)
    ).all()
    return {"traces": [serialize_span(row, include_payload=False) for row in rows]}


@router.get("/{trace_id}")
def get_trace(
    trace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(TraceSpan, trace_id)
    if not row or (row.user_id != user.id and user.role != UserRole.ADMIN):
        raise HTTPException(status_code=404, detail="Trace 不存在")
    return serialize_span(row, include_payload=True)
