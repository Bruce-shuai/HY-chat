from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=240)
    selected_model: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    selected_model: str | None = None
    is_archived: bool | None = None
