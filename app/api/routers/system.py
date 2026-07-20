from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.serializers import serialize_policy
from app.cache.service import cache
from app.core.config import get_settings
from app.models.catalog import list_models, normalize_model_allowlist
from app.tools.registry import tool_manifest
from app.db.models import User
from app.core.types import UserRole
from app.policies.service import HIGH_COST_TOOLS, WORKSPACE_READ_TOOLS

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/models")
def get_models(user: User = Depends(get_current_user)):
    allowed_models = normalize_model_allowlist(user.policy.allowed_models)
    allowed = set(allowed_models)
    models = [model.to_dict() for model in list_models() if model.id in allowed]
    policy = serialize_policy(user.policy)
    policy["allowed_models"] = allowed_models
    return {
        "current_model": (
            settings.zhipu_chat_model
            if settings.zhipu_chat_model in allowed
            else (models[0]["id"] if models else None)
        ),
        "models": models,
        "policy": policy,
    }


@router.get("/tools")
def get_tools(user: User = Depends(get_current_user)):
    tools = []
    for item in tool_manifest():
        enabled = True
        if item["name"] in HIGH_COST_TOOLS:
            enabled = user.policy.allow_high_cost_tools
        elif item["name"] in WORKSPACE_READ_TOOLS:
            enabled = user.role == UserRole.ADMIN
        tools.append({**item, "enabled": enabled})
    return {"tools": tools}


@router.get("/cache/health")
def cache_health():
    return {
        "enabled": settings.cache_enabled,
        "available": cache.ping(),
        "backend": "redis",
        "default_ttl": settings.cache_default_ttl,
    }
