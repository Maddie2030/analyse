import time

import redis.asyncio as aioredis

from .config import settings

RATE_LIMIT_PREFIX = "ratelimit:"

_SLIDING_WINDOW_LUA = """
local key     = KEYS[1]
local now     = tonumber(ARGV[1])
local window  = tonumber(ARGV[2])
local limit   = tonumber(ARGV[3])
local expire  = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now .. '-' .. math.random(1, 1000000))
    redis.call('EXPIRE', key, expire)
    return {0, count + 1}
end
return {1, count}
"""


def _key(identifier: str) -> str:
    return f"{RATE_LIMIT_PREFIX}{identifier}"


async def is_rate_limited(
    redis: aioredis.Redis,
    identifier: str,
    limit: int | None = None,
    window_seconds: int | None = None,
) -> tuple[bool, int]:
    effective_limit = limit if limit is not None else settings.RATE_LIMIT_REQUESTS
    effective_window = (
        window_seconds if window_seconds is not None
        else settings.RATE_LIMIT_WINDOW_SECONDS
    )
    now_ms = int(time.time() * 1000)
    result = await redis.eval(
        _SLIDING_WINDOW_LUA, 1, _key(identifier),
        now_ms, effective_window, effective_limit, effective_window + 1,
    )
    return bool(result[0]), int(result[1])
