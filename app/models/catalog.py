from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.types import JsonObject

settings = get_settings()


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    is_default: bool
    supports_streaming: bool = True
    supports_tools: bool = True

    def to_dict(self) -> JsonObject:
        return asdict(self)


def list_models() -> list[ModelInfo]:
    return [
        ModelInfo(
            id=model_id,
            label=model_id,
            provider="zhipu",
            is_default=model_id == settings.zhipu_chat_model,
        )
        for model_id in settings.available_chat_models
    ]


def resolve_model(model_id: str | None) -> str:
    selected = model_id or settings.zhipu_chat_model
    if selected not in settings.available_chat_models:
        allowed = ", ".join(settings.available_chat_models)
        raise ValueError(f"Unsupported model '{selected}'. Available models: {allowed}")
    return selected


@lru_cache(maxsize=16)
def get_chat_model(model_id: str | None = None, streaming: bool = True) -> ChatOpenAI:
    selected = resolve_model(model_id)
    return ChatOpenAI(
        model=selected,
        api_key=settings.zhipu_api_key,
        base_url=settings.zhipu_base_url,
        temperature=0.2,
        streaming=streaming,
    )
