from __future__ import annotations

from langgraph_sdk import Auth

from app.auth.errors import bearer_unauthorized_details
from app.auth.service import AuthenticationError, user_from_token
from app.db.init_db import init_db
from app.db.session import SessionLocal

init_db()
auth = Auth()


def langgraph_bearer_unauthorized(
    detail: str = "请先登录",
) -> Auth.exceptions.HTTPException:
    return Auth.exceptions.HTTPException(**bearer_unauthorized_details(detail))


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise langgraph_bearer_unauthorized()
    token = authorization.split(" ", 1)[1].strip()
    db = SessionLocal()
    try:
        user = user_from_token(db, token, expected_type="access")
        return {
            "identity": user.id,
            "display_name": user.display_name,
            "permissions": [user.role],
            "is_authenticated": True,
        }
    except AuthenticationError as exc:
        raise langgraph_bearer_unauthorized(str(exc)) from exc
    finally:
        db.close()


@auth.on.threads.create
async def create_thread(ctx: Auth.types.AuthContext, value: dict[str, object]):
    value.setdefault("metadata", {})["owner"] = ctx.user.identity


@auth.on.threads
async def scope_threads(
    ctx: Auth.types.AuthContext, value: object
) -> Auth.types.FilterType:
    return {"owner": ctx.user.identity}


@auth.on.store
async def scope_store(ctx: Auth.types.AuthContext, value: dict[str, object]):
    namespace = tuple(value.get("namespace") or ())
    if not namespace or namespace[0] != ctx.user.identity:
        value["namespace"] = (ctx.user.identity, *namespace)
