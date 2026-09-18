from __future__ import annotations

import errno
from typing import Any

import httpx


_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RETRYABLE_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.ENETRESET,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
    errno.EPIPE,
}


class TransientPublishDeferred(RuntimeError):
    """Publish was preserved and should be retried automatically later."""


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def is_transient_error(exc: BaseException | None) -> bool:
    """Recognize temporary transport/service failures without hiding logic bugs.

    The walk through __cause__/__context__ is important because higher-level
    scraper helpers often wrap an HTTPX transport exception in HTTPException or
    RuntimeError. Validation/parser errors remain terminal.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
            return True
        if isinstance(current, httpx.HTTPStatusError):
            if _status_code(current) in _RETRYABLE_HTTP_STATUS:
                return True
        if isinstance(current, OSError) and getattr(current, "errno", None) in _RETRYABLE_ERRNOS:
            return True

        status = _status_code(current)
        if status in _RETRYABLE_HTTP_STATUS:
            return True

        name = type(current).__name__.lower()
        module = type(current).__module__.lower()
        if "asyncpg" in module and any(
            token in name
            for token in (
                "connection", "cannotconnect", "toomanyconnections", "postmastershutdown",
                "adminshutdown", "crashshutdown",
            )
        ):
            return True
        if "aio_pika" in module or "aiormq" in module:
            if any(token in name for token in ("connection", "channel", "timeout", "closed")):
                return True

        current = current.__cause__ or current.__context__
    return False


def transient_message(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:1800]
