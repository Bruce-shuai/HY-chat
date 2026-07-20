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
    tier: str
    description: str
    quality_rank: int
    supports_streaming: bool = True
    supports_tools: bool = True

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class ModelProfile:
    label: str
    tier: str
    description: str
    quality_rank: int


MODEL_PROFILES: dict[str, ModelProfile] = {
    "glm-5.2": ModelProfile(
        label="GLM-5.2（旗舰，推荐）",
        tier="旗舰",
        description="复杂推理、工具调用、联网搜索和长任务优先使用。",
        quality_rank=10,
    ),
    "glm-5.1": ModelProfile(
        label="GLM-5.1（高性能）",
        tier="高性能",
        description="适合复杂对话、代码理解和较长链路任务。",
        quality_rank=20,
    ),
    "glm-5-turbo": ModelProfile(
        label="GLM-5-Turbo（工具增强）",
        tier="工具增强",
        description="适合工具调用、联网搜索和需要较快响应的日常任务。",
        quality_rank=30,
    ),
}

LEGACY_MODEL_IDS = frozenset(
    {
        "glm-5",
        "glm-4.6",
        "glm-4.5",
        "glm-4-plus",
        "glm-4-flash",
    }
)


def normalize_model_allowlist(model_ids: list[str] | None) -> list[str]:
    if not model_ids:
        return []

    requested = list(
        dict.fromkeys(model.strip() for model in model_ids if model.strip())
    )
    available = settings.available_chat_models
    available_set = set(available)
    has_legacy_model = any(model in LEGACY_MODEL_IDS for model in requested)

    if has_legacy_model:
        return available

    return [model for model in requested if model in available_set]


def get_model_profile(model_id: str) -> ModelProfile:
    return MODEL_PROFILES.get(
        model_id,
        ModelProfile(
            label=f"{model_id}（自定义）",
            tier="自定义",
            description="自定义智谱模型，请确认能力、成本和工具调用表现后再开放给用户。",
            quality_rank=100,
        ),
    )


def list_models() -> list[ModelInfo]:
    models = sorted(
        settings.available_chat_models,
        key=lambda model_id: (get_model_profile(model_id).quality_rank, model_id),
    )
    return [
        ModelInfo(
            id=model_id,
            label=profile.label,
            provider="zhipu",
            is_default=model_id == settings.zhipu_chat_model,
            tier=profile.tier,
            description=profile.description,
            quality_rank=profile.quality_rank,
        )
        for model_id in models
        for profile in [get_model_profile(model_id)]
    ]


def resolve_model(model_id: str | None) -> str:
    selected = model_id or settings.zhipu_chat_model
    if selected not in settings.available_chat_models:
        allowed = ", ".join(settings.available_chat_models)
        raise ValueError(f"不支持模型 {selected}。可用模型：{allowed}")
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
