from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.domain.validators import validate_password, validate_username

AVATAR_KEYS = {"skull", "bard", "cleric", "fire_wielder", "king", "paladin", "shadow_rogue", "sorcerer", "swordsman"}


class UserRegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    turnstile_token: str = ""

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        return validate_password(value)


class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str
    turnstile_token: str = ""


class UserProfileUpdateRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    avatar_key: str | None = None

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_username(value)

    @field_validator("avatar_key")
    @classmethod
    def check_avatar_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in AVATAR_KEYS:
            raise ValueError("Invalid avatar selection.")
        return value


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    avatar_key: str = "skull"
    created_at: datetime


class AdminStatsResponse(BaseModel):
    user_count: int
