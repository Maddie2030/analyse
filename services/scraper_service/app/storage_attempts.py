from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg

from app.config import settings


log = logging.getLogger("scraper.storage-attempts")


class StagingCleanupPending(RuntimeError):
    pass


class StagingCleanupFailed(RuntimeError):
    pass


async def begin_storage_attempt(
    pool: asyncpg.Pool,
    *,
    operation_type: str,
    draft_id: str | None = None,
    draft_chapter_id: str | None = None,
    batch_item_id: str | None = None,
    batch_id: str | None = None,
    local_staging_prefix: str | None = None,
    recovery_entity_id: str | None = None,
) -> str:
    """Create the durable ledger row *before* any external storage mutation."""
    async with pool.acquire() as conn:
        return str(
            await conn.fetchval(
                """
                INSERT INTO scraper_storage_attempts (
                    operation_type, draft_id, draft_chapter_id,
                    batch_item_id, batch_id, local_staging_prefix, canonical_entity_id
                )
                VALUES (
                    $1, $2::uuid, $3::uuid, $4::uuid, $5::uuid, $6, $7::uuid
                )
                RETURNING id::text
                """,
                operation_type,
                draft_id,
                draft_chapter_id,
                batch_item_id,
                batch_id,
                local_staging_prefix,
                recovery_entity_id,
            )
        )


