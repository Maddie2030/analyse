from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.infrastructure.passwords import PasswordService
from app.infrastructure.sessions import SessionService
from app.infrastructure.user_repository import UserRepository
from app.schemas.auth import UserProfileUpdateRequest, UserRegisterRequest, UserResponse


class AuthApplicationService:
    def __init__(
        self,
        users: UserRepository,
        passwords: PasswordService,
        sessions: SessionService,
    ) -> None:
        self.users = users
        self.passwords = passwords
        self.sessions = sessions

    @staticmethod
    def to_response(user) -> UserResponse:
        return UserResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
            avatar_key=getattr(user, "avatar_key", "skull") or "skull",
            created_at=user.created_at,
        )

    async def register(self, body: UserRegisterRequest) -> tuple[UserResponse, str]:
        if await self.users.by_username(body.username):
            raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken.")
        if await self.users.by_email(body.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered.")

        # Argon2 is deliberately expensive; run it on the service's bounded
        # executor so concurrent registrations do not stall the ASGI event loop.
        password_hash = await self.passwords.hash_async(body.password)
        try:
            user = await self.users.create(
                username=body.username,
                email=body.email,
                password_hash=password_hash,
            )
            # The user must be durable before creating an external Redis session.
            # Otherwise a later DB commit failure can leave a valid session that
            # points to a user row that never committed.
            await self.users.commit()
        except IntegrityError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Username or email is already registered.",
            ) from exc

        session_id = await self.sessions.create(
            user_id=str(user.id),
            username=user.username,
            role=user.role,
        )
        return self.to_response(user), session_id

    async def login(self, identifier: str, password: str) -> tuple[UserResponse, str]:
        user = await self.users.by_username_or_email(identifier)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")
        if not await self.passwords.verify_async(password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated.")

        session_id = await self.sessions.create(
            user_id=str(user.id),
            username=user.username,
            role=user.role,
        )
        return self.to_response(user), session_id

    async def profile(self, user_id: str) -> UserResponse:
        user = await self.users.by_id(user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
        return self.to_response(user)

    async def update_profile(
        self, user_id: str, body: UserProfileUpdateRequest
    ) -> UserResponse:
        user = await self.users.by_id(user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

        if body.username is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Username is a locked account identifier and cannot be changed from profile settings.",
            )

        if body.avatar_key is not None:
            user.avatar_key = body.avatar_key

        if body.email is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Email is a locked account identifier and cannot be changed from profile settings.",
            )

        user = await self.users.save(user)
        return self.to_response(user)
