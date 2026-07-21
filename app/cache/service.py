from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import random
import time
from typing import cast
import uuid

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.types import JsonValue

settings = get_settings()
NEGATIVE_CACHE_MARKER = "__hy_chat_negative_cache__"


@dataclass(frozen=True)
class CacheLookup:
    hit: bool
    value: JsonValue | None = None
    is_negative: bool = False
    created: bool = False
    error: bool = False


@dataclass(frozen=True)
class CacheLock:
    key: str
    token: str


CacheProducer = Callable[[], JsonValue | None]
NegativePredicate = Callable[[JsonValue | None], bool]
CachePredicate = Callable[[JsonValue | None], bool]


class CacheService:
    """Small JSON cache facade that degrades gracefully when Redis is unavailable."""

    def __init__(self, client: Redis):
        self.client = client

    @staticmethod
    def digest(*parts: object) -> str:
        payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _negative_payload(value: JsonValue | None = None) -> JsonValue:
        return {
            NEGATIVE_CACHE_MARKER: True,
            "value": value,
        }

    @staticmethod
    def _unwrap_negative(value: JsonValue) -> CacheLookup | None:
        if (
            isinstance(value, dict)
            and value.get(NEGATIVE_CACHE_MARKER) is True
            and set(value).issubset({NEGATIVE_CACHE_MARKER, "value"})
        ):
            return CacheLookup(
                hit=True,
                value=value.get("value"),
                is_negative=True,
            )
        return None

    @staticmethod
    def _with_ttl_jitter(ttl: int) -> int:
        ttl = max(1, int(ttl))
        ratio = settings.cache_ttl_jitter_ratio
        if ratio <= 0:
            return ttl
        spread = int(ttl * ratio)
        if spread <= 0:
            return ttl
        return max(1, ttl + random.randint(-spread, spread))

    def get_json_lookup(self, key: str) -> CacheLookup:
        if not settings.cache_enabled:
            return CacheLookup(hit=False)
        try:
            value = self.client.get(key)
            if value is None:
                return CacheLookup(hit=False)
            parsed = cast(JsonValue, json.loads(value))
            if negative := self._unwrap_negative(parsed):
                return negative
            return CacheLookup(hit=True, value=parsed)
        except RedisError:
            return CacheLookup(hit=False, error=True)
        except json.JSONDecodeError:
            return CacheLookup(hit=False)

    def get_json(self, key: str) -> JsonValue | None:
        return self.get_json_lookup(key).value

    def set_json(self, key: str, value: JsonValue, ttl: int | None = None) -> bool:
        if not settings.cache_enabled:
            return False
        try:
            self.client.setex(
                key,
                self._with_ttl_jitter(ttl or settings.cache_default_ttl),
                json.dumps(value, ensure_ascii=False, default=str),
            )
            return True
        except RedisError:
            return False

    def set_negative_json(
        self,
        key: str,
        value: JsonValue | None = None,
        ttl: int | None = None,
    ) -> bool:
        return self.set_json(
            key,
            self._negative_payload(value),
            ttl=ttl or settings.cache_negative_ttl,
        )

    def _lock_key(self, key: str) -> str:
        return f"cache:lock:{self.digest(key)}"

    def acquire_lock(self, key: str, ttl: int | None = None) -> CacheLock | None:
        if not settings.cache_enabled:
            return None
        lock_key = self._lock_key(key)
        token = str(uuid.uuid4())
        try:
            acquired = self.client.set(
                lock_key,
                token,
                nx=True,
                ex=max(1, int(ttl or settings.cache_lock_ttl)),
            )
            return CacheLock(lock_key, token) if acquired else None
        except RedisError:
            return None

    def release_lock(self, lock: CacheLock | None) -> bool:
        if not lock or not settings.cache_enabled:
            return False
        try:
            return (
                int(
                    self.client.eval(
                        """
                        if redis.call("get", KEYS[1]) == ARGV[1] then
                            return redis.call("del", KEYS[1])
                        end
                        return 0
                        """,
                        1,
                        lock.key,
                        lock.token,
                    )
                )
                == 1
            )
        except RedisError:
            return False

    def wait_for_json(
        self,
        key: str,
        *,
        timeout: float | None = None,
        poll_interval: float | None = None,
    ) -> CacheLookup:
        if not settings.cache_enabled:
            return CacheLookup(hit=False)
        deadline = time.monotonic() + (
            settings.cache_lock_wait_seconds if timeout is None else timeout
        )
        poll = (
            settings.cache_lock_poll_seconds if poll_interval is None else poll_interval
        )
        while time.monotonic() < deadline:
            lookup = self.get_json_lookup(key)
            if lookup.hit:
                return lookup
            if lookup.error:
                return lookup
            time.sleep(max(0.001, poll))
        return CacheLookup(hit=False)

    def get_or_set_json(
        self,
        key: str,
        producer: CacheProducer,
        *,
        ttl: int | None = None,
        negative_ttl: int | None = None,
        should_cache_negative: NegativePredicate | None = None,
        should_cache: CachePredicate | None = None,
        lock_ttl: int | None = None,
        wait_timeout: float | None = None,
    ) -> CacheLookup:
        lookup = self.get_json_lookup(key)
        if lookup.hit:
            return lookup

        lock = self.acquire_lock(key, ttl=lock_ttl)
        if not lock:
            lookup = self.wait_for_json(key, timeout=wait_timeout)
            if lookup.hit:
                return lookup

        try:
            if lock:
                lookup = self.get_json_lookup(key)
                if lookup.hit:
                    return lookup

            value = producer()
            is_negative = bool(should_cache_negative and should_cache_negative(value))
            if is_negative:
                self.set_negative_json(key, value, ttl=negative_ttl)
            elif value is not None and (should_cache(value) if should_cache else True):
                self.set_json(key, value, ttl=ttl)
            return CacheLookup(
                hit=True,
                value=value,
                is_negative=is_negative,
                created=True,
            )
        finally:
            self.release_lock(lock)

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
