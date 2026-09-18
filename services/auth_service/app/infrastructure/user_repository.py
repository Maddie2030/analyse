import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def by_username(self, username: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def by_id(self, user_id: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        return result.scalar_one_or_none()

    async def by_username_or_email(self, identifier: str) -> User | None:
        result = await self.db.execute(
            select(User).where(
                or_(
                    User.username == identifier,
                    User.email == identifier.lower(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        role: str = "user",
    ) -> User:
        user = User(
            username=username,
            email=email.lower(),
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def save(self, user: User) -> User:
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def commit(self) -> None:
        await self.db.commit()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count(User.id)))
        return int(result.scalar_one())
