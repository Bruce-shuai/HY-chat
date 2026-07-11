from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal, TypedDict, cast

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User, UserPolicy

settings = get_settings()
password_hash = PasswordHash.recommended()


class AuthenticationError(ValueError):
    pass


class TokenPayload(TypedDict):
    sub: str
    type: str
    ver: int
    role: str
    iat: int
    exp: int
    jti: str


def _next_quota_reset(now: datetime | None = None) -> datetime:
    current = now or datetime.utcnow()
    if current.month == 12:
        return datetime(current.year + 1, 1, 1)
    return datetime(current.year, current.month + 1, 1)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_user(db: Session, email: str, password: str, display_name: str) -> User:
    normalized_email = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise ValueError("该邮箱已经注册")

    is_first_user = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    user = User(
        email=normalized_email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role="admin" if is_first_user else "user",
    )
    user.policy = UserPolicy(
        allowed_models=settings.available_chat_models,
        rpm_limit=settings.default_rpm_limit,
        monthly_token_quota=settings.default_monthly_token_quota,
        tokens_used=0,
        quota_reset_at=_next_quota_reset(),
        allow_image_generation=settings.default_allow_image_generation,
        allow_high_cost_tools=settings.default_allow_high_cost_tools,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("该邮箱已经注册") from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        raise AuthenticationError("邮箱或密码不正确")
    if not user.is_active:
        raise AuthenticationError("账号已被停用")
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def create_token(user: User, token_type: Literal["access", "refresh"]) -> str:
    now = datetime.utcnow()
    expires = now + (
        timedelta(minutes=settings.jwt_access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.jwt_refresh_token_days)
    )
    payload = {
        "sub": user.id,
        "type": token_type,
        "ver": user.token_version,
        "role": user.role,
        "iat": now,
        "exp": expires,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str, expected_type: str | None = None) -> TokenPayload:
    try:
        payload = cast(
            TokenPayload,
            jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"require": ["sub", "type", "ver", "exp"]},
            ),
        )
    except InvalidTokenError as exc:
        raise AuthenticationError("登录凭证无效或已过期") from exc
    if expected_type and payload.get("type") != expected_type:
        raise AuthenticationError("登录凭证类型不正确")
    return payload


def user_from_token(db: Session, token: str, expected_type: str = "access") -> User:
    payload = decode_token(token, expected_type)
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise AuthenticationError("用户不存在或已被停用")
    if user.token_version != int(payload.get("ver", -1)):
        raise AuthenticationError("登录凭证已失效，请重新登录")
    return user


def token_pair(user: User) -> dict[str, str | int]:
    return {
        "access_token": create_token(user, "access"),
        "refresh_token": create_token(user, "refresh"),
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_minutes * 60,
    }
