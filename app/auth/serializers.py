from __future__ import annotations

from app.db.models import User, UserPolicy


def serialize_policy(policy: UserPolicy) -> dict[str, object]:
    return {
        "allowed_models": list(policy.allowed_models or []),
        "rpm_limit": policy.rpm_limit,
        "monthly_token_quota": policy.monthly_token_quota,
        "tokens_used": policy.tokens_used,
        "quota_reset_at": policy.quota_reset_at,
        "allow_image_generation": policy.allow_image_generation,
        "allow_high_cost_tools": policy.allow_high_cost_tools,
    }


def serialize_user(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "policy": serialize_policy(user.policy),
    }