async def heartbeat_storage_attempt(pool: asyncpg.Pool, attempt_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE scraper_storage_attempts
            SET heartbeat_at=NOW(), updated_at=NOW()
            WHERE id=$1::uuid AND status='active'
            """,
            attempt_id,
        )


async def storage_attempt_heartbeat_loop(
    pool: asyncpg.Pool,
    attempt_id: str,
    stop: asyncio.Event,
) -> None:
    interval = max(5.0, float(settings.scraper_storage_attempt_heartbeat_seconds))
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            try:
                await heartbeat_storage_attempt(pool, attempt_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The main publisher still reserves every path before writing.
                # A transient remote-DB outage must not make the heartbeat task
                # kill the worker; recovery deliberately errs toward retention.
                log.warning("storage attempt heartbeat failed id=%s", attempt_id, exc_info=True)


async def mark_storage_attempt_committed(
    conn: asyncpg.Connection,
    attempt_id: str,
    canonical_entity_id: str | None,
) -> None:
    """Mark canonical acceptance inside the same transaction as the entity commit."""
    result = await conn.execute(
        """
        UPDATE scraper_storage_attempts
        SET status='committed', canonical_entity_id=$2::uuid,
            object_paths='[]'::jsonb, heartbeat_at=NOW(), updated_at=NOW(),
            finished_at=NOW(), last_error=NULL
        WHERE id=$1::uuid AND status='active'
        """,
        attempt_id,
        canonical_entity_id,
    )
    if result.endswith("0"):
        # Stale-attempt recovery may already have claimed this ledger row and
        # queued deletion. Never allow a late publisher to commit references to
        # objects that a lifecycle worker is now entitled to remove. Raising
        # here rolls back the caller's canonical PostgreSQL transaction.
        raise RuntimeError("Storage attempt lease was lost before canonical commit.")


async def enqueue_local_staging_cleanup(
    conn: asyncpg.Connection,
    *,
    entity_id: str | None,
    local_prefix: str,
    reason: str,
) -> str:
    """Durably request local staging cleanup in the caller's DB transaction."""
    prefix = str(local_prefix).strip().replace("\\", "/").lstrip("/")
    if not prefix.startswith("_scraper/"):
        raise ValueError("Only scraper-private staging prefixes can be queued.")

    existing = await conn.fetchval(
        """
        SELECT id::text
        FROM lifecycle_cleanup_jobs
        WHERE entity_type='scraper_staging'
          AND entity_id IS NOT DISTINCT FROM $1::uuid
          AND status IN ('queued','processing','retry','failed')
          AND COALESCE(payload->'local_staging_prefixes','[]'::jsonb) ? $2::text
        ORDER BY created_at DESC
        LIMIT 1
        """,
        entity_id,
        prefix,
    )
    if existing:
        return str(existing)

    payload: dict[str, Any] = {
        "local_staging_prefixes": [prefix],
        "reason": str(reason)[:200],
    }
    return str(
        await conn.fetchval(
            """
            INSERT INTO lifecycle_cleanup_jobs (entity_type,entity_id,payload,max_attempts)
            VALUES ('scraper_staging',$1::uuid,$2::jsonb,20)
            RETURNING id::text
            """,
            entity_id,
            json.dumps(payload),
        )
    )


async def _queue_attempt_cleanup_locked(
    conn: asyncpg.Connection,
    row: asyncpg.Record,
    *,
    error: str | None = None,
) -> str | None:
    if row["status"] == "committed":
        return None
    paths = [str(value) for value in (row["object_paths"] or []) if value]
    if not paths:
        await conn.execute(
            """
            UPDATE scraper_storage_attempts
            SET status='cleanup_complete', object_paths='[]'::jsonb,
                heartbeat_at=NOW(), updated_at=NOW(), finished_at=NOW(),
                last_error=$2
            WHERE id=$1::uuid
            """,
            row["id"],
            (error or None),
        )
        return None

    payload = {
        "image_paths": sorted(set(paths)),
        "reason": "scraper_storage_attempt_recovery",
        "storage_attempt_id": str(row["id"]),
    }
    cleanup_job_id = await conn.fetchval(
        """
        INSERT INTO lifecycle_cleanup_jobs (entity_type,entity_id,payload,max_attempts)
        VALUES ('scraper_orphan',$1::uuid,$2::jsonb,20)
        RETURNING id::text
        """,
        row["canonical_entity_id"],
        json.dumps(payload),
    )
    await conn.execute(
        """
        UPDATE scraper_storage_attempts
        SET status='cleanup_queued', cleanup_job_id=$2::uuid,
            object_paths='[]'::jsonb, heartbeat_at=NOW(), updated_at=NOW(),
            finished_at=NOW(), last_error=$3
        WHERE id=$1::uuid
        """,
        row["id"],
        cleanup_job_id,
        (error or None),
    )
    return str(cleanup_job_id)


async def _all_paths_referenced_by_chapter(
    conn: asyncpg.Connection,
    chapter_id: str,
    object_paths: list[str],
) -> bool:
    paths = sorted({str(value).strip().lstrip("/") for value in object_paths if str(value).strip()})
    if not paths:
        return True
    rows = await conn.fetch(
        """
        SELECT image_path AS path FROM pages
        WHERE chapter_id=$1::uuid AND image_path = ANY($2::text[])
        UNION
        SELECT responsive_image_path AS path FROM pages
        WHERE chapter_id=$1::uuid
          AND responsive_image_path IS NOT NULL
          AND responsive_image_path = ANY($2::text[])
        """,
        chapter_id,
        paths,
    )
    referenced = {str(row["path"]).lstrip("/") for row in rows if row["path"]}
    return referenced == set(paths)


async def _canonical_entity_for_attempt(
    conn: asyncpg.Connection,
    row: asyncpg.Record,
) -> str | None:
    operation_type = str(row["operation_type"])
    object_paths = [str(value) for value in (row["object_paths"] or []) if value]
    if operation_type == "chapter_publish" and row["draft_chapter_id"]:
        published_id = await conn.fetchval(
            """
            SELECT published_chapter_id::text
            FROM scraper_series_draft_chapters
            WHERE id=$1::uuid
            """,
            row["draft_chapter_id"],
        )
        if published_id and await _all_paths_referenced_by_chapter(conn, str(published_id), object_paths):
            return str(published_id)
        return None
    if operation_type == "series_cover" and row["draft_id"]:
        published = await conn.fetchrow(
            """
            SELECT d.published_series_id::text AS id, s.cover_image_path
            FROM scraper_series_drafts d
            LEFT JOIN series s ON s.id=d.published_series_id
            WHERE d.id=$1::uuid
            """,
            row["draft_id"],
        )
        if not published or not published["id"]:
            return None
        if not object_paths or str(published["cover_image_path"] or "").lstrip("/") in {p.lstrip("/") for p in object_paths}:
            return str(published["id"])
        return None
    if operation_type == "batch_publish" and row["batch_item_id"]:
        published_id = await conn.fetchval(
            """
            SELECT published_chapter_id::text
            FROM scraper_batch_items
            WHERE id=$1::uuid AND status='completed'
            """,
            row["batch_item_id"],
        )
        if published_id and await _all_paths_referenced_by_chapter(conn, str(published_id), object_paths):
            return str(published_id)
        return None
    if operation_type == "batch_stage_create" and row["batch_id"]:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM scraper_batch_uploads WHERE id=$1::uuid)",
            row["batch_id"],
        )
        return str(row["batch_id"]) if exists else None
    if operation_type == "existing_draft_stage_create" and row["canonical_entity_id"]:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM scraper_drafts WHERE id=$1::uuid)",
            row["canonical_entity_id"],
        )
        return str(row["canonical_entity_id"]) if exists else None
    if operation_type == "existing_draft_publish" and row["canonical_entity_id"]:
        published_id = await conn.fetchval(
            """
            SELECT published_chapter_id::text
            FROM scraper_drafts
            WHERE id=$1::uuid AND status='published'
            """,
            row["canonical_entity_id"],
        )
        if published_id and await _all_paths_referenced_by_chapter(conn, str(published_id), object_paths):
            return str(published_id)
        return None
    return None


