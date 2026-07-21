from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.core.types import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetRequestResponse(BaseModel):
    status: Literal["ok"] = "ok"
    email_configured: bool
    reset_token: str | None = None


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class UserPolicyResponse(BaseModel):
    allowed_models: list[str]
    rpm_limit: int
    monthly_token_quota: int
    tokens_used: int
    quota_reset_at: datetime
    allow_high_cost_tools: bool


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    policy: UserPolicyResponse


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None


class AdminPolicyUpdate(BaseModel):
    allowed_models: list[str] | None = None
    rpm_limit: int | None = Field(default=None, ge=1, le=10_000)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    tokens_used: int | None = Field(default=None, ge=0)
    allow_high_cost_tools: bool | None = None
