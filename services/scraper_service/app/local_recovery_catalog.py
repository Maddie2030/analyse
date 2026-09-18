from __future__ import annotations

import base64
from datetime import datetime
import json
import re
from typing import Any, Mapping


PUBLIC_RECOVERY_ID = re.compile(r"^bkp_[0-9a-f]{24}$")
RECOVERY_CURSOR = re.compile(r"^[A-Za-z0-9_-]{1,512}$")


def _row_value(row: Mapping[str, Any], key: str) -> Any:
    return row[key]


def public_recovery_point(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return only browser-safe recovery metadata from the local projection."""
    created = _row_value(row, "created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return {
        "id": _row_value(row, "public_id"),
        "kind": _row_value(row, "kind"),
        "type": _row_value(row, "purpose"),
        "timestamp_utc": created,
        "mreader_version": _row_value(row, "mreader_version"),
        "postgres_major": _row_value(row, "postgres_major"),
        "size_bytes": _row_value(row, "size_bytes"),
        "verified": bool(_row_value(row, "verified")),
    }


async def list_recovery_points(pool: Any, limit: int = 50) -> list[Mapping[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT recovery_id,public_id,kind,purpose,relative_directory,
                   artifact_name,created_at,postgres_major,mreader_version,
                   size_bytes,sha256,verified,available
              FROM database_recovery_points
             WHERE available AND verified
             ORDER BY created_at DESC
             LIMIT $1
            """,
            max(1, min(limit, 100)),
        )
    return list(rows)


def _encode_recovery_cursor(row: Mapping[str, Any]) -> str:
    created_at = _row_value(row, "created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    payload = json.dumps(
        [str(created_at), str(_row_value(row, "public_id"))],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_recovery_cursor(cursor: str) -> tuple[str, str]:
    cursor = cursor.strip()
    if not RECOVERY_CURSOR.fullmatch(cursor):
        raise ValueError("Invalid recovery inventory cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid recovery inventory cursor") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not all(isinstance(item, str) for item in payload)
    ):
        raise ValueError("Invalid recovery inventory cursor")
    created_at, public_id = payload
    if not PUBLIC_RECOVERY_ID.fullmatch(public_id):
        raise ValueError("Invalid recovery inventory cursor")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid recovery inventory cursor") from exc
    return created_at, public_id


async def list_recovery_page(
    pool: Any, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 100))
    async with pool.acquire() as conn:
        total = int(
            await conn.fetchval(
                """
                SELECT count(*)
                  FROM database_recovery_points
                 WHERE available AND verified
                """
            )
            or 0
        )
        if cursor:
            created_at, public_id = _decode_recovery_cursor(cursor)
            rows = await conn.fetch(
                """
                SELECT recovery_id,public_id,kind,purpose,relative_directory,
                       artifact_name,created_at,postgres_major,mreader_version,
                       size_bytes,sha256,verified,available
                  FROM database_recovery_points
                 WHERE available AND verified
                   AND (created_at, public_id) < ($1::timestamptz, $2::text)
                 ORDER BY created_at DESC, public_id DESC
                 LIMIT $3
                """,
                created_at,
                public_id,
                bounded_limit + 1,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT recovery_id,public_id,kind,purpose,relative_directory,
                       artifact_name,created_at,postgres_major,mreader_version,
                       size_bytes,sha256,verified,available
                  FROM database_recovery_points
                 WHERE available AND verified
                 ORDER BY created_at DESC, public_id DESC
                 LIMIT $1
                """,
                bounded_limit + 1,
            )
    items = list(rows[:bounded_limit])
    next_cursor = _encode_recovery_cursor(items[-1]) if len(rows) > bounded_limit and items else None
    return {"items": items, "next_cursor": next_cursor, "total": total}


async def resolve_recovery_point(pool: Any, public_id: str) -> Mapping[str, Any]:
    public_id = public_id.strip()
    if not PUBLIC_RECOVERY_ID.fullmatch(public_id):
        raise ValueError("Invalid backup identifier")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recovery_id,public_id,kind,purpose,relative_directory,
                   artifact_name,created_at,postgres_major,mreader_version,
                   size_bytes,sha256,verified,available
              FROM database_recovery_points
             WHERE public_id=$1 AND available AND verified
            """,
            public_id,
        )
    if row is None:
        raise LookupError("Backup not found")
    return row


def public_local_storage_status(
    runtime: Mapping[str, Any],
    recovery_points: list[Mapping[str, Any]],
    total_count: int | None = None,
) -> dict[str, Any]:
    capabilities = runtime.get("capabilities") or {}
    ready = bool(runtime.get("available")) and bool(
        capabilities.get("local_storage_ready")
    )
    return {
        "status": "verified" if ready else "unavailable",
        "healthy": ready,
        "local_storage_ready": ready,
        "backup_count": len(recovery_points) if total_count is None else total_count,
        "message": (
            "Host-local recovery storage is ready."
            if ready
            else "Host-local recovery storage requires operator attention."
        ),
        "operator_action": (
            None
            if ready
            else "Review the database-protection root and backup-agent diagnostics."
        ),
    }