async def resolve_storage_attempt(
    pool: asyncpg.Pool,
    attempt_id: str,
    *,
    error: str | None = None,
) -> str:
    """Resolve an active attempt from canonical PostgreSQL state.

    Returns committed, cleanup_queued/cleanup_complete, or already_resolved.
    If PostgreSQL itself is unavailable the function raises; callers must then
    deliberately leave all storage untouched because the commit outcome is
    unknowable.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id::text, operation_type, draft_id::text,
                       draft_chapter_id::text, batch_item_id::text, batch_id::text,
                       local_staging_prefix, object_paths, status,
                       canonical_entity_id::text
                FROM scraper_storage_attempts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                attempt_id,
            )
            if row is None:
                return "already_resolved"
            if row["status"] != "active":
                return str(row["status"])

            canonical_id = await _canonical_entity_for_attempt(conn, row)
            if canonical_id:
                await mark_storage_attempt_committed(conn, attempt_id, canonical_id)
                return "committed"

            # A batch staging attempt owns only the local staging prefix; it has
            # no production object paths. Hand that cleanup to the same durable
            # lifecycle queue so a crash cannot strand it forever.
            if row["operation_type"] in {"batch_stage_create", "existing_draft_stage_create"} and row["local_staging_prefix"]:
                cleanup_entity_id = row["batch_id"] if row["operation_type"] == "batch_stage_create" else row["canonical_entity_id"]
                cleanup_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=cleanup_entity_id,
                    local_prefix=row["local_staging_prefix"],
                    reason=(
                        "batch_create_not_committed"
                        if row["operation_type"] == "batch_stage_create"
                        else "existing_draft_create_not_committed"
                    ),
                )
                await conn.execute(
                    """
                    UPDATE scraper_storage_attempts
                    SET status='cleanup_queued', cleanup_job_id=$2::uuid,
                        object_paths='[]'::jsonb, heartbeat_at=NOW(), updated_at=NOW(),
                        finished_at=NOW(), last_error=$3
                    WHERE id=$1::uuid
                    """,
                    attempt_id,
                    cleanup_id,
                    (error or None),
                )
                return "cleanup_queued"

            cleanup_id = await _queue_attempt_cleanup_locked(conn, row, error=error)
            return "cleanup_queued" if cleanup_id else "cleanup_complete"


async def recover_stale_storage_attempts(pool: asyncpg.Pool) -> dict[str, int]:
    stale_seconds = max(60, int(settings.scraper_storage_attempt_stale_seconds))
    limit = max(1, min(200, int(settings.scraper_storage_attempt_recovery_batch)))
    async with pool.acquire() as conn:
        ids = await conn.fetch(
            """
            SELECT id::text
            FROM scraper_storage_attempts
            WHERE status='active'
              AND heartbeat_at < NOW() - ($1::int * INTERVAL '1 second')
            ORDER BY heartbeat_at, created_at
            LIMIT $2
            """,
            stale_seconds,
            limit,
        )

    counts = {"committed": 0, "cleanup_queued": 0, "cleanup_complete": 0}
    for item in ids:
        try:
            outcome = await resolve_storage_attempt(
                pool,
                item["id"],
                error="Recovered stale storage attempt after worker interruption.",
            )
            if outcome in counts:
                counts[outcome] += 1
        except Exception:
            log.warning("failed to recover storage attempt id=%s", item["id"], exc_info=True)
            # Stop early when a remote DB is unstable instead of creating a
            # thundering herd of repeated connection attempts.
            break

    # Once durable cleanup finished, collapse the storage-attempt row to a tiny
    # terminal marker. Failed/retrying cleanup remains visible and is not pruned.
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE scraper_storage_attempts a
            SET status='cleanup_complete', updated_at=NOW(), finished_at=COALESCE(finished_at,NOW())
            FROM lifecycle_cleanup_jobs j
            WHERE a.cleanup_job_id=j.id
              AND a.status='cleanup_queued'
              AND j.status='completed'
            """
        )
        counts["cleanup_complete"] += int(result.split()[-1]) if result.split()[-1].isdigit() else 0

        prune_days = max(1, int(settings.scraper_storage_attempt_retention_days))
        await conn.execute(
            """
            DELETE FROM scraper_storage_attempts
            WHERE status IN ('committed','cleanup_complete')
              AND object_paths='[]'::jsonb
              AND updated_at < NOW() - ($1::int * INTERVAL '1 day')
            """,
            prune_days,
        )

    return counts


