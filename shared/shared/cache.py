import json
import logging
from typing import Any

import redis.asyncio as aioredis

from .config import settings

log = logging.getLogger(__name__)

_CACHE_PREFIX = "cache:"


def _cache_key(scope: str, key: str) -> str:
    return f"{_CACHE_PREFIX}{scope}:{key}"


async def cache_get(
    redis: aioredis.Redis, scope: str, key: str
) -> Any | None:
    raw = await redis.get(_cache_key(scope, key))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def cache_set(
    redis: aioredis.Redis,
    scope: str,
    key: str,
    value: Any,
    ttl: int | None = None,
) -> None:
    if ttl is None:
        ttl = settings.CACHE_TTL_SERIES_LIST
    try:
        await redis.setex(_cache_key(scope, key), ttl, json.dumps(value, default=str))
    except Exception:
        log.warning("cache_set failed for %s:%s", scope, key, exc_info=True)


async def cache_delete(redis: aioredis.Redis, scope: str, key: str) -> None:
    await redis.delete(_cache_key(scope, key))


async def cache_invalidate_pattern(
    redis: aioredis.Redis, scope: str, pattern: str = "*"
) -> None:
    keys = await redis.keys(_cache_key(scope, pattern))
    if keys:
        await redis.delete(*keys)


async def cache_get_or_set(
    redis: aioredis.Redis,
    scope: str,
    key: str,
    factory: Any,
    ttl: int | None = None,
) -> Any:
    cached = await cache_get(redis, scope, key)
    if cached is not None:
        return cached
    value = await factory()
    if value is not None:
        await cache_set(redis, scope, key, value, ttl)
    return value
