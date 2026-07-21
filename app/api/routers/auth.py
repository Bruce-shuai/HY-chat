from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.serializers import serialize_user
from app.auth.service import (
    AuthenticationError,
    authenticate_user,
    change_user_password,
    create_password_reset_issue,
    create_user,
    reset_password_with_token,
    token_pair,
    user_from_token,
)
from app.auth.types import TokenType
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
from app.services.email_service import (
    password_reset_email_configured,
    send_password_reset_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _token_response(user: User) -> dict[str, object]:
    return {**token_pair(user), "user": serialize_user(user)}


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = create_user(db, request.email, request.password, request.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _token_response(user)


@router.post("/login", response_model=TokenPair)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate_user(db, request.email, request.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _token_response(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(request: RefreshRequest, db: Session = Depends(get_db)):
    try:
        user = user_from_token(
            db, request.refresh_token, expected_type=TokenType.REFRESH
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _token_response(user)


@router.post("/password/change", response_model=TokenPair)
def change_password(
    request: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        updated_user = change_user_password(
            db,
            user,
            request.current_password,
            request.new_password,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _token_response(updated_user)


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
def request_password_reset(
    request: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    issue = create_password_reset_issue(db, request.email)
    if issue and password_reset_email_configured():
        background_tasks.add_task(
            send_password_reset_email,
            to_email=issue.email,
            display_name=issue.display_name,
            reset_token=issue.token,
        )
    return {
        "status": "ok",
        "email_configured": password_reset_email_configured(),
        "reset_token": issue.token
        if issue and settings.can_expose_password_reset_token
        else None,
    }


@router.post("/password-reset/confirm", response_model=TokenPair)
def confirm_password_reset(
    request: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
):
    try:
        user = reset_password_with_token(db, request.token, request.new_password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _token_response(user)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return serialize_user(user)


@router.post("/logout-all")
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    return {"status": "ok"}
