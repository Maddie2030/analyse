import redis.asyncio as aioredis

from shared import create_session, delete_session


class SessionService:
    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def create(self, *, user_id: str, username: str, role: str) -> str:
        return await create_session(self.redis, user_id, username, role)

    async def delete(self, session_id: str) -> None:
        await delete_session(self.redis, session_id)
