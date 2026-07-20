from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.core.types import ChatMessagePayload, ChatRole


class ChatMessage(BaseModel):
    role: ChatRole
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
            raise ValueError("请提供消息内容")
        return self

    def normalized_messages(self) -> list[ChatMessagePayload]:
        messages = [
            ChatMessagePayload(role=message.role, content=message.content)
            for message in self.messages
        ]
        if self.message:
            messages.append(
                ChatMessagePayload(role=ChatRole.USER, content=self.message)
            )
        return messages


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)
    document_ids: list[str] | None = None
