from __future__ import annotations

import hashlib
import json
from typing import cast

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.types import JsonValue

settings = get_settings()


class CacheService:
    """Small JSON cache facade that degrades gracefully when Redis is unavailable."""

    def __init__(self, client: Redis):
        self.client = client

    @staticmethod
    def digest(*parts: object) -> str:
        payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_json(self, key: str) -> JsonValue | None:
        if not settings.cache_enabled:
            return None
        try:
            value = self.client.get(key)
            return cast(JsonValue, json.loads(value)) if value is not None else None
        except (RedisError, json.JSONDecodeError):
            return None

    def set_json(self, key: str, value: JsonValue, ttl: int | None = None) -> bool:
        if not settings.cache_enabled:
            return False
        try:
            self.client.setex(
                key,
                ttl or settings.cache_default_ttl,
                json.dumps(value, ensure_ascii=False, default=str),
            )
            return True
        except RedisError:
            return False

    def delete_pattern(self, pattern: str) -> int:
        if not settings.cache_enabled:
            return 0
        deleted = 0
        try:
            for key in self.client.scan_iter(match=pattern, count=200):
                deleted += int(self.client.delete(key))
        except RedisError:
            return deleted
        return deleted

    def ping(self) -> bool:
        if not settings.cache_enabled:
            return False
        try:
            return bool(self.client.ping())
        except RedisError:
            return False


redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)
cache = CacheService(redis)
