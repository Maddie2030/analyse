from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.database_protection import (
    backup_agent_runtime,
    cancel_operation as cancel_database_operation,
    capability_ready,
    list_operations as list_database_operations,
    public_operation,
    queue_operation as queue_database_operation,
)
from app.local_recovery_catalog import (
    list_recovery_page,
    public_local_storage_status,
    public_recovery_point,
    resolve_recovery_point,
)
from app.models import DatabaseBackupTarget, DatabaseRestoreRequest
from app.security import require_admin


log = logging.getLogger("scraper.database_facade")
router = APIRouter(prefix="/api/admin/database", tags=["admin-database"])


@router.get("")
async def admin_database_protection_status(
    request: Request,
    _admin: dict = Depends(require_admin),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
):
    operations = await list_database_operations(request.app.state.db, limit)
    try:
        backup_page = await list_recovery_page(
            request.app.state.db, limit=limit, cursor=cursor
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    recovery_points = backup_page["items"]
    runtime = await backup_agent_runtime(request.app.state.db)
    return {
        "storage": public_local_storage_status(
            runtime, recovery_points, total_count=backup_page["total"]
        ),
        "runtime": runtime,
        "policy": {
            "timezone": settings.postgres_backup_tz,
            "automatic_window_start": settings.postgres_backup_auto_window_start,
            "automatic_window_end": settings.postgres_backup_auto_window_end,
            "logical_retention_days": settings.postgres_backup_daily_retention_days,
            "snapshot_retention_days": settings.postgres_backup_snapshot_retention_days,
        },
        "operations": [public_operation(item) for item in operations],
        "backups": [public_recovery_point(item) for item in recovery_points],
        "backup_page": {
            "next_cursor": backup_page["next_cursor"],
            "total": backup_page["total"],
        },
    }


async def _require_database_capability(request: Request, capability: str) -> dict:
    runtime = await backup_agent_runtime(request.app.state.db)
    if not runtime.get("available"):
        raise HTTPException(503, "Database protection operation engine is unavailable")
    if not capability_ready(runtime, capability):
        messages = {
            "logical_backup": "Logical backup is temporarily unavailable until host-local recovery storage is ready",
            "physical_snapshot": "Physical snapshot is temporarily unavailable until host-local recovery storage and PostgreSQL replication are ready",
            "restore_drill": "Restore drill is temporarily unavailable because the recovery engine cannot access the verified local recovery catalog",
            "restore": "Production restore is temporarily unavailable until the host-local pre-restore safety-backup capability is ready",
        }
        raise HTTPException(409, messages.get(capability, "Requested database protection capability is unavailable"))
    return runtime


@router.post("/backups", status_code=202)
async def admin_database_backup(
    request: Request,
    admin: dict = Depends(require_admin),
):
    await _require_database_capability(request, "logical_backup")
    item, created = await queue_database_operation(
        request.app.state.db,
        admin,
        "backup",
        metadata={"trigger": "admin-ui"},
    )
    return {"operation": public_operation(item), "created": created}


@router.post("/snapshots", status_code=202)
async def admin_database_snapshot(
    request: Request,
    admin: dict = Depends(require_admin),
):
    await _require_database_capability(request, "physical_snapshot")
    item, created = await queue_database_operation(
        request.app.state.db,
        admin,
        "backup",
        category="snapshots",
        metadata={"trigger": "admin-ui", "backup_kind": "physical-snapshot"},
    )
    return {"operation": public_operation(item), "created": created}


@router.post("/restore-drills", status_code=202)
async def admin_database_restore_drill(
    payload: DatabaseBackupTarget,
    request: Request,
    admin: dict = Depends(require_admin),
):
    try:
        recovery = await resolve_recovery_point(request.app.state.db, payload.backup_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Backup not found") from exc
    await _require_database_capability(request, "restore_drill")
    item, created = await queue_database_operation(
        request.app.state.db,
        admin,
        "restore_drill",
        category=str(recovery["purpose"]),
        backup_filename=str(recovery["recovery_id"]),
        metadata={"recovery_public_id": payload.backup_id},
    )
    return {"operation": public_operation(item), "created": created}


@router.post("/restores", status_code=202)
async def admin_database_restore(
    payload: DatabaseRestoreRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    try:
        recovery = await resolve_recovery_point(request.app.state.db, payload.backup_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Backup not found") from exc
    runtime = await _require_database_capability(request, "restore")
    restore_control = runtime.get("restore_control") or {}
    fingerprint = str(restore_control.get("installation_fingerprint") or "")
    generation = restore_control.get("restore_generation")
    if payload.installation_fingerprint != fingerprint or payload.restore_generation != generation:
        raise HTTPException(409, "Restore confirmation is stale; refresh database protection status and retry")
    expected = f"RESTORE {payload.backup_id} ON {fingerprint} GEN {generation}"
    if payload.confirmation != expected:
        raise HTTPException(400, "Restore confirmation did not match the selected backup, installation and generation")
    item, created = await queue_database_operation(
        request.app.state.db,
        admin,
        "restore",
        category=str(recovery["purpose"]),
        backup_filename=str(recovery["recovery_id"]),
        metadata={
            "typed_confirmation": True,
            "recovery_public_id": payload.backup_id,
            "recovery_sha256": str(recovery["sha256"]),
            "expected_installation_fingerprint": fingerprint,
            "expected_restore_generation": generation,
        },
    )
    return {"operation": public_operation(item), "created": created}


@router.post("/operations/{operation_id}/cancel")
async def admin_cancel_database_operation(
    operation_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    item = await cancel_database_operation(request.app.state.db, str(operation_id))
    if item is None:
        raise HTTPException(404, "Database operation not found")
    if item["status"] != "cancelled":
        raise HTTPException(409, "Only queued database operations can be cancelled")
    return public_operation(item)


@router.get("/backups/{backup_id}/download")
async def admin_download_database_backup(
    backup_id: str,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    try:
        recovery = await resolve_recovery_point(request.app.state.db, backup_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Backup not found") from exc

    token = settings.recovery_bridge_token.strip()
    base_url = settings.recovery_bridge_internal_url.rstrip("/")
    if not token or not base_url:
        raise HTTPException(503, "Recovery download bridge is unavailable")

    upstream_request = request.app.state.http.build_request(
        "GET",
        f"{base_url}/internal/v1/recovery/download/{backup_id}",
        headers={"X-MReader-Internal-Token": token},
    )
    try:
        upstream = await request.app.state.http.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        log.warning("private recovery bridge request failed type=%s", type(exc).__name__)
        raise HTTPException(503, "Recovery download bridge is unavailable") from exc

    if upstream.status_code != 200:
        status = upstream.status_code
        await upstream.aclose()
        if status == 404:
            raise HTTPException(404, "Backup not found")
        if status in {401, 403, 503}:
            raise HTTPException(503, "Recovery download bridge is unavailable")
        raise HTTPException(502, "Recovery download bridge returned an invalid response")

    expected_size = int(recovery["size_bytes"])
    expected_sha256 = str(recovery["sha256"])
    if (
        upstream.headers.get("content-length") != str(expected_size)
        or upstream.headers.get("x-mreader-content-sha256") != expected_sha256
    ):
        await upstream.aclose()
        raise HTTPException(409, "Recovery point changed while preparing the download; refresh and retry")

    extension = ".tar" if recovery["kind"] == "physical_snapshot" else ".dump"

    async def stream_verified_recovery():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        stream_verified_recovery(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{backup_id}{extension}"',
            "Content-Length": str(expected_size),
            "X-Content-Type-Options": "nosniff",
            "X-MReader-Content-SHA256": expected_sha256,
        },
    )
