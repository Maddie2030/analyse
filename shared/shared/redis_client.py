import redis.asyncio as aioredis

from .config import settings

_redis_pool: aioredis.ConnectionPool | None = None


def init_redis_pool() -> None:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            retry_on_error=[aioredis.ConnectionError, aioredis.TimeoutError],
            health_check_interval=30,
        )


async def close_redis_pool() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


async def get_redis() -> aioredis.Redis:
    if _redis_pool is None:
        init_redis_pool()
    return aioredis.Redis(connection_pool=_redis_pool)
