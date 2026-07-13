from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_admin
from app.auth.serializers import serialize_user
from app.core.config import get_settings
from app.core.types import UserRole
from app.db.models import Conversation, StoredFile, TraceSpan, User
from app.db.session import get_db
from app.schemas.auth import AdminPolicyUpdate, AdminUserUpdate
from app.storage.service import storage

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get("/stats")
def admin_stats(db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "active_users": db.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
        or 0,
        "conversations": db.scalar(select(func.count()).select_from(Conversation)) or 0,
        "files": db.scalar(select(func.count()).select_from(StoredFile)) or 0,
        "trace_spans": db.scalar(select(func.count()).select_from(TraceSpan)) or 0,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(
        select(User).options(selectinload(User.policy)).order_by(User.created_at.desc())
    ).all()
    return {"users": [serialize_user(user) for user in users]}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_admin.id:
        raise HTTPException(status_code=409, detail="不能删除当前登录账号")
    if user.role == UserRole.ADMIN:
        admin_count = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            )
            or 0
        )
        if user.is_active and admin_count <= 1:
            raise HTTPException(status_code=409, detail="不能删除最后一个管理员")

    object_keys = list(
        db.scalars(select(StoredFile.object_key).where(StoredFile.user_id == user.id))
    )
    db.delete(user)
    db.commit()
    logger.info(
        "Admin deleted user admin_id=%s user_id=%s stored_objects=%s",
        current_admin.id,
        user_id,
        len(object_keys),
    )

    for object_key in object_keys:
        try:
            storage.delete(object_key)
        except Exception:
            logger.warning(
                "Failed to delete stored object user_id=%s object_key=%s",
                user_id,
                object_key,
                exc_info=True,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/users/{user_id}")
def update_user(user_id: str, request: AdminUserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    values = request.model_dump(exclude_unset=True)
    if user.role == UserRole.ADMIN and (
        values.get("role") == UserRole.USER or values.get("is_active") is False
    ):
        admin_count = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            )
            or 0
        )
        if admin_count <= 1:
            raise HTTPException(status_code=409, detail="不能停用或降级最后一个管理员")
    for key, value in values.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.patch("/users/{user_id}/policy")
def update_policy(
    user_id: str, request: AdminPolicyUpdate, db: Session = Depends(get_db)
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    values = request.model_dump(exclude_unset=True)
    if "allowed_models" in values:
        invalid = set(values["allowed_models"]) - set(settings.available_chat_models)
        if invalid:
            raise HTTPException(
                status_code=400, detail=f"不支持的模型: {sorted(invalid)}"
            )
    for key, value in values.items():
        setattr(user.policy, key, value)
    db.commit()
    db.refresh(user)
    return serialize_user(user)