async def expire_abandoned_staging(pool: asyncpg.Pool) -> int:
    """Queue durable cleanup for old, inactive local staging when explicitly enabled.

    The default TTL is zero, so upgrades preserve every unpublished draft. When
    an operator opts into expiry, only inactive drafts are eligible. The cleanup
    intent and removal of stale PostgreSQL staging references are committed in
    the same transaction; physical deletion is left to the retryable lifecycle
    worker.
    """
    ttl_hours = int(settings.scraper_staging_ttl_hours)
    if ttl_hours <= 0:
        return 0

    # Keep each scan bounded so a remote PostgreSQL connection is never held for
    # a large library sweep. Subsequent scans continue from remaining candidates.
    async with pool.acquire() as conn:
        candidates = await conn.fetch(
            """
            SELECT d.id::text
            FROM scraper_series_drafts d
            WHERE d.updated_at < NOW() - ($1::int * INTERVAL '1 hour')
              AND d.workflow_status IN (
                    'draft','ready','failed','cancelled','duplicate',
                    'published_partial','published'
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM scraper_series_draft_chapters c
                    WHERE c.draft_id=d.id
                      AND (
                            c.stage_status IN ('queued','staging')
                            OR c.publish_status='publishing'
                      )
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM scraper_storage_attempts a
                    WHERE a.draft_id=d.id AND a.status='active'
              )
            ORDER BY d.updated_at, d.id
            LIMIT 25
            """,
            ttl_hours,
        )

    expired = 0
    for candidate in candidates:
        draft_id = str(candidate["id"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id::text, workflow_status, published_series_id::text,
                           cover_staging_path, updated_at
                    FROM scraper_series_drafts
                    WHERE id=$1::uuid
                    FOR UPDATE
                    """,
                    draft_id,
                )
                if row is None:
                    continue
                if row["workflow_status"] not in {
                    "draft", "ready", "failed", "cancelled", "duplicate",
                    "published_partial", "published",
                }:
                    continue
                still_old = await conn.fetchval(
                    "SELECT $2::timestamptz < NOW() - ($1::int * INTERVAL '1 hour')",
                    ttl_hours,
                    row["updated_at"],
                )
                if not still_old:
                    continue
                active = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM scraper_series_draft_chapters c
                        WHERE c.draft_id=$1::uuid
                          AND (c.stage_status IN ('queued','staging') OR c.publish_status='publishing')
                    ) OR EXISTS(
                        SELECT 1 FROM scraper_storage_attempts a
                        WHERE a.draft_id=$1::uuid AND a.status='active'
                    )
                    """,
                    draft_id,
                )
                if active:
                    continue

                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft_id,
                    local_prefix=f"_scraper/series-drafts/{draft_id}",
                    reason=f"staging_retention_expired_after_{ttl_hours}h",
                )

                # Once cleanup intent is durable, PostgreSQL must not keep paths
                # that will become invalid. Published chapter identity is kept;
                # only disposable raw staging metadata is cleared.
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET pages='[]'::jsonb,
                        stage_status=CASE
                            WHEN published_chapter_id IS NOT NULL THEN 'published'
                            ELSE 'discovered'
                        END,
                        stage_progress=CASE
                            WHEN published_chapter_id IS NOT NULL THEN stage_progress
                            ELSE COALESCE(stage_progress,'{}'::jsonb) || jsonb_build_object(
                                'phase','expired','percent',0,
                                'message','Local staged files expired by the configured retention policy. Stage this chapter again before publishing.',
                                'cleanup_job_id',$2::text,
                                'updated_at',NOW()
                            )
                        END,
                        publish_status=CASE
                            WHEN published_chapter_id IS NOT NULL THEN 'published'
                            ELSE 'pending'
                        END,
                        publish_error=CASE
                            WHEN published_chapter_id IS NOT NULL THEN publish_error
                            ELSE NULL
                        END,
                        stage_worker_heartbeat_at=NULL,
                        queue_dispatched_at=NULL,
                        updated_at=NOW()
                    WHERE draft_id=$1::uuid
                    """,
                    draft_id,
                    cleanup_job_id,
                )

                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET cover_staging_path=NULL,
                        workflow_status=CASE
                            WHEN workflow_status IN ('cancelled','duplicate','published') THEN workflow_status
                            WHEN published_series_id IS NOT NULL THEN 'published_partial'
                            ELSE 'draft'
                        END,
                        error_message=CASE
                            WHEN workflow_status IN ('cancelled','duplicate','published') THEN error_message
                            ELSE 'Local staged files expired by the configured retention policy. Stage required chapters again before publishing.'
                        END,
                        publish_progress=COALESCE(publish_progress,'{}'::jsonb) || jsonb_build_object(
                            'staging_expired',TRUE,
                            'cleanup_job_id',$2::text,
                            'updated_at',NOW()
                        ),
                        updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                    cleanup_job_id,
                )
                expired += 1

    # The older "existing series" draft editor uses a different table/prefix.
    # It is still supported, so an explicitly configured retention policy must
    # not leave its raw local pages growing forever. Published identity is kept;
    # only disposable staging references are cleared.
    async with pool.acquire() as conn:
        legacy_candidates = await conn.fetch(
            """
            SELECT d.id::text
            FROM scraper_drafts d
            WHERE d.updated_at < NOW() - ($1::int * INTERVAL '1 hour')
              AND d.status IN ('draft','published')
              AND COALESCE(jsonb_array_length(d.pages),0) > 0
              AND NOT EXISTS (
                    SELECT 1 FROM scraper_storage_attempts a
                    WHERE a.draft_id=d.id AND a.status='active'
              )
            ORDER BY d.updated_at, d.id
            LIMIT 15
            """,
            ttl_hours,
        )

    for candidate in legacy_candidates:
        draft_id = str(candidate["id"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id::text, status, pages, updated_at
                    FROM scraper_drafts
                    WHERE id=$1::uuid
                    FOR UPDATE
                    """,
                    draft_id,
                )
                if row is None or row["status"] not in {"draft", "published"} or not (row["pages"] or []):
                    continue
                still_old = await conn.fetchval(
                    "SELECT $2::timestamptz < NOW() - ($1::int * INTERVAL '1 hour')",
                    ttl_hours,
                    row["updated_at"],
                )
                if not still_old:
                    continue
                active = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM scraper_storage_attempts
                        WHERE draft_id=$1::uuid AND status='active'
                    )
                    """,
                    draft_id,
                )
                if active:
                    continue
                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft_id,
                    local_prefix=f"_scraper/staging/{draft_id}",
                    reason=f"existing_draft_staging_retention_expired_after_{ttl_hours}h",
                )
                await conn.execute(
                    """
                    UPDATE scraper_drafts
                    SET pages='[]'::jsonb,
                        chapter_data=COALESCE(chapter_data,'{}'::jsonb) || jsonb_build_object(
                            'staging_expired',TRUE,
                            'staging_cleanup_job_id',$2::text
                        ),
                        updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                    cleanup_job_id,
                )
                expired += 1

    # Failed batch items are operator-held staging too. Once the operator has
    # explicitly enabled a TTL, convert old failed items to discarded and queue
    # their local chapter folders for durable cleanup. Active/queued/processing
    # work is never eligible.
    async with pool.acquire() as conn:
        batch_candidates = await conn.fetch(
            """
            SELECT i.id::text, i.batch_id::text, i.chapter_slug
            FROM scraper_batch_items i
            WHERE i.updated_at < NOW() - ($1::int * INTERVAL '1 hour')
              AND i.status IN ('failed_conflict','failed_error')
              AND COALESCE(jsonb_array_length(i.source_files),0) > 0
              AND NOT EXISTS (
                    SELECT 1 FROM scraper_storage_attempts a
                    WHERE a.batch_item_id=i.id AND a.status='active'
              )
            ORDER BY i.updated_at, i.id
            LIMIT 25
            """,
            ttl_hours,
        )

    for candidate in batch_candidates:
        item_id = str(candidate["id"])
        batch_id = str(candidate["batch_id"])
        chapter_slug = str(candidate["chapter_slug"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id::text, batch_id::text, chapter_slug, status, source_files, updated_at
                    FROM scraper_batch_items
                    WHERE id=$1::uuid
                    FOR UPDATE
                    """,
                    item_id,
                )
                if (
                    row is None
                    or row["status"] not in {"failed_conflict", "failed_error"}
                    or not (row["source_files"] or [])
                ):
                    continue
                still_old = await conn.fetchval(
                    "SELECT $2::timestamptz < NOW() - ($1::int * INTERVAL '1 hour')",
                    ttl_hours,
                    row["updated_at"],
                )
                if not still_old:
                    continue
                active = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM scraper_storage_attempts
                        WHERE batch_item_id=$1::uuid AND status='active'
                    )
                    """,
                    item_id,
                )
                if active:
                    continue
                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=item_id,
                    local_prefix=f"_scraper/batches/{batch_id}/{chapter_slug}",
                    reason=f"batch_staging_retention_expired_after_{ttl_hours}h",
                )
                await conn.execute(
                    """
                    UPDATE scraper_batch_items
                    SET status='discarded', source_files='[]'::jsonb,
                        overwrite_requested_at=NULL, processing_heartbeat_at=NULL,
                        error_message=$2, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    item_id,
                    f"Local staged files expired after configured {ttl_hours}h retention; cleanup job {cleanup_job_id} queued.",
                )
                await conn.execute(
                    """
                    UPDATE scraper_batch_uploads b
                    SET status=CASE
                        WHEN EXISTS (
                            SELECT 1 FROM scraper_batch_items i
                            WHERE i.batch_id=b.id AND i.status IN ('queued','processing')
                        ) THEN 'processing'
                        WHEN EXISTS (
                            SELECT 1 FROM scraper_batch_items i
                            WHERE i.batch_id=b.id AND i.status IN ('failed_conflict','failed_error')
                        ) THEN 'needs_attention'
                        WHEN NOT EXISTS (
                            SELECT 1 FROM scraper_batch_items i
                            WHERE i.batch_id=b.id AND i.status NOT IN ('completed','discarded')
                        ) THEN 'completed'
                        ELSE b.status
                    END,
                    updated_at=NOW()
                    WHERE b.id=$1::uuid
                    """,
                    batch_id,
                )
                expired += 1

    return expired


async def wait_for_staging_cleanup(
    pool: asyncpg.Pool,
    *,
    entity_id: str,
    requested_prefix: str,
) -> None:
    """Do not restage into a path that an older durable cleanup may still delete."""
    requested = str(requested_prefix).replace("\\", "/").lstrip("/").rstrip("/")
    timeout = max(1.0, float(settings.scraper_staging_cleanup_wait_seconds))
    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text, status, payload, last_error
                FROM lifecycle_cleanup_jobs
                WHERE entity_type='scraper_staging'
                  AND entity_id=$1::uuid
                  AND status IN ('queued','processing','retry','failed')
                ORDER BY created_at
                """,
                entity_id,
            )
        blockers: list[asyncpg.Record] = []
        for row in rows:
            prefixes = [
                str(value).replace("\\", "/").lstrip("/").rstrip("/")
                for value in ((row["payload"] or {}).get("local_staging_prefixes") or [])
            ]
            if any(
                requested == prefix
                or requested.startswith(prefix + "/")
                or prefix.startswith(requested + "/")
                for prefix in prefixes
                if prefix
            ):
                blockers.append(row)

        if not blockers:
            return
        failed = next((row for row in blockers if row["status"] == "failed"), None)
        if failed is not None:
            raise StagingCleanupFailed(
                "A previous staging cleanup failed and must be retried before restaging: "
                f"job={failed['id']} error={failed['last_error'] or 'unknown'}"
            )
        if asyncio.get_running_loop().time() >= deadline:
            raise StagingCleanupPending(
                "A previous staging cleanup is still in progress. Retry after the lifecycle worker completes it."
            )
        await asyncio.sleep(0.5)
