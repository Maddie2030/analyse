import redis.asyncio as aioredis

from shared import is_rate_limited


class AuthRateLimiter:
    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def is_limited(self, action: str, client_ip: str) -> bool:
        limited, _ = await is_rate_limited(
            self.redis,
            f"{action}:{client_ip}",
            limit=30,
            window_seconds=60,
        )
        return limited
