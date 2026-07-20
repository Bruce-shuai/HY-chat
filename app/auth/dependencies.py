from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.errors import bearer_unauthorized_details
from app.auth.service import AuthenticationError, user_from_token
from app.auth.types import TokenType
from app.core.admin_contact import append_admin_contact
from app.core.types import UserRole
from app.db.models import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def bearer_unauthorized(detail: str = "请先登录") -> HTTPException:
    return HTTPException(**bearer_unauthorized_details(detail))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise bearer_unauthorized()
    try:
        return user_from_token(
            db, credentials.credentials, expected_type=TokenType.ACCESS
        )
    except AuthenticationError as exc:
        raise bearer_unauthorized(str(exc)) from exc


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=append_admin_contact("需要管理员权限。"),
        )
    return user
