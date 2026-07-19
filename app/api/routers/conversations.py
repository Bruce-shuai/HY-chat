from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.models import Conversation, User
from app.db.session import get_db
from app.models.catalog import resolve_model
from app.schemas.conversation import ConversationCreate, ConversationUpdate

router = APIRouter(prefix="/conversations", tags=["conversations"])


def serialize_conversation(row: Conversation) -> dict[str, object]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "title": row.title,
        "selected_model": row.selected_model,
        "is_archived": row.is_archived,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _owned(db: Session, user_id: str, conversation_id: str) -> Conversation:
    row = db.get(Conversation, conversation_id)
    if not row or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


def _owned_by_thread(db: Session, user_id: str, thread_id: str) -> Conversation:
    row = db.scalar(
        select(Conversation).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == user_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    return row


def _apply_update(
    row: Conversation,
    request: ConversationUpdate,
    user: User,
) -> None:
    values = request.model_dump(exclude_unset=True)
    if values.get("selected_model"):
        try:
            values["selected_model"] = resolve_model(values["selected_model"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if values["selected_model"] not in (user.policy.allowed_models or []):
            raise HTTPException(status_code=403, detail="当前账号无权使用该模型")
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()


@router.post("", status_code=201)
def create_conversation(
    request: ConversationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        selected = resolve_model(request.selected_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if selected not in (user.policy.allowed_models or []):
        raise HTTPException(status_code=403, detail="当前账号无权使用该模型")
    row = Conversation(
        user_id=user.id,
        thread_id=str(uuid.uuid4()),
        title=request.title,
        selected_model=selected,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_conversation(row)


@router.get("")
def list_conversations(
    archived: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.is_archived == archived)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return {"conversations": [serialize_conversation(row) for row in rows]}


@router.patch("/by-thread/{thread_id}")
def update_conversation_by_thread(
    thread_id: str,
    request: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_by_thread(db, user.id, thread_id)
    _apply_update(row, request, user)
    db.commit()
    db.refresh(row)
    return serialize_conversation(row)


@router.delete("/by-thread/{thread_id}")
def delete_conversation_by_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned_by_thread(db, user.id, thread_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "thread_id": thread_id}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_conversation(_owned(db, user.id, conversation_id))


@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    request: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned(db, user.id, conversation_id)
    _apply_update(row, request, user)
    db.commit()
    db.refresh(row)
    return serialize_conversation(row)


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned(db, user.id, conversation_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}
