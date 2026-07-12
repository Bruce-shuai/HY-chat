from __future__ import annotations

from enum import Enum
from typing import TypeAlias, TypedDict

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessagePayload(TypedDict):
    role: ChatRole
    content: str
