from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import asyncpg


PUBLIC_BACKUP_ID = re.compile(r"^bkp_[0-9a-f]{24}$")


RUNTIME_COMPONENT = "backup-agent"
RUNTIME_STALE_SECONDS = 75


def _runtime_age_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())


async def backup_agent_runtime(pool: asyncpg.Pool) -> dict[str, Any]:
    """Return browser-safe backup-agent liveness/capabilities from PostgreSQL heartbeat state."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT component,status,capabilities,last_heartbeat_at,last_error
                  FROM database_protection_runtime
                 WHERE component=$1
                """,
                RUNTIME_COMPONENT,
            )
    except (asyncpg.PostgresError, AttributeError):
        row = None
    if row is None:
        return {
            "available": False,
            "status": "offline",
            "last_heartbeat_at": None,
            "capabilities": {
                "local_storage_ready": False,
                "logical_backup": False,
                "physical_snapshot": False,
                "restore_drill": False,
                "restore": False,
            },
            "restore_control": {
                "installation_fingerprint": None,
                "restore_generation": None,
            },
            "message": "Database protection operation engine is not reporting readiness.",
        }
    heartbeat = row["last_heartbeat_at"]
    age = _runtime_age_seconds(heartbeat)
    stale = age is None or age > RUNTIME_STALE_SECONDS
    raw_caps = row["capabilities"] or {}
    fingerprint = raw_caps.get("installation_fingerprint")
    generation = raw_caps.get("restore_generation")
    valid_restore_control = (
        isinstance(fingerprint, str)
        and re.fullmatch(r"inst_[0-9a-f]{16}", fingerprint) is not None
        and isinstance(generation, int)
        and not isinstance(generation, bool)
        and generation >= 1
    )
    caps = {
        key: bool(raw_caps.get(key)) and not stale
        for key in ("local_storage_ready", "logical_backup", "physical_snapshot", "restore_drill", "restore")
    }
    caps["restore"] = caps["restore"] and valid_restore_control
    status = "offline" if stale else str(row["status"] or "degraded")
    if stale:
        message = "Database protection operation engine heartbeat is stale."
    elif status == "ready":
        message = "Database protection operation engine is ready."
    else:
        message = "Database protection operation engine is available with limited capabilities."
    return {
        "available": not stale,
        "status": status,
        "last_heartbeat_at": heartbeat.isoformat() if heartbeat else None,
        "capabilities": caps,
        "restore_control": {
            "installation_fingerprint": fingerprint if valid_restore_control and not stale else None,
            "restore_generation": generation if valid_restore_control and not stale else None,
        },
        "message": message,
    }


def capability_ready(runtime: dict[str, Any], capability: str) -> bool:
    return bool(runtime.get("available")) and bool((runtime.get("capabilities") or {}).get(capability))


def public_operation(item: dict[str, Any]) -> dict[str, Any]:
    """Strip storage paths, filenames, metadata and raw backend errors from browser responses."""
    backup_id = None
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    for candidate in (metadata.get("recovery_public_id"), result.get("recovery_public_id")):
        if isinstance(candidate, str) and PUBLIC_BACKUP_ID.fullmatch(candidate):
            backup_id = candidate
            break
    status = str(item.get("status") or "")
    if status == "failed":
        message = "Database protection operation failed. Review backup-agent logs for internal diagnostics."
    elif status == "running":
        message = "Operation in progress."
    elif status == "queued":
        message = "Operation queued."
    elif status in {"verified", "completed"}:
        message = "Operation completed successfully."
    elif status == "cancelled":
        message = "Operation cancelled."
    else:
        message = "Database protection operation updated."
    return {
        "id": item.get("id"),
        "operation_type": item.get("operation_type"),
        "status": status,
        "phase": item.get("phase"),
        "backup_id": backup_id,
        "requested_by_username": item.get("requested_by_username"),
        "requested_at": item.get("requested_at"),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        "message": message,
    }


def _operation(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "operation_type": row["operation_type"],
        "status": row["status"],
        "phase": row["phase"],
        "category": row["category"],
        "backup_filename": row["backup_filename"],
        "requested_by": str(row["requested_by"]) if row["requested_by"] else None,
        "requested_by_username": row["requested_by_username"],
        "requested_at": row["requested_at"].isoformat() if row["requested_at"] else None,
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "error": row["error"],
        "metadata": row["metadata"] or {},
        "result": row["result"] or {},
    }


async def list_operations(pool: asyncpg.Pool, limit: int = 50) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM database_operations ORDER BY requested_at DESC LIMIT $1",
            max(1, min(limit, 100)),
        )
    return [_operation(row) or {} for row in rows]


async def queue_operation(
    pool: asyncpg.Pool,
    admin: dict,
    operation_type: str,
    *,
    category: str | None = None,
    backup_filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    if operation_type not in {"backup", "restore_drill", "restore"}:
        raise ValueError("Unsupported database operation")
    async with pool.acquire() as conn:
        async with conn.transaction():
            active = await conn.fetchrow(
                "SELECT * FROM database_operations WHERE status IN ('queued','running') ORDER BY requested_at LIMIT 1 FOR UPDATE"
            )
            if active is not None:
                return _operation(active) or {}, False
            row = await conn.fetchrow(
                """
                INSERT INTO database_operations(
                    operation_type,status,phase,category,backup_filename,
                    requested_by,requested_by_username,metadata
                ) VALUES ($1,'queued','queued',$2,$3,$4::uuid,$5,$6::jsonb)
                ON CONFLICT DO NOTHING RETURNING *
                """,
                operation_type,
                category,
                backup_filename,
                admin.get("user_id"),
                admin.get("username"),
                metadata or {},
            )
            if row is not None:
                return _operation(row) or {}, True
            active = await conn.fetchrow(
                "SELECT * FROM database_operations WHERE status IN ('queued','running') ORDER BY requested_at LIMIT 1"
            )
            return _operation(active) or {}, False


async def cancel_operation(pool: asyncpg.Pool, operation_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE database_operations
               SET status='cancelled', phase='cancelled', completed_at=now(),
                   error='Cancelled by administrator before execution.'
             WHERE id=$1::uuid AND status='queued'
             RETURNING *
            """,
            operation_id,
        )
        if row is not None:
            return _operation(row)
        return _operation(await conn.fetchrow("SELECT * FROM database_operations WHERE id=$1::uuid", operation_id))
