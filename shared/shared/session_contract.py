from __future__ import annotations

import uuid
from datetime import datetime

SESSION_CONTRACT_VERSION = 1


def _valid_v1_uuid(raw: object) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == raw.lower()


def _valid_rfc3339(raw: object) -> bool:
    if not isinstance(raw, str) or not raw or "T" not in raw:
        return False
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def valid_session_payload(value: object, *, require_active: bool = False) -> bool:
    """Validate the Redis session envelope shared by Python services.

    Version 0/missing is accepted only for the rolling-upgrade window. Version
    1 is the strict cross-language contract in contracts/session/v1.
    """
    if not isinstance(value, dict):
        return False
    version = value.get("version", 0)
    if version not in (0, SESSION_CONTRACT_VERSION):
        return False

    user_id = value.get("user_id")
    username = value.get("username")
    if not isinstance(user_id, str) or not user_id:
        return False
    if not isinstance(username, str) or not (1 <= len(username) <= 100):
        return False
    if value.get("role") not in {"user", "admin"}:
        return False
    if not isinstance(value.get("is_active"), bool):
        return False
    if require_active and value.get("is_active") is not True:
        return False

    if version == SESSION_CONTRACT_VERSION:
        if not _valid_v1_uuid(user_id):
            return False
        if not _valid_rfc3339(value.get("created_at")):
            return False
    return True
