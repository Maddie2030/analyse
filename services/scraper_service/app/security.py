import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from shared import valid_session_payload

from app.config import settings


def normalize_url(raw_url: str) -> str:
    value = str(raw_url).strip()

    if not value:
        raise HTTPException(400, "URL is required.")

    if "://" not in value:
        value = f"https://{value}"

    return value


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def resolve_public_addresses(raw_url: str) -> tuple[str, list[str]]:
    normalized = normalize_url(raw_url)
    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "Only http/https URLs are allowed.")

    if not parsed.hostname:
        raise HTTPException(400, "URL hostname is required.")

    host = parsed.hostname.rstrip(".").lower()

    if host in {"localhost"} or host.endswith(".local"):
        raise HTTPException(400, "Private/local hosts are not allowed.")

    loop = asyncio.get_running_loop()

    try:
        addresses = await loop.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise HTTPException(
            400,
            f"Unable to resolve target hostname '{host}': {type(exc).__name__}.",
        )

    if not addresses:
        raise HTTPException(
            400,
            f"Unable to resolve target hostname '{host}'.",
        )

    result: list[str] = []
    seen: set[str] = set()

    for item in addresses:
        address = item[4][0]

        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise HTTPException(
                400,
                f"Target hostname '{host}' resolved to an invalid IP address.",
            )

        if _blocked_ip(ip):
            raise HTTPException(
                400,
                (
                    "Private, loopback, link-local, multicast, reserved, "
                    f"or unspecified targets are blocked ({address})."
                ),
            )

        if address not in seen:
            seen.add(address)
            result.append(address)

    return normalized, result


async def validate_public_url(raw_url: str) -> str:
    normalized, _addresses = await resolve_public_addresses(raw_url)
    return normalized



async def require_admin(request: Request) -> dict:
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(401, "Not authenticated.")

    redis: Redis = request.app.state.redis
    raw = await redis.get(f"session:{session_id}")

    if raw is None:
        raise HTTPException(401, "Not authenticated.")

    if isinstance(raw, bytes):
        raw = raw.decode()

    try:
        session = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(401, "Not authenticated.")

    if not valid_session_payload(session, require_active=True):
        raise HTTPException(401, "Not authenticated.")

    if session.get("role") != "admin":
        raise HTTPException(403, "Admin access required.")

    return session
