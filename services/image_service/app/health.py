import asyncio
from typing import Any

import httpx
from sqlalchemy import text

from shared import AsyncSessionLocal, get_redis, settings
from app.rabbitmq import get_broker


async def _check_postgres() -> dict[str, Any]:
    try:
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(
                db.execute(text("SELECT 1")),
                timeout=3.0,
            )
        return {"ok": True}
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
        }


async def _check_valkey() -> dict[str, Any]:
    try:
        redis = await get_redis()
        await asyncio.wait_for(redis.ping(), timeout=3.0)
        return {"ok": True}
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
        }


async def _check_seaweedfs() -> dict[str, Any]:
    filer_url = str(settings.SEAWEEDFS_FILER_URL).rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{filer_url}/")

        # Filer may return 200 or redirect depending on version/config.
        ok = 200 <= response.status_code < 400

        return {
            "ok": ok,
            "status_code": response.status_code,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
        }


async def _check_rabbitmq() -> dict[str, Any]:
    try:
        await asyncio.wait_for(get_broker().ping(), timeout=3.0)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


async def readiness() -> tuple[bool, dict[str, Any]]:
    postgres, valkey, rabbitmq, seaweedfs = await asyncio.gather(
        _check_postgres(),
        _check_valkey(),
        _check_rabbitmq(),
        _check_seaweedfs(),
    )

    dependencies = {
        "postgres": postgres,
        "valkey": valkey,
        "rabbitmq": rabbitmq,
        "seaweedfs": seaweedfs,
    }

    healthy = all(item.get("ok") for item in dependencies.values())

    return healthy, dependencies
