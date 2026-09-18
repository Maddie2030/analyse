import logging
from functools import lru_cache
from typing import Any

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from httpx import AsyncClient

from .config import settings
from .redis_client import get_redis
from .session import get_session

log = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _password_hasher():
    # Password hashing is used only by the auth service. Import lazily so
    # services that reuse authorization helpers do not need argon2 installed.
    from argon2 import PasswordHasher
    return PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher().verify(password_hash, password)
    except Exception:
        return False


async def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    if not settings.TURNSTILE_ENABLED:
        return True
    if not token:
        return False
    try:
        async with AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.TURNSTILE_SECRET,
                    "response": token,
                    "remoteip": remote_ip or "",
                },
            )
            return resp.json().get("success", False)
    except Exception:
        log.warning("Turnstile verification failed", exc_info=True)
        return False


async def get_current_user_optional(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> dict[str, Any] | None:
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = await get_session(redis, session_id)
    if session is None:
        return None
    return session


async def get_current_user(
    current_user: dict[str, Any] | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    if current_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return current_user


async def require_user(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not current_user.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    return current_user


async def require_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not current_user.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    if current_user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user
