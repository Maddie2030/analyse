from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared import get_db, require_admin

router = APIRouter(tags=["admin-lifecycle"])


@router.get("/lifecycle/cleanup-jobs")
async def cleanup_jobs(
    state: str | None = Query(None, pattern="^(active|queued|processing|retry|completed|failed)$"),
    limit: int = Query(50, ge=1, le=200),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if state == "active":
        where = "WHERE status IN ('queued','processing','retry','failed')"
    else:
        where = "WHERE status = :state" if state else ""
    result = await db.execute(text(f"""
        SELECT id::text, entity_type, entity_id::text,
               jsonb_strip_nulls(jsonb_build_object(
                   'reason', payload->>'reason',
                   'storage_attempt_id', payload->>'storage_attempt_id',
                   'image_path_count', jsonb_array_length(COALESCE(payload->'image_paths','[]'::jsonb)),
                   'storage_prefix_count', jsonb_array_length(COALESCE(payload->'storage_prefixes','[]'::jsonb)),
                   'local_staging_prefix_count', jsonb_array_length(COALESCE(payload->'local_staging_prefixes','[]'::jsonb))
               )) AS payload,
               status, attempts, max_attempts,
               next_attempt_at, last_error, created_at, updated_at, completed_at
        FROM lifecycle_cleanup_jobs
        {where}
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"state": state, "limit": limit})
    return [dict(row) for row in result.mappings().all()]


@router.post("/lifecycle/cleanup-jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_cleanup_job(
    job_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(422, "Invalid cleanup job id.")
    result = await db.execute(text("""
        UPDATE lifecycle_cleanup_jobs
        SET status='retry', next_attempt_at=NOW(), locked_at=NULL, locked_by=NULL,
            completed_at=NULL, last_error=NULL, updated_at=NOW()
        WHERE id=CAST(:id AS uuid) AND status IN ('failed','retry')
        RETURNING id::text
    """), {"id": job_id})
    if result.scalar_one_or_none() is None:
        raise HTTPException(409, "Cleanup job is not retryable or does not exist.")
    return {"accepted": True, "job_id": job_id}
