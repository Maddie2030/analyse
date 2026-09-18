"""Shared MReader primitives with lazy exports.

Services import different subsets of this package. Keep package import itself
lightweight so a service that only needs the session contract does not create a
PostgreSQL engine or require database/model dependencies at import time.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "settings": (".config", "settings"),
    "get_db": (".database", "get_db"),
    "engine": (".database", "engine"),
    "AsyncSessionLocal": (".database", "AsyncSessionLocal"),
    "get_redis": (".redis_client", "get_redis"),
    "init_redis_pool": (".redis_client", "init_redis_pool"),
    "close_redis_pool": (".redis_client", "close_redis_pool"),
    "cache_get": (".cache", "cache_get"),
    "cache_set": (".cache", "cache_set"),
    "cache_delete": (".cache", "cache_delete"),
    "cache_invalidate_pattern": (".cache", "cache_invalidate_pattern"),
    "cache_get_or_set": (".cache", "cache_get_or_set"),
    "SeaweedFSClient": (".seaweedfs", "SeaweedFSClient"),
    "init_seaweedfs_client": (".seaweedfs", "init_seaweedfs_client"),
    "close_seaweedfs_client": (".seaweedfs", "close_seaweedfs_client"),
    "get_seaweedfs": (".seaweedfs", "get_seaweedfs"),
    "create_session": (".session", "create_session"),
    "get_session": (".session", "get_session"),
    "delete_session": (".session", "delete_session"),
    "refresh_session": (".session", "refresh_session"),
    "SESSION_CONTRACT_VERSION": (".session_contract", "SESSION_CONTRACT_VERSION"),
    "valid_session_payload": (".session_contract", "valid_session_payload"),
    "hash_password": (".auth", "hash_password"),
    "verify_password": (".auth", "verify_password"),
    "verify_turnstile": (".auth", "verify_turnstile"),
    "get_current_user": (".auth", "get_current_user"),
    "get_current_user_optional": (".auth", "get_current_user_optional"),
    "require_user": (".auth", "require_user"),
    "require_admin": (".auth", "require_admin"),
    "is_rate_limited": (".rate_limit", "is_rate_limited"),
    "enqueue_cleanup_job": (".lifecycle", "enqueue_cleanup_job"),
    "Base": (".models", "Base"),
    "User": (".models", "User"),
    "Genre": (".models", "Genre"),
    "Series": (".models", "Series"),
    "SeriesGenre": (".models", "SeriesGenre"),
    "Tag": (".models", "Tag"),
    "SeriesTag": (".models", "SeriesTag"),
    "Chapter": (".models", "Chapter"),
    "Page": (".models", "Page"),
    "ReadingProgress": (".models", "ReadingProgress"),
    "Bookmark": (".models", "Bookmark"),
    "Subscription": (".models", "Subscription"),
    "Notification": (".models", "Notification"),
    "Comment": (".models", "Comment"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
