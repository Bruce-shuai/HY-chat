from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    message: str | None = Field(
        default=None, description="Convenience field for one user message"
    )
    messages: list[ChatMessage] = Field(default_factory=list)
    model: str | None = None
    use_cache: bool = True
    conversation_id: str | None = None
    thread_id: str | None = None

    @model_validator(mode="after")
    def validate_input(self):
        if not self.message and not self.messages:
            raise ValueError("message or messages is required")
        return self

    def normalized_messages(self) -> list[dict[str, str]]:
        messages = [message.model_dump() for message in self.messages]
        if self.message:
            messages.append({"role": "user", "content": self.message})
        return messages


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)
    document_ids: list[str] | None = None
