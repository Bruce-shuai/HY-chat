from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.serializers import serialize_user
from app.auth.service import (
    AuthenticationError,
    authenticate_user,
    create_user,
    token_pair,
    user_from_token,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


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
        user = user_from_token(db, request.refresh_token, expected_type="refresh")
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
