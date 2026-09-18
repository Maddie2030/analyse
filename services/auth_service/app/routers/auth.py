import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth_service import AuthApplicationService
from app.infrastructure.cookies import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    set_session_cookie,
)
from app.infrastructure.passwords import PasswordService
from app.infrastructure.rate_limits import AuthRateLimiter
from app.infrastructure.sessions import SessionService
from app.infrastructure.user_repository import UserRepository
from app.schemas.auth import (
    AdminStatsResponse,
    UserLoginRequest,
    UserProfileUpdateRequest,
    UserRegisterRequest,
    UserResponse,
)
from shared import (
    get_current_user,
    get_db,
    get_redis,
    require_admin,
    require_user,
    verify_turnstile,
)

router = APIRouter(tags=["auth"])


def _application(db: AsyncSession, redis: aioredis.Redis) -> AuthApplicationService:
    return AuthApplicationService(
        users=UserRepository(db),
        passwords=PasswordService(),
        sessions=SessionService(redis),
    )


async def _protect_auth_action(
    *, redis: aioredis.Redis, request: Request, action: str, turnstile_token: str
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if await AuthRateLimiter(redis).is_limited(action, client_ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests. Please try again later.",
        )

    remote_ip = request.client.host if request.client else None
    if not await verify_turnstile(turnstile_token, remote_ip):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Turnstile verification failed.",
        )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> UserResponse:
    await _protect_auth_action(
        redis=redis,
        request=request,
        action="register",
        turnstile_token=body.turnstile_token,
    )
    result, session_id = await _application(db, redis).register(body)
    set_session_cookie(response, session_id)
    return result


@router.post("/login", response_model=UserResponse)
async def login(
    body: UserLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> UserResponse:
    await _protect_auth_action(
        redis=redis,
        request=request,
        action="login",
        turnstile_token=body.turnstile_token,
    )
    result, session_id = await _application(db, redis).login(
        body.username_or_email,
        body.password,
    )
    set_session_cookie(response, session_id)
    return result


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    redis: aioredis.Redis = Depends(get_redis),
) -> dict:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        await SessionService(redis).delete(session_id)
    clear_session_cookie(response)
    return {"message": "Logged out"}


@router.get("/profile", response_model=UserResponse)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> UserResponse:
    return await _application(db, redis).profile(current_user["user_id"])


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    body: UserProfileUpdateRequest,
    current_user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> UserResponse:
    return await _application(db, redis).update_profile(current_user["user_id"], body)


@router.get("/admin/stats", response_model=AdminStatsResponse)
async def admin_stats(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminStatsResponse:
    return AdminStatsResponse(user_count=await UserRepository(db).count())
