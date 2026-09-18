import asyncio
from concurrent.futures import ThreadPoolExecutor

from shared import hash_password, verify_password

# Argon2 is intentionally CPU/memory expensive. Keep it off the FastAPI event
# loop and bound concurrency so a login burst cannot create dozens of competing
# hash jobs on the small Docker Desktop host.
_PASSWORD_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="argon2")


class PasswordService:
    @staticmethod
    def hash(password: str) -> str:
        return hash_password(password)

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        return verify_password(password, password_hash)

    @staticmethod
    async def hash_async(password: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_PASSWORD_EXECUTOR, hash_password, password)

    @staticmethod
    async def verify_async(password: str, password_hash: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _PASSWORD_EXECUTOR, verify_password, password, password_hash
        )
