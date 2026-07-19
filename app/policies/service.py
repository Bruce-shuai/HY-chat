from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.cache.service import redis
from app.core.types import UserRole
from app.db.models import User, UserPolicy

HIGH_COST_TOOLS = {"web_search", "get_stock_quote"}
WORKSPACE_READ_TOOLS = {
    "list_workspace_files",
    "read_workspace_file",
    "search_workspace_code",
}


class PolicyViolation(PermissionError):
    pass


def runtime_user_id(runtime: object) -> str | None:
    server_info = getattr(runtime, "server_info", None)
    user = getattr(server_info, "user", None)
    if isinstance(user, Mapping):
        return str(user.get("identity")) if user.get("identity") else None
    identity = getattr(user, "identity", None)
    if identity:
        return str(identity)
    state = getattr(runtime, "state", None)
    if isinstance(state, Mapping) and state.get("auth_user_id"):
        return str(state["auth_user_id"])
    return None


def get_policy(db: Session, user_id: str) -> UserPolicy:
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise PolicyViolation("账号不存在或已被停用")
    policy = user.policy
    now = datetime.utcnow()
    if policy.quota_reset_at <= now:
        policy.tokens_used = 0
        policy.quota_reset_at = (
            datetime(now.year + 1, 1, 1)
            if now.month == 12
            else datetime(now.year, now.month + 1, 1)
        )
        db.commit()
    return policy


def authorize_model_access(db: Session, user_id: str, model_name: str) -> UserPolicy:
    """Validate durable model permissions without consuming an RPM slot."""

    policy = get_policy(db, user_id)
    if model_name not in (policy.allowed_models or []):
        raise PolicyViolation(f"当前账号无权使用模型 {model_name}")
    if (
        policy.monthly_token_quota >= 0
        and policy.tokens_used >= policy.monthly_token_quota
    ):
        raise PolicyViolation("本月 Token 配额已用尽")
    return policy


def enforce_model(db: Session, user_id: str, model_name: str) -> UserPolicy:
    policy = authorize_model_access(db, user_id, model_name)

    minute = datetime.utcnow().strftime("%Y%m%d%H%M")
    key = f"policy:rpm:{user_id}:{minute}"
    try:
        count = int(redis.incr(key))
        if count == 1:
            redis.expire(key, 120)
        if count > policy.rpm_limit:
            raise PolicyViolation(f"请求过于频繁：每分钟最多 {policy.rpm_limit} 次")
    except RedisError:
        # Redis 故障不应让整个聊天服务不可用；Token 与模型权限仍由数据库强制执行。
        pass
    return policy


def record_token_usage(db: Session, user_id: str, total_tokens: int) -> None:
    if total_tokens <= 0:
        return
    get_policy(db, user_id)
    db.execute(
        update(UserPolicy)
        .where(UserPolicy.user_id == user_id)
        .values(tokens_used=UserPolicy.tokens_used + total_tokens)
    )
    db.commit()


def enforce_workspace_access(db: Session, user_id: str) -> None:
    """Restrict the shared server workspace to active administrators."""

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise PolicyViolation("账号不存在或已被停用")
    if user.role != UserRole.ADMIN:
        raise PolicyViolation("工作区仅限管理员访问")


def enforce_tool(db: Session, user_id: str, tool_name: str) -> None:
    if tool_name in WORKSPACE_READ_TOOLS:
        enforce_workspace_access(db, user_id)
        return

    policy = get_policy(db, user_id)
    if tool_name in HIGH_COST_TOOLS and not policy.allow_high_cost_tools:
        raise PolicyViolation(f"当前账号不允许调用高成本工具 {tool_name}")
