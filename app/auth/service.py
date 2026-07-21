from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict, cast

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.types import TokenType
from app.core.config import get_settings
from app.core.types import UserRole
from app.db.models import PasswordResetToken, User, UserPolicy

settings = get_settings()
password_hash = PasswordHash.recommended()
logger = logging.getLogger(__name__)


class AuthenticationError(ValueError):
    pass


class TokenPayload(TypedDict):
    sub: str
    type: str
    ver: int
    role: UserRole
    iat: int
    exp: int
    jti: str


@dataclass(frozen=True)
class PasswordResetIssue:
    user_id: str
    email: str
    display_name: str
    token: str


def _next_quota_reset(now: datetime | None = None) -> datetime:
    current = now or datetime.utcnow()
    if current.month == 12:
        return datetime(current.year + 1, 1, 1)
    return datetime(current.year, current.month + 1, 1)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _should_bootstrap_admin(db: Session, normalized_email: str) -> bool:
    """Choose the first administrator without exposing production to a race to register."""

    configured_email = settings.initial_admin_email.strip().lower()
    if configured_email:
        admin_count = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN)
            )
            or 0
        )
        return admin_count == 0 and normalized_email == configured_email
    return (db.scalar(select(func.count()).select_from(User)) or 0) == 0


def create_user(db: Session, email: str, password: str, display_name: str) -> User:
    normalized_email = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise ValueError("该邮箱已经注册")

    is_bootstrap_admin = _should_bootstrap_admin(db, normalized_email)
    user = User(
        email=normalized_email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=UserRole.ADMIN if is_bootstrap_admin else UserRole.USER,
    )
    user.policy = UserPolicy(
        allowed_models=settings.available_chat_models,
        rpm_limit=settings.default_rpm_limit,
        monthly_token_quota=settings.default_monthly_token_quota,
        tokens_used=0,
        quota_reset_at=_next_quota_reset(),
        allow_high_cost_tools=settings.default_allow_high_cost_tools,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("该邮箱已经注册") from exc
    db.refresh(user)
    logger.info("User registered user_id=%s role=%s", user.id, user.role.value)
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
    logger.info("User authenticated user_id=%s role=%s", user.id, user.role.value)
    return user


def change_user_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
) -> User:
    if not verify_password(current_password, user.password_hash):
        raise AuthenticationError("当前密码不正确")
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    logger.info("User password changed user_id=%s", user.id)
    return user


def create_password_reset_issue(
    db: Session,
    email: str,
) -> PasswordResetIssue | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not user.is_active:
        return None

    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=settings.password_reset_token_minutes)
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at <= now))
    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(token),
            expires_at=expires_at,
            created_at=now,
        )
    )
    db.commit()
    logger.info("Password reset requested user_id=%s", user.id)
    return PasswordResetIssue(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        token=token,
    )


def reset_password_with_token(db: Session, token: str, new_password: str) -> User:
    now = datetime.utcnow()
    reset_token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_reset_token(token.strip()),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if not reset_token:
        raise AuthenticationError("重置链接无效或已过期")

    user = db.get(User, reset_token.user_id)
    if not user or not user.is_active:
        raise AuthenticationError("用户不存在或已被停用")

    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.updated_at = now
    reset_token.used_at = now
    db.commit()
    db.refresh(user)
    logger.info("Password reset completed user_id=%s", user.id)
    return user


def create_token(user: User, token_type: TokenType) -> str:
    now = datetime.utcnow()
    expires = now + (
        timedelta(minutes=settings.jwt_access_token_minutes)
        if token_type is TokenType.ACCESS
        else timedelta(days=settings.jwt_refresh_token_days)
    )
    payload = {
        "sub": user.id,
        "type": token_type.value,
        "ver": user.token_version,
        "role": user.role,
        "iat": now,
        "exp": expires,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str, expected_type: TokenType | None = None) -> TokenPayload:
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
    if expected_type and payload.get("type") != expected_type.value:
        raise AuthenticationError("登录凭证类型不正确")
    return payload


def user_from_token(
    db: Session,
    token: str,
    expected_type: TokenType = TokenType.ACCESS,
) -> User:
    payload = decode_token(token, expected_type)
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise AuthenticationError("用户不存在或已被停用")
    if user.token_version != int(payload.get("ver", -1)):
        raise AuthenticationError("登录凭证已失效，请重新登录")
    return user


def token_pair(user: User) -> dict[str, str | int]:
    return {
        "access_token": create_token(user, TokenType.ACCESS),
        "refresh_token": create_token(user, TokenType.REFRESH),
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_minutes * 60,
    }
