from __future__ import annotations

from typing import TypedDict


class UnauthorizedDetails(TypedDict):
    status_code: int
    detail: str
    headers: dict[str, str]


def bearer_unauthorized_details(
    detail: str = "请先登录",
) -> UnauthorizedDetails:
    return {
        "status_code": 401,
        "detail": detail,
        "headers": {"WWW-Authenticate": "Bearer"},
    }
