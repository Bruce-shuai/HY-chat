from app.cache.service import cache, redis

redis_client = redis


def ping_redis() -> bool:
    return cache.ping()
