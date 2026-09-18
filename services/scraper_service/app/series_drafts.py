import asyncio
import json
import mimetypes
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import asyncpg
import httpx
from fastapi import HTTPException, UploadFile

from app.adapters.manga import MangaSeriesManifest
from app.adapters.generic_manga import _slugify
from app.adapters.manga_registry import manga_registry
from app.config import settings
from app.chapter_identity import chapter_slug_from_number, normalize_chapter_number
from app.catalog_series import ensure_catalog_series
from app.ingestion import (
    MediaSubmission,
    media_job_status,
    submit_series_cover_to_media,
    submit_to_media,
    wait_for_media_job_completion,
    wait_for_media_publication,
)
from app.publication_bridge import (
    build_staged_chapter_archive,
    cancel_ingestion_operation_tx,
    ensure_ingestion_operation,
    recover_ingestion_operation_lease_tx,
)
from app.operation_events import record_operation_event
from app.queueing import enqueue_unique, queue_depth, queue_position, remove_pending
from app.fetcher import browser_fallback_available, fetch_html, fetch_image
from app.recursive_discovery import build_fallback_manifest, recursive_chapter_discovery
from app.resilience import TransientPublishDeferred, is_transient_error, transient_message
from app.staging_store import (
    StagedObjectMissing,
    content_type_for_path,
    find_staging_by_prefix,
    get_object,
    put_object,
    put_upload_object,
    staging_exists,
    staging_root,
)
from app.storage_attempts import enqueue_local_staging_cleanup, wait_for_staging_cleanup
from app.source_api import (
    discover_atsu_manifest,
    discover_naver_manifest,
    fetch_atsu_chapter_pages,
    is_atsu_url,
    is_naver_url,
    naver_mobile_url,
)


DISCOVERY_QUEUE = "mreader.scraper.discovery"
STAGE_QUEUE = "mreader.scraper.stage"
PUBLISH_QUEUE = "mreader.scraper.publish"
CHAPTER_PUBLISH_QUEUE = "mreader.scraper.chapter-publish"
MAX_PAGE_BYTES = 50 * 1024 * 1024
MAX_CHAPTER_PAGES = 1000
DOWNLOAD_CONCURRENCY = max(1, settings.scraper_image_download_concurrency)


def _source_operation_key(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/")
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{host}{path}" + (f"?{parsed.query}" if parsed.query else "")


async def _fetch_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    force_browser: bool = False,
    browser_scroll: bool = False,
) -> tuple[str, bytes]:
    fetched = await fetch_html(
        client,
        url=url,
        max_bytes=settings.scraper_max_response_bytes,
        force_browser=force_browser,
        browser_scroll=browser_scroll,
    )
    return fetched.final_url, fetched.content


def _extension(
    content_type: str,
    source_url: str,
) -> str:
    guessed = mimetypes.guess_extension(
        content_type.split(";")[0].strip()
    )

    if guessed == ".jpe":
        guessed = ".jpg"

    if guessed:
        return guessed.lstrip(".")

    suffix = PurePosixPath(
        source_url.split("?", 1)[0]
    ).suffix.lower()

    if suffix:
        return suffix.lstrip(".")

    return "img"


async def _put(
    client: httpx.AsyncClient,
    path: str,
    data: bytes,
    content_type: str,
) -> None:
    await put_object(client, path, data, content_type)


async def _get(
    client: httpx.AsyncClient,
    path: str,
) -> tuple[bytes, str]:
    try:
        return await get_object(client, path)
    except StagedObjectMissing as exc:
        raise HTTPException(404, "Staged image not found.") from exc


async def _download_image(
    client: httpx.AsyncClient,
    *,
    url: str,
    referer: str | None = None,
) -> tuple[bytes, str]:
    fetched = await fetch_image(
        client,
        url=url,
        referer=referer,
        max_bytes=MAX_PAGE_BYTES,
    )
    return fetched.content, fetched.content_type


async def _get_staged_image(
    client: httpx.AsyncClient,
    *,
    path: str,
    label: str,
) -> tuple[bytes, str]:
    """Read one object from the canonical staging PVC; never reconstruct it."""
    try:
        return await get_object(client, path)
    except StagedObjectMissing as missing:
        raise RuntimeError(
            f"{label} is missing from the canonical scraper staging PVC. "
            f"logical_path={path}; container_root={staging_root()}. Re-stage or re-upload this item."
        ) from missing


async def _validate_publish_staging(
    pool: asyncpg.Pool,
    draft_id: str,
) -> None:
    """Fail publication before creating production rows if any staged file is missing."""
    async with pool.acquire() as conn:
        draft = await conn.fetchrow(
            "SELECT cover_staging_path FROM scraper_series_drafts WHERE id=$1::uuid",
            draft_id,
        )
        chapters = await conn.fetch(
            """
            SELECT id::text, chapter_number::text, pages
            FROM scraper_series_draft_chapters
            WHERE draft_id=$1::uuid AND selected=true AND published_chapter_id IS NULL
              AND stage_status='ready'
            ORDER BY chapter_number NULLS LAST, id
            """,
            draft_id,
        )
    missing: list[str] = []
    if draft and draft["cover_staging_path"] and not await staging_exists(draft["cover_staging_path"]):
        missing.append(str(draft["cover_staging_path"]))
    for chapter in chapters:
        for page in sorted(list(chapter["pages"] or []), key=lambda value: value.get("order", 0)):
            path = str(page.get("staging_path") or "").strip()
            if path and not await staging_exists(path):
                missing.append(path)
    if missing:
        raise RuntimeError(
            "Publish staging preflight failed: PostgreSQL references files missing from the canonical scraper PVC. "
            f"Re-stage/re-upload before publishing. missing_examples={missing[:5]}"
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace_headers(operation_id: str, request_id: str | None = None) -> dict[str, str]:
    headers = {"X-MReader-Operation-ID": operation_id}
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


class OperationCancellationRequested(Exception):
    pass


_CANCEL_POLL_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}


def _cached_cancel_value(kind: str, draft_id: str) -> bool | None:
    item = _CANCEL_POLL_CACHE.get((kind, draft_id))
    if item is None:
        return None
    checked_at, value = item
    ttl = max(0.0, float(settings.scraper_db_poll_min_interval_seconds))
    if value or (time.monotonic() - checked_at) <= ttl:
        return value
    _CANCEL_POLL_CACHE.pop((kind, draft_id), None)
    return None


def _store_cancel_value(kind: str, draft_id: str, value: bool) -> bool:
    _CANCEL_POLL_CACHE[(kind, draft_id)] = (time.monotonic(), bool(value))
    return bool(value)


async def _is_operation_cancel_requested(pool: asyncpg.Pool, draft_id: str) -> bool:
    cached = _cached_cancel_value("operation", draft_id)
    if cached is not None:
        return cached
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            """
            SELECT operation_cancel_requested_at IS NOT NULL
            FROM scraper_series_drafts
            WHERE id = $1::uuid
            """,
            draft_id,
        )
    # A deleted draft is also a hard stop signal for any in-flight worker.
    return _store_cancel_value("operation", draft_id, value is None or bool(value))


async def _raise_if_operation_cancelled(pool: asyncpg.Pool, draft_id: str) -> None:
    if await _is_operation_cancel_requested(pool, draft_id):
        raise OperationCancellationRequested()


async def _find_exact_existing_series(
    pool: asyncpg.Pool,
    *,
    title: str,
    discovered_slug: str,
) -> dict | None:
    title_key = " ".join(title.strip().lower().split())
    title_slug = _slugify(title)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text, title, slug
            FROM series
            WHERE regexp_replace(lower(btrim(title)), '\\s+', ' ', 'g') = $1
               OR lower(slug) = lower($2)
               OR lower(slug) = lower($3)
            ORDER BY CASE
                WHEN regexp_replace(lower(btrim(title)), '\\s+', ' ', 'g') = $1 THEN 0
                WHEN lower(slug) = lower($3) THEN 1
                ELSE 2
            END
            LIMIT 1
            """,
            title_key,
            discovered_slug,
            title_slug,
        )
    return dict(row) if row is not None else None


def _canonical_series_operation_state(workflow_status: str) -> tuple[str, str]:
    """Map editable workflow detail into the canonical parent operation state."""
    mapping = {
        "queued_discovery": ("queued", "discovery"),
        "discovering": ("running", "discovery"),
        "draft": ("needs_review", "review"),
        "ready": ("needs_review", "review"),
        "staging": ("running", "staging"),
        "queued_publish": ("queued", "publish"),
        "publishing": ("running", "publish"),
        "published": ("completed", "completed"),
        "published_partial": ("completed_with_errors", "completed"),
        "cancel_requested": ("cancel_requested", "cancel_requested"),
        "cancelled": ("cancelled", "cancelled"),
        "duplicate": ("failed", "duplicate"),
        "failed": ("failed", "failed"),
    }
    return mapping.get(workflow_status, ("needs_review", workflow_status or "review"))


async def _sync_series_ingestion_operation_tx(
    conn: asyncpg.Connection,
    draft_id: str,
) -> dict | None:
    """Persist one canonical new-series parent header from coordinator state.

    The legacy draft remains editable workflow detail.  This header is the
    user-visible/cancellation projection and is updated in the same coordinator
    transactions as the workflow transitions that call this helper.
    """
    source_kind = "new-series-scrape"
    row = await conn.fetchrow(
        """
        SELECT
            d.created_by::text AS requesting_actor_id,
            d.workflow_status,
            d.operation_cancel_requested_at,
            d.acknowledged_at,
            COUNT(c.id) FILTER (WHERE c.selected)::int AS selected_count,
            COUNT(c.id) FILTER (
                WHERE c.selected AND c.stage_status IN ('ready','published')
            )::int AS staged_count,
            COUNT(c.id) FILTER (
                WHERE c.publish_status='published' OR c.published_chapter_id IS NOT NULL
            )::int AS published_count,
            COUNT(c.id) FILTER (
                WHERE c.stage_status='error' OR c.publish_status IN ('failed','skipped')
            )::int AS failed_count
        FROM scraper_series_drafts d
        LEFT JOIN scraper_series_draft_chapters c ON c.draft_id=d.id
        WHERE d.id=$1::uuid
        GROUP BY d.id
        """,
        draft_id,
    )
    if row is None:
        return None

    value = dict(row)
    status, phase = _canonical_series_operation_state(str(value["workflow_status"] or ""))
    if value.get("operation_cancel_requested_at") is not None and status != "cancelled":
        status, phase = "cancel_requested", "cancel_requested"
    error_code = None
    if status == "failed":
        error_code = str(value["workflow_status"] or "failed")[:96]
    elif status == "completed_with_errors":
        error_code = "partial_result"

    existing = await conn.fetchrow(
        """
        SELECT source_kind,requesting_actor_id::text
        FROM ingestion_operations
        WHERE id=$1::uuid
        FOR UPDATE
        """,
        draft_id,
    )
    if existing is None:
        result = await conn.fetchrow(
            """
            INSERT INTO ingestion_operations(
                id,source_kind,requesting_actor_id,status,phase,
                source_revision,revision,lease_generation,
                selected_count,staged_count,published_count,failed_count,
                cancel_requested_at,acknowledged_at,error_code
            ) VALUES(
                $1::uuid,$2,$3::uuid,$4,$5,1,1,1,$6,$7,$8,$9,$10,$11,$12
            )
            RETURNING id::text,source_kind,requesting_actor_id::text,status,phase,
                      revision,lease_generation,selected_count,staged_count,
                      published_count,failed_count,cancel_requested_at,acknowledged_at,error_code
            """,
            draft_id,
            source_kind,
            value["requesting_actor_id"],
            status,
            phase,
            int(value["selected_count"] or 0),
            int(value["staged_count"] or 0),
            int(value["published_count"] or 0),
            int(value["failed_count"] or 0),
            value.get("operation_cancel_requested_at"),
            value.get("acknowledged_at"),
            error_code,
        )
        return dict(result)

    if existing["source_kind"] != source_kind:
        raise RuntimeError("series draft operation id is owned by another ingestion source")
    if str(existing["requesting_actor_id"]) != str(value["requesting_actor_id"]):
        raise RuntimeError("series draft operation is owned by another requesting actor")

    result = await conn.fetchrow(
        """
        UPDATE ingestion_operations
        SET status=$2,phase=$3,revision=revision+1,
            selected_count=$4,staged_count=$5,published_count=$6,failed_count=$7,
            cancel_requested_at=$8,acknowledged_at=$9,error_code=$10,updated_at=NOW()
        WHERE id=$1::uuid
        RETURNING id::text,source_kind,requesting_actor_id::text,status,phase,
                  revision,lease_generation,selected_count,staged_count,
                  published_count,failed_count,cancel_requested_at,acknowledged_at,error_code
        """,
        draft_id,
        status,
        phase,
        int(value["selected_count"] or 0),
        int(value["staged_count"] or 0),
        int(value["published_count"] or 0),
        int(value["failed_count"] or 0),
        value.get("operation_cancel_requested_at"),
        value.get("acknowledged_at"),
        error_code,
    )
    return dict(result)


async def _finalize_cancelled_operation(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    draft_id: str,
) -> None:
    """Finalize cancellation while making storage cleanup durable."""
    cleanup_job_id: str | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT operation_cancel_requested_by::text
                FROM scraper_series_drafts
                WHERE id = $1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if row is None:
                return

            await conn.execute(
                """
                UPDATE scraper_series_draft_chapters
                SET
                    stage_status = CASE
                        WHEN published_chapter_id IS NOT NULL THEN 'published'
                        ELSE 'cancelled'
                    END,
                    pages = '[]'::jsonb,
                    stage_finished_at = CASE
                        WHEN published_chapter_id IS NULL THEN COALESCE(stage_finished_at, NOW())
                        ELSE stage_finished_at
                    END,
                    stage_worker_heartbeat_at = NULL,
                    publish_status = CASE
                        WHEN published_chapter_id IS NOT NULL THEN 'published'
                        WHEN publish_status IN ('pending','publishing') THEN 'cancelled'
                        ELSE publish_status
                    END,
                    publish_error = CASE
                        WHEN published_chapter_id IS NULL
                             AND publish_status IN ('pending','publishing')
                        THEN 'Scraper operation was cancelled by the administrator.'
                        ELSE publish_error
                    END,
                    publish_finished_at = CASE
                        WHEN published_chapter_id IS NULL
                             AND publish_status IN ('pending','publishing')
                        THEN NOW()
                        ELSE publish_finished_at
                    END,
                    stage_progress = CASE
                        WHEN published_chapter_id IS NULL THEN
                            COALESCE(stage_progress,'{}'::jsonb) || jsonb_build_object(
                                'phase','cancelled','percent',100,
                                'message','Staging cancelled; local page references cleared.',
                                'updated_at',NOW()
                            )
                        ELSE stage_progress
                    END,
                    queue_dispatched_at = NULL,
                    updated_at = NOW()
                WHERE draft_id = $1::uuid
                """,
                draft_id,
            )

            cleanup_job_id = await enqueue_local_staging_cleanup(
                conn,
                entity_id=draft_id,
                local_prefix=f"_scraper/series-drafts/{draft_id}",
                reason="scraper_operation_cancelled",
            )

            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET
                    workflow_status = 'cancelled',
                    cover_staging_path = NULL,
                    queue_dispatched_at = NULL,
                    discovery_worker_heartbeat_at = NULL,
                    publish_worker_heartbeat_at = NULL,
                    publish_finished_at = COALESCE(publish_finished_at, NOW()),
                    publish_progress = COALESCE(publish_progress, '{}'::jsonb)
                        || jsonb_build_object(
                            'phase','cancelled',
                            'percent',100,
                            'message','Operation cancelled. Staging cleanup is durably queued.',
                            'cleanup_job_id',$2::text,
                            'updated_at',NOW()
                        ),
                    error_message = 'Operation cancelled by the administrator.',
                    acknowledged_at = COALESCE(acknowledged_at, NOW()),
                    acknowledged_by = COALESCE(acknowledged_by, operation_cancel_requested_by),
                    updated_at = NOW()
                WHERE id = $1::uuid
                  AND operation_cancel_requested_at IS NOT NULL
                """,
                draft_id,
                cleanup_job_id,
            )
            await _sync_series_ingestion_operation_tx(conn, draft_id)

    await record_operation_event(
        pool,
        operation_id=draft_id,
        service="scraper-worker",
        event_type="operation_cancelled",
        phase="cancelled",
        status="cancelled",
        message="Operation cancellation finalized; cleanup is durable and retryable.",
        metadata={"cleanup_job_id": cleanup_job_id},
    )

async def _project_canonical_chapter_outcome_tx(
    conn: asyncpg.Connection,
    chapter_id: str,
    outcome: dict | None,
) -> str:
    """Project canonical ingestion authority back into the legacy draft row."""
    if not outcome:
        return "missing"

    canonical_status = str(outcome.get("status") or "")
    published_chapter_id = str(outcome.get("chapter_id") or "").strip()
    if outcome.get("committed") and published_chapter_id:
        await conn.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET published_chapter_id=$2::uuid,stage_status='published',publish_status='published',
                publish_error=NULL,publish_finished_at=COALESCE(publish_finished_at,NOW()),updated_at=NOW()
            WHERE id=$1::uuid
            """,
            chapter_id,
            published_chapter_id,
        )
        return "committed"

    if canonical_status == "cancelled":
        await conn.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET publish_status=CASE WHEN published_chapter_id IS NULL THEN 'cancelled' ELSE publish_status END,
                publish_error=CASE WHEN published_chapter_id IS NULL
                    THEN COALESCE(publish_error,'Canonical ingestion operation was cancelled.')
                    ELSE publish_error END,
                publish_finished_at=CASE WHEN published_chapter_id IS NULL
                    THEN COALESCE(publish_finished_at,NOW()) ELSE publish_finished_at END,
                queue_dispatched_at=NULL,updated_at=NOW()
            WHERE id=$1::uuid
            """,
            chapter_id,
        )
        return "cancelled"

    if outcome.get("recovered"):
        await conn.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET publish_status=CASE WHEN published_chapter_id IS NULL THEN 'pending' ELSE publish_status END,
                publish_error=NULL,queue_dispatched_at=NULL,updated_at=NOW()
            WHERE id=$1::uuid
            """,
            chapter_id,
        )
        return "recovered"

    if canonical_status in {"completed", "completed_with_errors", "failed"}:
        return "terminal"
    return canonical_status or "current"


async def _cancel_draft_chapter_publications_tx(
    conn: asyncpg.Connection,
    draft_id: str,
) -> list[dict]:
    """Fence every canonical chapter publication before legacy draft cancellation."""
    rows = await conn.fetch(
        """
        SELECT id::text
        FROM scraper_series_draft_chapters
        WHERE draft_id=$1::uuid
        ORDER BY id
        """,
        draft_id,
    )
    outcomes: list[dict] = []
    for row in rows:
        chapter_id = str(row["id"])
        outcome = await cancel_ingestion_operation_tx(conn, chapter_id)
        projection = await _project_canonical_chapter_outcome_tx(conn, chapter_id, outcome)
        outcomes.append({"chapter_id": chapter_id, "projection": projection, "outcome": outcome})
    return outcomes


async def _recover_draft_chapter_publication_tx(
    conn: asyncpg.Connection,
    chapter_id: str,
) -> str:
    outcome = await recover_ingestion_operation_lease_tx(conn, chapter_id)
    return await _project_canonical_chapter_outcome_tx(conn, chapter_id, outcome)


async def cancel_scraper_operation(
    pool: asyncpg.Pool,
    redis,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    admin_id: str,
    request_id: str | None = None,
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id::text, workflow_status
                FROM scraper_series_drafts
                WHERE id = $1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if row is None:
                raise HTTPException(404, "Scraper operation not found.")

            chapter_rows = await conn.fetch(
                """
                SELECT id::text, publish_status, publish_progress
                FROM scraper_series_draft_chapters
                WHERE draft_id = $1::uuid
                """,
                draft_id,
            )
            await cancel_ingestion_operation_tx(conn, draft_id)
            await _cancel_draft_chapter_publications_tx(conn, draft_id)
            previous_status = row["workflow_status"]
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET
                    operation_cancel_requested_at = COALESCE(operation_cancel_requested_at, NOW()),
                    operation_cancel_requested_by = $2::uuid,
                    publish_cancel_requested_at = CASE
                        WHEN workflow_status IN ('queued_publish','publishing')
                        THEN COALESCE(publish_cancel_requested_at, NOW())
                        ELSE publish_cancel_requested_at
                    END,
                    workflow_status = 'cancel_requested',
                    error_message = 'Operation cancellation requested by the administrator.',
                    acknowledged_at = COALESCE(acknowledged_at, NOW()),
                    acknowledged_by = COALESCE(acknowledged_by, $2::uuid),
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                draft_id,
                admin_id,
            )
            await _sync_series_ingestion_operation_tx(conn, draft_id)

    await record_operation_event(
        pool,
        operation_id=draft_id,
        request_id=request_id,
        service="scraper-api",
        event_type="operation_cancel_requested",
        phase="cancel_requested",
        status="cancel_requested",
        message="Administrator requested operation-wide cancellation; the operation is archived from the default dashboard while workers stop safely.",
        metadata={"previous_status": previous_status},
    )

    # RabbitMQ messages are compact durable references. remove_pending is O(1)
    # and intentionally may be a no-op; workers always re-check PostgreSQL.
    try:
        await remove_pending(redis, DISCOVERY_QUEUE, draft_id)
        await remove_pending(redis, PUBLISH_QUEUE, draft_id)
        for chapter in chapter_rows:
            await remove_pending(redis, STAGE_QUEUE, chapter["id"])
            await remove_pending(redis, CHAPTER_PUBLISH_QUEUE, chapter["id"])
    except Exception:
        pass

    single_publish_active = any(
        chapter["publish_status"] == "publishing"
        and (chapter["publish_progress"] or {}).get("mode") == "single"
        for chapter in chapter_rows
    )
    active = (
        previous_status in {"discovering", "staging", "publishing"}
        or single_publish_active
    )
    if not active:
        await _finalize_cancelled_operation(pool, client, draft_id)

    return {
        "status": "cancel_requested" if active else "cancelled",
        "operation_id": draft_id,
        "removed_from_dashboard": True,
    }

async def _update_publish_progress(
    pool: asyncpg.Pool,
    draft_id: str,
    *,
    phase: str | None = None,
    percent: int | None = None,
    message: str | None = None,
    **fields,
) -> None:
    patch = {key: value for key, value in fields.items() if value is not None}
    if phase is not None:
        patch["phase"] = phase
    if percent is not None:
        patch["percent"] = max(0, min(100, int(percent)))
    if message is not None:
        patch["message"] = message
    patch["updated_at"] = _utc_now_iso()

    async with pool.acquire() as conn:
        previous = await conn.fetchrow(
            """
            SELECT
                COALESCE(publish_progress->>'phase','') AS phase,
                NULLIF(publish_progress->>'request_id','') AS request_id
            FROM scraper_series_drafts
            WHERE id=$1::uuid
            """,
            draft_id,
        )
        await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET publish_progress = COALESCE(publish_progress, '{}'::jsonb) || $2::jsonb,
                publish_worker_heartbeat_at = CASE
                    WHEN workflow_status='publishing' THEN NOW()
                    ELSE publish_worker_heartbeat_at
                END,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            json.dumps(patch),
        )
    previous_phase = previous["phase"] if previous else ""
    if phase and phase != previous_phase:
        await record_operation_event(
            pool,
            operation_id=draft_id,
            request_id=(previous["request_id"] if previous else None),
            service="scraper-worker",
            event_type="publish_phase",
            phase=phase,
            status="running" if phase not in {"completed", "completed_with_warnings", "completed_with_chapter_failures", "failed", "cancelled"} else phase,
            message=message or f"Publish phase changed to {phase}.",
            metadata={"percent": patch.get("percent")},
        )

async def _write_stage_progress(
    conn,
    chapter_id: str,
    patch: dict,
    fence: tuple[int | None, int | None],
):
    expected_revision, expected_stage_generation = fence
    previous = await conn.fetchrow(
        """
        SELECT
            draft_id::text,
            COALESCE(stage_progress->>'phase','') AS phase,
            NULLIF(stage_progress->>'request_id','') AS request_id
        FROM scraper_series_draft_chapters
        WHERE id=$1::uuid
          AND ($2::bigint IS NULL OR revision=$2::bigint)
          AND ($3::bigint IS NULL OR stage_generation=$3::bigint)
        """,
        chapter_id,
        expected_revision,
        expected_stage_generation,
    )
    await conn.execute(
        """
        UPDATE scraper_series_draft_chapters
        SET stage_progress = COALESCE(stage_progress, '{}'::jsonb) || $2::jsonb,
            stage_worker_heartbeat_at = NOW(),
            updated_at = NOW()
        WHERE id = $1::uuid
          AND ($3::bigint IS NULL OR revision=$3::bigint)
          AND ($4::bigint IS NULL OR stage_generation=$4::bigint)
        """,
        chapter_id,
        json.dumps(patch),
        expected_revision,
        expected_stage_generation,
    )
    return previous


async def _update_stage_progress(
    pool: asyncpg.Pool,
    chapter_id: str,
    *,
    phase: str,
    percent: int,
    message: str,
    **fields,
) -> None:
    fence = (
        fields.pop("expected_revision", None),
        fields.pop("expected_stage_generation", None),
    )
    patch = {
        "phase": phase,
        "percent": max(0, min(100, int(percent))),
        "message": message,
        "updated_at": _utc_now_iso(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    async with pool.acquire() as conn:
        previous = await _write_stage_progress(conn, chapter_id, patch, fence)
    if previous and phase != previous["phase"]:
        await record_operation_event(
            pool,
            operation_id=previous["draft_id"],
            chapter_id=chapter_id,
            request_id=previous["request_id"],
            service="scraper-worker",
            event_type="stage_phase",
            phase=phase,
            status="running" if phase not in {"completed", "failed", "cancelled"} else phase,
            message=message,
            metadata={"percent": patch.get("percent")},
        )


async def _invalidate_publish_caches(
    redis,
) -> list[str]:
    warnings: list[str] = []

    for scope in (
        "series",
        "chapter",
        "genres",
        "tags",
        "dashboard",
    ):
        cursor = 0
        pattern = f"cache:{scope}:*"

        try:
            while True:
                cursor, keys = await redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=200,
                )

                if keys:
                    await redis.delete(*keys)

                if cursor == 0:
                    break
        except Exception as exc:
            warnings.append(
                f"Cache invalidation failed for {scope}: {exc}"
            )

    return warnings


async def _get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    attempts: int = 3,
    params: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(
                url,
                params=params,
                headers=headers,
                timeout=15.0,
            )
            last_response = response

            if response.status_code == 200:
                return response

            if response.status_code not in {
                # Read-after-write verification can briefly see a stale 404
                # through service/cache layers immediately after publish.
                404,
                408,
                425,
                429,
                500,
                502,
                503,
                504,
            }:
                return response
        except Exception as exc:
            last_error = exc

        if attempt < attempts:
            await asyncio.sleep(0.5 * attempt)

    if last_response is not None:
        return last_response

    assert last_error is not None
    raise last_error


async def _verify_published_interfaces(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    slug: str,
    series_id: str,
    chapters: list[dict],
) -> dict:
    errors: list[str] = []
    catalog_verified = False
    catalog_verified_chapters = 0
    reader_verified_chapters = 0
    reader_verified_images = 0

    catalog_base = settings.catalog_internal_url.rstrip("/")
    reader_base = settings.reader_internal_url.rstrip("/")

    await _update_publish_progress(
        pool,
        draft_id,
        phase="verifying_catalog",
        percent=92,
        message="Production rows committed. Verifying Catalog API availability.",
        catalog_verified=False,
        catalog_verified_chapters=0,
        reader_verified_chapters=0,
        reader_verified_images=0,
        verification_errors=[],
    )

    try:
        response = await _get_with_retries(
            client,
            f"{catalog_base}/api/catalog/series/{quote(slug, safe='')}",
            params={
                "chapter_limit": min(
                    100,
                    max(1, len(chapters)),
                )
            },
            headers=_trace_headers(draft_id),
        )

        if response.status_code != 200:
            errors.append(
                f"Catalog series verification returned HTTP {response.status_code}."
            )
        else:
            body = response.json()
            if str(body.get("id")) != str(series_id):
                errors.append(
                    "Catalog returned the series slug but with an unexpected series id."
                )
            else:
                catalog_verified = True
    except Exception as exc:
        errors.append(
            f"Catalog series verification failed: {type(exc).__name__}: {exc}"
        )

    total_chapters = max(1, len(chapters))

    for index, chapter in enumerate(chapters, start=1):
        chapter_slug = chapter["chapter_slug"]

        # Verify Catalog's chapter endpoint separately. This also covers
        # series with more chapters than one Catalog detail page can return.
        try:
            response = await _get_with_retries(
                client,
                (
                    f"{catalog_base}/api/catalog/series/"
                    f"{quote(slug, safe='')}/chapters/"
                    f"{quote(chapter_slug, safe='')}"
                ),
                headers=_trace_headers(draft_id),
            )

            if response.status_code == 200:
                catalog_verified_chapters += 1
            else:
                errors.append(
                    (
                        f"Catalog chapter {chapter_slug} verification "
                        f"returned HTTP {response.status_code}."
                    )
                )
        except Exception as exc:
            errors.append(
                (
                    f"Catalog chapter {chapter_slug} verification failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            )

        await _update_publish_progress(
            pool,
            draft_id,
            phase="verifying_reader",
            percent=93 + int((index - 1) / total_chapters * 6),
            message=(
                f"Verifying Reader API for chapter "
                f"{index}/{len(chapters)} ({chapter_slug})."
            ),
            catalog_verified=catalog_verified,
            catalog_verified_chapters=catalog_verified_chapters,
            reader_verified_chapters=reader_verified_chapters,
            reader_verified_images=reader_verified_images,
            verification_errors=errors[-20:],
            current_chapter_slug=chapter_slug,
            current_chapter_number=str(chapter["chapter_number"]),
        )

        try:
            response = await _get_with_retries(
                client,
                (
                    f"{reader_base}/api/reader/"
                    f"{quote(slug, safe='')}/"
                    f"{quote(chapter_slug, safe='')}"
                ),
                headers=_trace_headers(draft_id),
            )

            if response.status_code != 200:
                errors.append(
                    (
                        f"Reader chapter {chapter_slug} verification "
                        f"returned HTTP {response.status_code}."
                    )
                )
                continue

            body = response.json()
            expected_pages = len(chapter["final_pages"])
            actual_pages = int(body.get("page_count") or 0)

            if actual_pages != expected_pages:
                errors.append(
                    (
                        f"Reader chapter {chapter_slug} page_count mismatch: "
                        f"expected {expected_pages}, got {actual_pages}."
                    )
                )
                continue

            reader_verified_chapters += 1

            # Verify storage availability through Reader's token/image route,
            # not merely that the DB manifest exists. Check both ends of a
            # multi-page chapter so a missing/truncated tail object is caught
            # without downloading every page during publish verification.
            pages = body.get("pages") or []
            if not pages:
                errors.append(
                    f"Reader manifest for {chapter_slug} did not return any pages."
                )
                continue

            sample_indexes = [0]
            if len(pages) > 1:
                sample_indexes.append(len(pages) - 1)

            image_samples_ok = True
            for sample_index in sample_indexes:
                page = pages[sample_index]
                image_path = str(page.get("image_path") or "")
                token = str(page.get("token") or "")

                if not image_path or not token:
                    errors.append(
                        (
                            f"Reader manifest for {chapter_slug} page "
                            f"{sample_index + 1} did not return an image path/token."
                        )
                    )
                    image_samples_ok = False
                    continue

                image_response = await _get_with_retries(
                    client,
                    (
                        f"{reader_base}/images/"
                        f"{quote(image_path, safe='/')}"
                    ),
                    params={"token": token},
                    headers=_trace_headers(draft_id),
                )

                if not (
                    image_response.status_code == 200
                    and len(image_response.content) > 0
                ):
                    errors.append(
                        (
                            f"Reader image verification for {chapter_slug} page "
                            f"{sample_index + 1} returned HTTP "
                            f"{image_response.status_code}."
                        )
                    )
                    image_samples_ok = False

            # Preserve the existing progress contract: this counter is one
            # successful Reader image verification unit per chapter.
            if image_samples_ok:
                reader_verified_images += 1
        except Exception as exc:
            errors.append(
                (
                    f"Reader chapter {chapter_slug} verification failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            )

    return {
        "catalog_verified": catalog_verified,
        "catalog_verified_chapters": catalog_verified_chapters,
        "reader_verified_chapters": reader_verified_chapters,
        "reader_verified_images": reader_verified_images,
        "verification_errors": errors[-50:],
    }


async def _update_discovery_progress(
    pool: asyncpg.Pool,
    draft_id: str,
    *,
    phase: str,
    percent: int,
    message: str,
    **fields,
) -> None:
    patch = {
        "phase": phase,
        "percent": max(0, min(100, int(percent))),
        "message": message,
        "updated_at": _utc_now_iso(),
        **{
            key: value
            for key, value in fields.items()
            if value is not None
        },
    }
    async with pool.acquire() as conn:
        previous_phase = await conn.fetchval(
            "SELECT COALESCE(discovery_progress->>'phase','') FROM scraper_series_drafts WHERE id=$1::uuid",
            draft_id,
        )
        await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET
                discovery_progress =
                    COALESCE(discovery_progress, '{}'::jsonb)
                    || $2::jsonb,
                discovery_worker_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            json.dumps(patch),
        )
    if phase != previous_phase:
        await record_operation_event(
            pool,
            operation_id=draft_id,
            service="scraper-worker",
            event_type="discovery_phase",
            phase=phase,
            status="running" if phase not in {"completed", "failed", "cancelled"} else phase,
            message=message,
            metadata={"percent": patch.get("percent")},
        )


async def queue_series_discovery(
    pool: asyncpg.Pool,
    redis,
    *,
    url: str,
    created_by: str,
    recursive: bool = True,
    max_depth: int = 1,
    max_pages: int = 20,
    request_id: str | None = None,
) -> dict:
    """Create one durable active operation per normalized source URL."""
    draft_id = str(uuid.uuid4())
    placeholder_slug = f"pending-{draft_id.replace('-', '')[:18]}"
    options = {"recursive": bool(recursive), "max_depth": int(max_depth), "max_pages": int(max_pages)}
    progress = {
        "phase": "queued", "percent": 0,
        "message": "Series discovery is queued and waiting for a worker.",
        "request_id": request_id or "", "updated_at": _utc_now_iso(),
    }
    source_key = _source_operation_key(url)
    existing_id: str | None = None

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Shared PostgreSQL lock works across API replicas/admin sessions.
            # Only the same normalized source URL contends on this lock.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"scraper-source:{source_key}",
            )
            existing_id = await conn.fetchval(
                """
                SELECT id::text
                FROM scraper_series_drafts
                WHERE source_url_key = $1
                  AND workflow_status NOT IN ('published','published_partial','failed','cancelled','duplicate')
                  AND acknowledged_at IS NULL
                ORDER BY created_at ASC
                LIMIT 1
                """,
                source_key,
            )
            if existing_id is None:
                await conn.execute(
                    """
                    INSERT INTO scraper_series_drafts (
                        id,source_url,source_url_key,adapter,title,slug,description,series_status,
                        genres,tags,workflow_status,error_message,created_by,discovery_options,discovery_progress
                    ) VALUES (
                        $1::uuid,$2,$3,'queued','Pending series discovery',$4,NULL,'ongoing',
                        '[]'::jsonb,'[]'::jsonb,'queued_discovery',NULL,$5::uuid,$6::jsonb,$7::jsonb
                    )
                    """,
                    draft_id, url, source_key, placeholder_slug, created_by,
                    json.dumps(options), json.dumps(progress),
                )
                await _sync_series_ingestion_operation_tx(conn, draft_id)

    if existing_id is not None:
        return await get_series_draft(pool, existing_id)

    await record_operation_event(
        pool, operation_id=draft_id, service="scraper-api",
        event_type="discovery_accepted", phase="queued", status="queued",
        message="Series discovery request committed to PostgreSQL.", request_id=request_id,
    )
    try:
        await enqueue_unique(
            redis, DISCOVERY_QUEUE, draft_id,
            payload={"operation_id": draft_id, "request_id": request_id or ""},
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_series_drafts SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_discovery'",
                draft_id,
            )
    except Exception as exc:
        await _update_discovery_progress(
            pool, draft_id, phase="queued_recovery", percent=0,
            message="Discovery is durable in PostgreSQL and will be requeued when the broker/worker recovers.",
            queue_error=f"{type(exc).__name__}: {exc}"[:1000],
        )
    return await get_series_draft(pool, draft_id)


async def run_series_discovery(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    draft_id: str,
) -> None:
    """Execute one queued series discovery into its already-persisted draft."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id::text,
                source_url,
                workflow_status,
                discovery_options,
                operation_cancel_requested_at,
                created_by::text
            FROM scraper_series_drafts
            WHERE id = $1::uuid
            """,
            draft_id,
        )

    if row is None or row["workflow_status"] not in {
        "queued_discovery",
        "discovering",
    } or row["operation_cancel_requested_at"] is not None:
        return

    options = dict(row["discovery_options"] or {})
    recursive = bool(options.get("recursive", True))
    max_depth = max(0, min(3, int(options.get("max_depth", 1))))
    max_pages = max(1, min(50, int(options.get("max_pages", 20))))
    source_url = row["source_url"]

    async with pool.acquire() as conn:
        claimed = await conn.fetchval(
            """
            UPDATE scraper_series_drafts
            SET
                workflow_status = 'discovering',
                discovery_attempt = discovery_attempt + 1,
                discovery_started_at = COALESCE(discovery_started_at, NOW()),
                discovery_worker_heartbeat_at = NOW(),
                error_message = NULL,
                discovery_progress = discovery_progress || $2::jsonb,
                updated_at = NOW()
            WHERE id = $1::uuid
              AND workflow_status = 'queued_discovery'
              AND operation_cancel_requested_at IS NULL
            RETURNING id::text
            """,
            draft_id,
            json.dumps({
                "phase": "starting",
                "percent": 2,
                "message": "Scraper worker accepted the series discovery job.",
                "updated_at": _utc_now_iso(),
            }),
        )
        if claimed is not None:
            await _sync_series_ingestion_operation_tx(conn, draft_id)
    if claimed is None:
        return

    discovery = {
        "recursive_requested": bool(recursive),
        "recursive": None,
        "source_strategy": None,
    }
    cover_path: str | None = None

    try:
        # A previous failed discovery may have queued cleanup for an old cover.
        # Never write a replacement into a prefix that a delayed cleanup job can
        # still remove underneath the active worker.
        await wait_for_staging_cleanup(
            pool,
            entity_id=draft_id,
            requested_prefix=f"_scraper/series-drafts/{draft_id}",
        )
        await _raise_if_operation_cancelled(pool, draft_id)
        await _update_discovery_progress(
            pool,
            draft_id,
            phase="fetching_series",
            percent=8,
            message="Fetching the series source page/API.",
        )

        if is_atsu_url(source_url):
            final_url = source_url
            manifest = await discover_atsu_manifest(client, source_url)
            adapter_name = "atsu-api"
            discovery["source_strategy"] = "public-json-api"
            await _update_discovery_progress(
                pool,
                draft_id,
                phase="extracting_manifest",
                percent=45,
                message="Series metadata and chapter list were returned by the source API.",
                source_strategy=discovery["source_strategy"],
                chapters_found=len(manifest.chapters),
            )
            await _raise_if_operation_cancelled(pool, draft_id)
            # Existing production series continue through the common update
            # path below. Only chapter numbers missing from production are
            # retained in this draft.
        elif is_naver_url(source_url):
            # Naver's list page is client-rendered. Prefer its public JSON
            # endpoint instead of paying for Chromium just to discover chapters.
            try:
                final_url = source_url
                manifest = await discover_naver_manifest(client, source_url)
                adapter_name = "naver-public-api"
                discovery["source_strategy"] = "public-json-api"
                await _update_discovery_progress(
                    pool, draft_id, phase="extracting_manifest", percent=45,
                    message="Naver metadata and episode list were returned by its public JSON endpoint.",
                    source_strategy=discovery["source_strategy"],
                    chapters_found=len(manifest.chapters),
                )
                await _raise_if_operation_cancelled(pool, draft_id)
                # Existing production series are valid update targets. The
                # shared filter below removes chapter numbers already live.
            except HTTPException as api_error:
                # Compatibility fallback if Naver changes or temporarily rejects
                # the public data endpoint. Preserve the old HTML/mobile/browser path.
                await _update_discovery_progress(
                    pool, draft_id, phase="source_fallback", percent=18,
                    message=f"Naver public API unavailable ({api_error.detail}); falling back to HTML rendering.",
                )
                final_url, raw = await _fetch_html(client, source_url)
                html = raw.decode("utf-8", errors="replace")
                adapter = manga_registry.resolve(final_url)
                adapter_name = adapter.name
                discovery["source_strategy"] = "html-adapter"
                manifest = None
                try:
                    manifest = adapter.extract_series_manifest(final_url, html)
                except ValueError:
                    pass
                if manifest is None:
                    mobile = naver_mobile_url(final_url)
                    if mobile != final_url:
                        try:
                            final_url, raw = await _fetch_html(client, mobile)
                            html = raw.decode("utf-8", errors="replace")
                            adapter = manga_registry.resolve(final_url)
                            adapter_name = adapter.name
                            manifest = adapter.extract_series_manifest(final_url, html)
                            discovery["source_strategy"] = "naver-mobile-html"
                        except Exception:
                            manifest = None
                if manifest is None and browser_fallback_available():
                    final_url, raw = await _fetch_html(
                        client, source_url, force_browser=True, browser_scroll=True
                    )
                    html = raw.decode("utf-8", errors="replace")
                    adapter = manga_registry.resolve(final_url)
                    adapter_name = adapter.name
                    manifest = adapter.extract_series_manifest(final_url, html)
                    discovery["source_strategy"] = "scrapling-browser-render"
                if manifest is None:
                    raise api_error
        else:
            final_url, raw = await _fetch_html(client, source_url)
            html = raw.decode("utf-8", errors="replace")
            adapter = manga_registry.resolve(final_url)
            adapter_name = adapter.name
            discovery["source_strategy"] = "html-adapter"

            await _update_discovery_progress(
                pool,
                draft_id,
                phase="extracting_manifest",
                percent=25,
                message=f"Parsing source with the {adapter_name} adapter.",
                adapter=adapter_name,
            )

            original_error: Exception | None = None
            manifest: MangaSeriesManifest | None = None

            try:
                manifest = adapter.extract_series_manifest(final_url, html)
            except ValueError as exc:
                original_error = exc

            if manifest is None and is_naver_url(final_url):
                mobile = naver_mobile_url(final_url)
                if mobile != final_url:
                    try:
                        await _update_discovery_progress(
                            pool,
                            draft_id,
                            phase="source_fallback",
                            percent=32,
                            message="Desktop source is client-rendered; retrying its public mobile representation.",
                        )
                        final_url, raw = await _fetch_html(client, mobile)
                        html = raw.decode("utf-8", errors="replace")
                        adapter = manga_registry.resolve(final_url)
                        manifest = adapter.extract_series_manifest(final_url, html)
                        adapter_name = adapter.name
                        discovery["source_strategy"] = "naver-mobile-html"
                    except Exception as exc:
                        original_error = exc
                        manifest = None

            # Generic JS-render fallback. Static HTML can be a perfectly valid
            # 200 response yet contain only an application shell. Re-render
            # once in Chromium before declaring the source unsupported.
            if manifest is None and browser_fallback_available():
                try:
                    await _update_discovery_progress(
                        pool,
                        draft_id,
                        phase="browser_render_fallback",
                        percent=36,
                        message="Static parsing found no chapter manifest; rendering the page once with Chromium.",
                    )
                    final_url, raw = await _fetch_html(
                        client,
                        final_url,
                        force_browser=True,
                        browser_scroll=True,
                    )
                    html = raw.decode("utf-8", errors="replace")
                    adapter = manga_registry.resolve(final_url)
                    adapter_name = adapter.name
                    manifest = adapter.extract_series_manifest(final_url, html)
                    discovery["source_strategy"] = "scrapling-browser-render"
                except Exception as exc:
                    original_error = exc
                    manifest = None

            await _raise_if_operation_cancelled(pool, draft_id)
            should_recursive = recursive and (
                manifest is None
                or adapter.name in {"generic-manga", "naver-webtoon"}
            )
            if should_recursive:
                shell = manifest or build_fallback_manifest(
                    series_url=final_url,
                    html=html,
                    chapters=[],
                )
                try:
                    await _update_discovery_progress(
                        pool,
                        draft_id,
                        phase="recursive_discovery",
                        percent=42,
                        message=(
                            "Scanning bounded same-site index/pagination pages "
                            "for additional chapters."
                        ),
                        max_depth=max_depth,
                        max_pages=max_pages,
                    )
                    recursive_chapters, crawl_meta = await recursive_chapter_discovery(
                        client,
                        series_url=final_url,
                        first_html=html,
                        series_title=shell.series.title,
                        max_depth=max_depth,
                        max_pages=max_pages,
                        cancel_check=lambda: _raise_if_operation_cancelled(pool, draft_id),
                    )
                    discovery["recursive"] = crawl_meta

                    if recursive_chapters:
                        if manifest is None:
                            manifest = build_fallback_manifest(
                                series_url=final_url,
                                html=html,
                                chapters=recursive_chapters,
                            )
                            adapter_name = f"{adapter.name}+recursive"
                            discovery["source_strategy"] = "bounded-recursive-html"
                        else:
                            merged = {
                                chapter.chapter_number: chapter
                                for chapter in manifest.chapters
                            }
                            before = len(merged)
                            for chapter in recursive_chapters:
                                merged.setdefault(chapter.chapter_number, chapter)
                            if len(merged) > before:
                                manifest = MangaSeriesManifest(
                                    series=manifest.series,
                                    genres=manifest.genres,
                                    tags=manifest.tags,
                                    chapters=sorted(
                                        merged.values(),
                                        key=lambda chapter: float(chapter.chapter_number),
                                    ),
                                )
                                discovery["source_strategy"] = (
                                    f"{discovery['source_strategy']}+recursive"
                                )
                except Exception as exc:
                    discovery["recursive"] = {
                        "enabled": True,
                        "max_depth": max_depth,
                        "max_pages": max_pages,
                        "pages_fetched": 0,
                        "visited": 0,
                        "chapters_found": 0,
                        "errors": [f"{type(exc).__name__}: {exc}"],
                    }
                    if manifest is None:
                        original_error = exc

            await _raise_if_operation_cancelled(pool, draft_id)
            if manifest is None or not manifest.chapters:
                detail = str(original_error) if original_error else (
                    "No chapter links were discovered on the series page. "
                    "Try recursive discovery or a source-specific adapter."
                )
                raise RuntimeError(detail)

        await _raise_if_operation_cancelled(pool, draft_id)

        # Existing production series are update targets, not hard duplicates.
        # Discovery filters chapter numbers already present in production; the
        # staging transaction rechecks this under a per-series advisory lock so
        # concurrent admins cannot stage the same logical chapter twice.
        existing_target = await _find_exact_existing_series(
            pool,
            title=manifest.series.title,
            discovered_slug=manifest.series.slug,
        )
        skipped_existing = 0
        if existing_target is not None:
            async with pool.acquire() as conn:
                existing_numbers = {
                    Decimal(str(value))
                    for value in await conn.fetch(
                        "SELECT chapter_number FROM chapters WHERE series_id=$1::uuid",
                        existing_target["id"],
                    )
                    for value in [value["chapter_number"]]
                }
            filtered_chapters = []
            for discovered_chapter in manifest.chapters:
                try:
                    discovered_number = Decimal(discovered_chapter.chapter_number)
                except InvalidOperation:
                    continue
                if discovered_number in existing_numbers:
                    skipped_existing += 1
                    continue
                filtered_chapters.append(discovered_chapter)
            manifest = MangaSeriesManifest(
                series=manifest.series,
                genres=manifest.genres,
                tags=manifest.tags,
                chapters=filtered_chapters,
            )
            discovery["existing_series_update"] = {
                "series_id": existing_target["id"],
                "series_slug": existing_target["slug"],
                "chapters_already_present": skipped_existing,
                "chapters_missing": len(filtered_chapters),
            }

        await _update_discovery_progress(
            pool,
            draft_id,
            phase="preparing_draft",
            percent=70,
            message=f"Preparing {len(manifest.chapters)} discovered chapters for admin review.",
            chapters_found=len(manifest.chapters),
            source_strategy=discovery["source_strategy"],
            recursive=discovery.get("recursive"),
        )

        await _raise_if_operation_cancelled(pool, draft_id)
        cover_path = None
        if manifest.series.cover_url and existing_target is None:
            try:
                await _update_discovery_progress(
                    pool,
                    draft_id,
                    phase="fetching_cover",
                    percent=78,
                    message="Downloading the discovered series cover into private staging.",
                )
                cover_bytes, cover_type = await _download_image(
                    client,
                    url=manifest.series.cover_url,
                    referer=final_url,
                )
                await _raise_if_operation_cancelled(pool, draft_id)
                cover_path = (
                    f"_scraper/series-drafts/{draft_id}/"
                    f"cover/source.{_extension(cover_type, manifest.series.cover_url)}"
                )
                await _put(client, cover_path, cover_bytes, cover_type)
            except OperationCancellationRequested:
                raise
            except Exception as exc:
                # Cover is repairable in the admin editor and should not fail
                # an otherwise valid discovery.
                discovery["cover_warning"] = f"{type(exc).__name__}: {exc}"[:1000]
                cover_path = None

        await _raise_if_operation_cancelled(pool, draft_id)
        await _update_discovery_progress(
            pool,
            draft_id,
            phase="saving_draft",
            percent=90,
            message="Saving discovered metadata and chapters to PostgreSQL.",
        )

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Serialize the final discovery save with admin metadata-policy
                # changes.  Clear-all can be requested while discovery is still
                # running; whichever transaction wins the row lock first, the
                # resulting draft remains title-free.
                locked_draft = await conn.fetchrow(
                    "SELECT COALESCE(discovery_options, '{}'::jsonb) AS discovery_options "
                    "FROM scraper_series_drafts WHERE id=$1::uuid FOR UPDATE",
                    draft_id,
                )
                if locked_draft is None:
                    raise RuntimeError("Series draft disappeared before discovery could be saved.")
                suppress_chapter_titles = bool(
                    dict(locked_draft["discovery_options"] or {}).get(
                        "suppress_chapter_titles", False
                    )
                )

                await conn.execute(
                    "DELETE FROM scraper_series_draft_chapters WHERE draft_id = $1::uuid",
                    draft_id,
                )
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET
                        source_url = $2,
                        adapter = $3,
                        title = $4,
                        slug = $5,
                        description = $6,
                        series_status = $7::varchar(20),
                        cover_source_url = $8,
                        cover_staging_path = $9,
                        genres = $10::jsonb,
                        tags = $11::jsonb,
                        workflow_status = $12::varchar(32),
                        error_message = $13,
                        published_series_id = $14::uuid,
                        duplicate_series_id = NULL,
                        duplicate_series_slug = NULL,
                        duplicate_series_title = NULL,
                        discovery_finished_at = NOW(),
                        discovery_worker_heartbeat_at = NOW(),
                        discovery_progress = discovery_progress || $15::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    draft_id,
                    final_url,
                    adapter_name,
                    manifest.series.title,
                    existing_target["slug"] if existing_target is not None else manifest.series.slug,
                    manifest.series.description,
                    manifest.series.status,
                    manifest.series.cover_url,
                    cover_path,
                    json.dumps(manifest.genres),
                    json.dumps(manifest.tags),
                    "ready" if existing_target is not None and not manifest.chapters else "draft",
                    None,
                    existing_target["id"] if existing_target is not None else None,
                    json.dumps({
                        "phase": "completed",
                        "percent": 100,
                        "message": (
                            "Existing series is already up to date; no missing chapters were discovered."
                            if existing_target is not None and not manifest.chapters
                            else (
                                f"Existing series update found {len(manifest.chapters)} missing chapter(s); already-published chapter numbers were skipped."
                                if existing_target is not None
                                else "Discovery completed and is ready for administrator review."
                            )
                        ),
                        "chapters_found": len(manifest.chapters),
                        "chapters_already_present": skipped_existing,
                        "source_strategy": discovery["source_strategy"],
                        "recursive": discovery.get("recursive"),
                        "cover_warning": discovery.get("cover_warning"),
                        "updated_at": _utc_now_iso(),
                    }),
                )

                inserted = 0
                for chapter in manifest.chapters:
                    try:
                        number, _number_text = normalize_chapter_number(chapter.chapter_number)
                        chapter_slug = chapter_slug_from_number(number)
                    except ValueError:
                        continue

                    result = await conn.execute(
                        """
                        INSERT INTO scraper_series_draft_chapters (
                            draft_id,
                            chapter_number,
                            chapter_slug,
                            chapter_title,
                            source_url,
                            selected,
                            stage_status,
                            pages
                        )
                        VALUES (
                            $1::uuid,
                            $2,
                            $3,
                            $4,
                            $5,
                            TRUE,
                            'discovered',
                            '[]'::jsonb
                        )
                        ON CONFLICT (draft_id, chapter_number) DO NOTHING
                        """,
                        draft_id,
                        number,
                        chapter_slug,
                        None if suppress_chapter_titles else chapter.title,
                        chapter.url,
                    )
                    if result.endswith("1"):
                        inserted += 1

                if inserted == 0 and existing_target is None:
                    raise RuntimeError("Discovery produced no valid numeric chapters to save.")
                await _sync_series_ingestion_operation_tx(conn, draft_id)

    except OperationCancellationRequested:
        await _finalize_cancelled_operation(pool, client, draft_id)
        return
    except Exception as exc:
        # COMMIT may have succeeded even when a remote PostgreSQL connection
        # failed while reporting the result. Re-read canonical state before
        # changing status or scheduling cleanup. If PostgreSQL is unavailable,
        # deliberately preserve local staging and let durable recovery retry.
        try:
            async with pool.acquire() as conn:
                canonical = await conn.fetchrow(
                    """
                    SELECT d.discovery_finished_at, d.cover_staging_path,
                           (SELECT COUNT(*)::int FROM scraper_series_draft_chapters c WHERE c.draft_id=d.id) AS chapter_count
                    FROM scraper_series_drafts d
                    WHERE d.id=$1::uuid
                    """,
                    draft_id,
                )
        except Exception:
            raise exc

        if canonical is not None and canonical["discovery_finished_at"] is not None and int(canonical["chapter_count"] or 0) > 0:
            return

        async with pool.acquire() as conn:
            async with conn.transaction():
                if cover_path and (canonical is None or str(canonical["cover_staging_path"] or "") != cover_path):
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=cover_path,
                        reason=f"discovery_cover_not_committed:{type(exc).__name__}",
                    )
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET
                        workflow_status = 'failed',
                        error_message = $2,
                        discovery_finished_at = NOW(),
                        discovery_worker_heartbeat_at = NOW(),
                        discovery_progress = discovery_progress || $3::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    draft_id,
                    str(exc)[:2000],
                    json.dumps({
                        "phase": "failed",
                        "percent": 100,
                        "message": "Series discovery failed. The job remains visible for review or retry.",
                        "error": f"{type(exc).__name__}: {exc}"[:2000],
                        "updated_at": _utc_now_iso(),
                    }),
                )
                await _sync_series_ingestion_operation_tx(conn, draft_id)
        raise


def _apply_live_publish_metrics(value: dict, chapter_values: list[dict]) -> dict:
    """Overlay publish counters from authoritative chapter rows.

    The durable parent JSON remains useful for phase/message/correlation data,
    but chapter/page totals must reflect the current chapter rows, including
    chapters that finish staging after a batch publish has already started.
    """
    selected_rows = [row for row in chapter_values if row.get("selected")]
    if not selected_rows:
        return value

    def progress_int(row: dict, key: str) -> int:
        progress = dict(row.get("publish_progress") or {})
        try:
            return max(0, int(progress.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    def page_count(row: dict) -> int:
        candidates: list[int] = []
        if row.get("page_count") is not None:
            try:
                candidates.append(max(0, int(row.get("page_count") or 0)))
            except (TypeError, ValueError):
                pass
        pages = row.get("pages") or []
        if isinstance(pages, list):
            candidates.append(len(pages))
        for progress_key, count_key in (
            ("stage_progress", "pages_total"),
            ("publish_progress", "source_pages_total"),
        ):
            progress = dict(row.get(progress_key) or {})
            try:
                candidates.append(max(0, int(progress.get(count_key) or 0)))
            except (TypeError, ValueError):
                pass
        return max(candidates, default=0)

    published_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is not None or row.get("publish_status") == "published"
    )
    failed_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is None and row.get("publish_status") == "failed"
    )
    skipped_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is None and row.get("publish_status") == "skipped"
    )
    cancelled_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is None and row.get("publish_status") == "cancelled"
    )
    publishing_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is None and row.get("publish_status") == "publishing"
    )
    staging_count = sum(
        1 for row in selected_rows if row.get("stage_status") in {"queued", "staging"}
    )
    ready_pending_count = sum(
        1 for row in selected_rows
        if row.get("published_chapter_id") is None
        and row.get("stage_status") == "ready"
        and row.get("publish_status") not in {"published", "failed", "skipped", "cancelled", "publishing"}
    )
    completed_count = published_count + failed_count + skipped_count + cancelled_count
    source_pages_total = sum(page_count(row) for row in selected_rows)
    source_pages_completed = sum(
        min(page_count(row), progress_int(row, "source_pages_completed"))
        for row in selected_rows
    )
    final_pages_written = sum(
        progress_int(row, "final_pages_written")
        for row in selected_rows
        if row.get("published_chapter_id") is not None or row.get("publish_status") == "publishing"
    )

    live_progress = dict(value.get("publish_progress") or {})
    live_progress.update({
        "total_chapters": len(selected_rows),
        "chapters_processed": completed_count,
        "chapters_completed": completed_count,
        "chapters_published": published_count,
        "chapters_failed": failed_count,
        "chapters_skipped": skipped_count,
        "chapters_cancelled": cancelled_count,
        "chapters_publishing": publishing_count,
        "chapters_deferred": staging_count,
        "chapters_staging": staging_count,
        "chapters_ready_pending": ready_pending_count,
        "total_source_pages": source_pages_total,
        "source_pages_completed": source_pages_completed,
        "final_pages_written": final_pages_written,
    })
    value["publish_progress"] = live_progress
    return value


async def get_series_draft(
    pool: asyncpg.Pool,
    draft_id: str,
) -> dict:
    async with pool.acquire() as conn:
        draft = await conn.fetchrow(
            """
            SELECT
                d.id::text,
                d.source_url,
                d.adapter,
                d.title,
                d.slug,
                d.description,
                d.series_status,
                d.cover_source_url,
                d.cover_staging_path,
                d.genres,
                d.tags,
                d.workflow_status,
                io.status AS operation_status,
                io.phase AS operation_phase,
                io.revision AS operation_revision,
                io.lease_generation AS operation_lease_generation,
                io.cancel_requested_at AS operation_cancel_requested_at,
                io.error_code AS operation_error_code,
                d.error_message,
                COALESCE(
                    NULLIF(to_jsonb(d)->'discovery_options'->>'suppress_chapter_titles', '')::boolean,
                    FALSE
                ) AS chapter_titles_suppressed,
                COALESCE(
                    to_jsonb(d)->'discovery_options',
                    '{"recursive":true,"max_depth":1,"max_pages":20}'::jsonb
                ) AS discovery_options,
                COALESCE(
                    to_jsonb(d)->'discovery_progress',
                    '{"phase":"completed","percent":100,"message":"Legacy discovery completed."}'::jsonb
                ) AS discovery_progress,
                COALESCE(
                    NULLIF(to_jsonb(d)->>'discovery_attempt', '')::integer,
                    0
                ) AS discovery_attempt,
                NULLIF(to_jsonb(d)->>'discovery_started_at', '')::timestamptz AS discovery_started_at,
                NULLIF(to_jsonb(d)->>'discovery_finished_at', '')::timestamptz AS discovery_finished_at,
                NULLIF(to_jsonb(d)->>'discovery_worker_heartbeat_at', '')::timestamptz AS discovery_worker_heartbeat_at,
                NULLIF(to_jsonb(d)->>'acknowledged_at', '')::timestamptz AS acknowledged_at,
                NULLIF(to_jsonb(d)->>'acknowledged_by', '')::uuid::text AS acknowledged_by,
                NULLIF(to_jsonb(d)->>'operation_cancel_requested_at', '')::timestamptz AS operation_cancel_requested_at,
                NULLIF(to_jsonb(d)->>'operation_cancel_requested_by', '')::uuid::text AS operation_cancel_requested_by,
                NULLIF(to_jsonb(d)->>'duplicate_series_id', '')::uuid::text AS duplicate_series_id,
                NULLIF(to_jsonb(d)->>'duplicate_series_slug', '') AS duplicate_series_slug,
                NULLIF(to_jsonb(d)->>'duplicate_series_title', '') AS duplicate_series_title,
                COALESCE(
                    to_jsonb(d)->'publish_progress',
                    '{"phase":"not_started","percent":0,"message":"Publish progress migration has not been applied yet.","total_chapters":0,"chapters_completed":0,"total_source_pages":0,"source_pages_completed":0,"final_pages_written":0,"catalog_verified":false,"catalog_verified_chapters":0,"reader_verified_chapters":0,"reader_verified_images":0,"verification_errors":[]}'::jsonb
                ) AS publish_progress,
                COALESCE(
                    NULLIF(to_jsonb(d)->>'publish_attempt', '')::integer,
                    0
                ) AS publish_attempt,
                NULLIF(
                    to_jsonb(d)->>'publish_started_at',
                    ''
                )::timestamptz AS publish_started_at,
                NULLIF(
                    to_jsonb(d)->>'publish_finished_at',
                    ''
                )::timestamptz AS publish_finished_at,
                NULLIF(
                    to_jsonb(d)->>'publish_cancel_requested_at',
                    ''
                )::timestamptz AS publish_cancel_requested_at,
                NULLIF(
                    to_jsonb(d)->>'publish_worker_heartbeat_at',
                    ''
                )::timestamptz AS publish_worker_heartbeat_at,
                d.published_series_id::text,
                d.created_by::text,
                d.created_at,
                d.updated_at
            FROM scraper_series_drafts d
            LEFT JOIN ingestion_operations io ON io.id = d.id
            WHERE d.id = $1::uuid
            """,
            draft_id,
        )

        if draft is None:
            raise HTTPException(
                404,
                "Series draft not found.",
            )

        chapters = await conn.fetch(
            """
            SELECT
                id::text,
                draft_id::text,
                chapter_number,
                chapter_slug,
                chapter_title,
                source_url,
                selected,
                stage_status,
                pages,
                error_message,
                COALESCE(
                    to_jsonb(scraper_series_draft_chapters)->'stage_progress',
                    '{"phase":"not_started","percent":0,"message":"Staging progress migration has not been applied yet.","pages_total":0,"pages_completed":0}'::jsonb
                ) AS stage_progress,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'stage_started_at',
                    ''
                )::timestamptz AS stage_started_at,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'stage_finished_at',
                    ''
                )::timestamptz AS stage_finished_at,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'stage_worker_heartbeat_at',
                    ''
                )::timestamptz AS stage_worker_heartbeat_at,
                COALESCE(
                    to_jsonb(scraper_series_draft_chapters)->>'publish_status',
                    CASE
                      WHEN published_chapter_id IS NOT NULL THEN 'published'
                      ELSE 'pending'
                    END
                ) AS publish_status,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'publish_error',
                    ''
                ) AS publish_error,
                COALESCE(
                    to_jsonb(scraper_series_draft_chapters)->'publish_progress',
                    '{"phase":"pending","percent":0,"message":"Chapter publish migration has not been applied yet.","source_pages_total":0,"source_pages_completed":0,"final_pages_written":0}'::jsonb
                ) AS publish_progress,
                COALESCE(
                    NULLIF(
                        to_jsonb(scraper_series_draft_chapters)->>'publish_attempt',
                        ''
                    )::integer,
                    0
                ) AS publish_attempt,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'publish_started_at',
                    ''
                )::timestamptz AS publish_started_at,
                NULLIF(
                    to_jsonb(scraper_series_draft_chapters)->>'publish_finished_at',
                    ''
                )::timestamptz AS publish_finished_at,
                published_chapter_id::text,
                created_at,
                updated_at
            FROM scraper_series_draft_chapters
            WHERE draft_id = $1::uuid
            ORDER BY chapter_number ASC
            """,
            draft_id,
        )

    value = dict(draft)
    value["chapters"] = [
        dict(row)
        for row in chapters
    ]
    return _apply_live_publish_metrics(value, value["chapters"])


async def get_series_draft_chapter_pages(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    chapter_id: str,
) -> dict:
    """Return only one chapter's staged page payload.

    The workflow poll intentionally omits page objects.  The admin UI calls
    this endpoint once when a chapter transitions to a staged/ready state so
    it can hydrate the edit/reorder/delete cards without repeatedly loading
    the entire series draft during polling.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id::text,
                draft_id::text,
                stage_status,
                pages,
                jsonb_array_length(COALESCE(pages, '[]'::jsonb))::int AS page_count,
                updated_at
            FROM scraper_series_draft_chapters
            WHERE draft_id = $1::uuid
              AND id = $2::uuid
            """,
            draft_id,
            chapter_id,
        )
    if row is None:
        raise HTTPException(404, "Series draft chapter not found.")
    return dict(row)

async def get_series_workflow_status(
    pool: asyncpg.Pool,
    draft_id: str,
) -> dict:
    """Return lightweight scraper progress without staged page payloads."""
    async with pool.acquire() as conn:
        draft = await conn.fetchrow(
            """
            SELECT
                d.id::text, d.slug, d.workflow_status, d.error_message,
                io.status AS operation_status,
                io.phase AS operation_phase,
                io.revision AS operation_revision,
                io.lease_generation AS operation_lease_generation,
                io.cancel_requested_at AS operation_cancel_requested_at,
                io.error_code AS operation_error_code,
                d.published_series_id::text,
                COALESCE(NULLIF(to_jsonb(d)->>'publish_attempt','')::integer,0) AS publish_attempt,
                NULLIF(to_jsonb(d)->>'publish_started_at','')::timestamptz AS publish_started_at,
                NULLIF(to_jsonb(d)->>'publish_finished_at','')::timestamptz AS publish_finished_at,
                NULLIF(to_jsonb(d)->>'publish_cancel_requested_at','')::timestamptz AS publish_cancel_requested_at,
                NULLIF(to_jsonb(d)->>'publish_worker_heartbeat_at','')::timestamptz AS publish_worker_heartbeat_at,
                COALESCE(to_jsonb(d)->'publish_progress','{}'::jsonb) AS publish_progress,
                COALESCE(to_jsonb(d)->'discovery_progress','{}'::jsonb) AS discovery_progress,
                d.updated_at
            FROM scraper_series_drafts d
            LEFT JOIN ingestion_operations io ON io.id = d.id
            WHERE d.id = $1::uuid
            """,
            draft_id,
        )
        if draft is None:
            raise HTTPException(404, "Series draft not found.")
        chapters = await conn.fetch(
            """
            SELECT
                c.id::text, c.chapter_number, c.chapter_slug, c.selected,
                c.stage_status, c.published_chapter_id::text, c.error_message,
                COALESCE(to_jsonb(c)->'stage_progress','{}'::jsonb) AS stage_progress,
                NULLIF(to_jsonb(c)->>'stage_started_at','')::timestamptz AS stage_started_at,
                NULLIF(to_jsonb(c)->>'stage_finished_at','')::timestamptz AS stage_finished_at,
                COALESCE(to_jsonb(c)->>'publish_status', CASE WHEN c.published_chapter_id IS NOT NULL THEN 'published' ELSE 'pending' END) AS publish_status,
                NULLIF(to_jsonb(c)->>'publish_error','') AS publish_error,
                COALESCE(to_jsonb(c)->'publish_progress','{}'::jsonb) AS publish_progress,
                COALESCE(NULLIF(to_jsonb(c)->>'publish_attempt','')::integer,0) AS publish_attempt,
                NULLIF(to_jsonb(c)->>'publish_started_at','')::timestamptz AS publish_started_at,
                NULLIF(to_jsonb(c)->>'publish_finished_at','')::timestamptz AS publish_finished_at,
                jsonb_array_length(COALESCE(c.pages,'[]'::jsonb))::int AS page_count,
                c.updated_at
            FROM scraper_series_draft_chapters c
            WHERE c.draft_id = $1::uuid
            ORDER BY c.chapter_number ASC
            """,
            draft_id,
        )
    value = dict(draft)
    chapter_values = [dict(row) for row in chapters]
    value["chapters"] = chapter_values

    return _apply_live_publish_metrics(value, chapter_values)



async def update_series_metadata(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    title: str,
    slug: str,
    description: str | None,
    series_status: str,
    genres: list[str],
    tags: list[str],
) -> dict:
    clean_genres = sorted({value.strip() for value in genres if value.strip()})
    clean_tags = sorted({value.strip() for value in tags if value.strip()})

    async with pool.acquire() as conn:
        async with conn.transaction():
            draft = await conn.fetchrow(
                """
                SELECT workflow_status, published_series_id, operation_cancel_requested_at
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if draft is None:
                raise HTTPException(404, "Series draft not found.")
            if draft["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "Cancelled scraper operations are read-only.")
            if draft["published_series_id"] is not None:
                raise HTTPException(409, "Series metadata is locked after production publication begins.")
            if draft["workflow_status"] not in {"draft", "ready", "failed"}:
                raise HTTPException(409, "Series draft cannot be edited in its current state.")

            existing = await conn.fetchrow("SELECT id FROM series WHERE slug=$1", slug)
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET title=$2, slug=$3, description=$4, series_status=$5::varchar(20),
                    genres=$6::jsonb, tags=$7::jsonb, error_message=$8, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                title,
                slug,
                description,
                series_status,
                json.dumps(clean_genres),
                json.dumps(clean_tags),
                "A production series already uses this slug." if existing is not None else None,
            )

    return await get_series_draft(pool, draft_id)

async def replace_cover_from_url(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    url: str,
) -> dict:
    async with pool.acquire() as conn:
        source_url = await conn.fetchval("SELECT source_url FROM scraper_series_drafts WHERE id=$1::uuid", draft_id)
    if source_url is None:
        raise HTTPException(404, "Series draft not found.")
    data, content_type = await _download_image(client, url=url, referer=source_url)
    path = f"_scraper/series-drafts/{draft_id}/cover/source-{uuid.uuid4().hex}.{_extension(content_type, url)}"
    await _put(client, path, data, content_type)

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT workflow_status,published_series_id,operation_cancel_requested_at,cover_staging_path
                    FROM scraper_series_drafts WHERE id=$1::uuid FOR UPDATE
                    """,
                    draft_id,
                )
                if row is None:
                    raise HTTPException(404, "Series draft not found.")
                if row["operation_cancel_requested_at"] is not None:
                    raise HTTPException(409, "Cancelled scraper operations are read-only.")
                if row["published_series_id"] is not None:
                    raise HTTPException(409, "Cover editing is locked after production publication begins.")
                if row["workflow_status"] not in {"draft", "ready", "failed"}:
                    raise HTTPException(409, f"Cover editing is locked while the draft is {row['workflow_status']}.")
                old = row["cover_staging_path"]
                await conn.execute(
                    "UPDATE scraper_series_drafts SET cover_source_url=$2,cover_staging_path=$3,updated_at=NOW() WHERE id=$1::uuid",
                    draft_id,
                    url,
                    path,
                )
                if old and old != path:
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=old,
                        reason="draft_cover_replaced",
                    )
    except Exception as exc:
        # A failed transaction acknowledgement may hide a successful COMMIT.
        # If PostgreSQL is unavailable, preserve the file; if it is reachable,
        # only queue cleanup when the new path is not canonical.
        async with pool.acquire() as conn:
            canonical = await conn.fetchval(
                "SELECT cover_staging_path FROM scraper_series_drafts WHERE id=$1::uuid",
                draft_id,
            )
            if canonical != path:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=path,
                        reason=f"draft_cover_replace_rollback:{type(exc).__name__}",
                    )
            committed = canonical == path
        if committed:
            return await get_series_draft(pool, draft_id)
        raise
    return await get_series_draft(pool, draft_id)

async def upload_cover(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    file: UploadFile,
) -> dict:
    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Cover must be an image.")
    path = f"_scraper/series-drafts/{draft_id}/cover/source-{uuid.uuid4().hex}.{_extension(content_type, file.filename or 'cover')}"
    try:
        await put_upload_object(path, file.file, max_bytes=MAX_PAGE_BYTES)
    except ValueError as exc:
        if "empty" in str(exc).lower():
            raise HTTPException(400, "Cover upload is empty.") from exc
        raise HTTPException(413, "Cover exceeds 50 MiB.") from exc

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT workflow_status,published_series_id,operation_cancel_requested_at,cover_staging_path
                    FROM scraper_series_drafts WHERE id=$1::uuid FOR UPDATE
                    """,
                    draft_id,
                )
                if row is None:
                    raise HTTPException(404, "Series draft not found.")
                if row["operation_cancel_requested_at"] is not None:
                    raise HTTPException(409, "Cancelled scraper operations are read-only.")
                if row["published_series_id"] is not None:
                    raise HTTPException(409, "Cover editing is locked after production publication begins.")
                if row["workflow_status"] not in {"draft", "ready", "failed"}:
                    raise HTTPException(409, f"Cover editing is locked while the draft is {row['workflow_status']}.")
                old = row["cover_staging_path"]
                await conn.execute(
                    "UPDATE scraper_series_drafts SET cover_source_url=NULL,cover_staging_path=$2,updated_at=NOW() WHERE id=$1::uuid",
                    draft_id,
                    path,
                )
                if old and old != path:
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=old,
                        reason="draft_cover_replaced",
                    )
    except Exception as exc:
        async with pool.acquire() as conn:
            canonical = await conn.fetchval(
                "SELECT cover_staging_path FROM scraper_series_drafts WHERE id=$1::uuid",
                draft_id,
            )
            if canonical != path:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=path,
                        reason=f"draft_cover_upload_rollback:{type(exc).__name__}",
                    )
            committed = canonical == path
        if committed:
            return await get_series_draft(pool, draft_id)
        raise
    return await get_series_draft(pool, draft_id)

async def remove_cover(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
) -> dict:
    cleanup_job_id: str | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT workflow_status,published_series_id,operation_cancel_requested_at,cover_staging_path
                FROM scraper_series_drafts WHERE id=$1::uuid FOR UPDATE
                """,
                draft_id,
            )
            if row is None:
                raise HTTPException(404, "Series draft not found.")
            if row["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "Cancelled scraper operations are read-only.")
            if row["published_series_id"] is not None:
                raise HTTPException(409, "Cover editing is locked after production publication begins.")
            if row["workflow_status"] not in {"draft", "ready", "failed"}:
                raise HTTPException(409, f"Cover editing is locked while the draft is {row['workflow_status']}.")
            old = row["cover_staging_path"]
            await conn.execute(
                "UPDATE scraper_series_drafts SET cover_source_url=NULL,cover_staging_path=NULL,updated_at=NOW() WHERE id=$1::uuid",
                draft_id,
            )
            if old:
                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft_id,
                    local_prefix=old,
                    reason="draft_cover_removed",
                )
    return await get_series_draft(pool, draft_id)

async def preview_cover(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
) -> tuple[bytes, str]:
    draft = await get_series_draft(
        pool,
        draft_id,
    )

    path = draft["cover_staging_path"]
    if not path:
        raise HTTPException(
            404,
            "Draft has no cover.",
        )

    return await _get(
        client,
        path,
    )


async def _lock_editable_chapter(
    conn: asyncpg.Connection,
    chapter_id: str,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        SELECT
            c.id::text,
            c.draft_id::text,
            c.stage_status,
            c.publish_status,
            c.publish_progress,
            c.published_chapter_id::text,
            c.pages,
            c.source_url,
            d.workflow_status,
            d.operation_cancel_requested_at
        FROM scraper_series_draft_chapters c
        JOIN scraper_series_drafts d ON d.id=c.draft_id
        WHERE c.id=$1::uuid
        FOR UPDATE OF d, c
        """,
        chapter_id,
    )
    if row is None:
        raise HTTPException(404, "Draft chapter not found.")
    if row["operation_cancel_requested_at"] is not None:
        raise HTTPException(409, "Cancelled scraper operations are read-only.")
    if row["workflow_status"] in {
        "queued_discovery", "discovering", "staging",
        "queued_publish", "publishing", "cancel_requested",
    }:
        raise HTTPException(409, f"Chapter editing is locked while the draft is {row['workflow_status']}.")
    if row["published_chapter_id"] is not None or row["stage_status"] == "published" or row["publish_status"] == "published":
        raise HTTPException(409, "Published chapters are immutable in scraper staging.")
    if row["stage_status"] in {"queued", "staging"}:
        raise HTTPException(409, "Chapter editing is locked while staging is active.")
    progress = dict(row["publish_progress"] or {})
    if row["publish_status"] == "publishing" or (
        progress.get("mode") == "single"
        and progress.get("phase") in {
            "queued_single", "queued_recovery", "waiting_for_publish_lock",
            "waiting_for_batch", "processing_cover", "processing_pages", "saving_database",
        }
    ):
        raise HTTPException(409, "Chapter editing is locked while publish work is active.")
    return row


async def _save_manual_pages_locked(
    conn: asyncpg.Connection,
    *,
    chapter_id: str,
    draft_id: str,
    pages: list[dict],
) -> None:
    for index, page in enumerate(pages, start=1):
        page["order"] = index
    await conn.execute(
        """
        UPDATE scraper_series_draft_chapters
        SET pages=$2::jsonb,
            revision=revision+1,
            stage_status=CASE WHEN jsonb_array_length($2::jsonb) > 0 THEN 'ready' ELSE 'pending' END,
            error_message=NULL,
            stage_finished_at=CASE WHEN jsonb_array_length($2::jsonb) > 0 THEN NOW() ELSE NULL END,
            stage_progress=jsonb_build_object(
                'phase', CASE WHEN jsonb_array_length($2::jsonb) > 0 THEN 'completed' ELSE 'manual_edit' END,
                'percent', CASE WHEN jsonb_array_length($2::jsonb) > 0 THEN 100 ELSE 0 END,
                'message', CASE WHEN jsonb_array_length($2::jsonb) > 0 THEN 'Chapter pages are ready.' ELSE 'Chapter has no staged pages.' END,
                'pages_total', jsonb_array_length($2::jsonb),
                'pages_completed', jsonb_array_length($2::jsonb),
                'updated_at', NOW()
            ),
            updated_at=NOW()
        WHERE id=$1::uuid
        """,
        chapter_id,
        json.dumps(pages),
    )
    summary = await conn.fetchrow(
        """
        SELECT d.workflow_status, d.published_series_id::text,
               COUNT(c.id) FILTER (WHERE c.selected)::int AS selected_count,
               COUNT(c.id) FILTER (WHERE c.selected AND c.stage_status IN ('ready','published'))::int AS ready_count,
               COUNT(c.id) FILTER (WHERE c.selected AND c.stage_status IN ('queued','staging'))::int AS active_count
        FROM scraper_series_drafts d
        LEFT JOIN scraper_series_draft_chapters c ON c.draft_id=d.id
        WHERE d.id=$1::uuid
        GROUP BY d.id,d.workflow_status,d.published_series_id
        """,
        draft_id,
    )
    if summary and int(summary["active_count"] or 0) == 0 and summary["workflow_status"] not in {
        "queued_publish", "publishing", "published", "cancel_requested", "cancelled"
    }:
        all_ready = int(summary["selected_count"] or 0) > 0 and int(summary["ready_count"] or 0) == int(summary["selected_count"] or 0)
        # Legacy regression contract: next_status = ('published_partial' if summary["published_series_id"] else 'ready')
        next_status = (
            "published_partial" if summary["published_series_id"] else "ready"
        ) if all_ready else (
            "published_partial" if summary["published_series_id"] else "draft"
        )
        await conn.execute(
            "UPDATE scraper_series_drafts SET workflow_status=$2::varchar(32), error_message=NULL, updated_at=NOW() WHERE id=$1::uuid",
            draft_id,
            next_status,
        )


async def update_chapter(
    pool: asyncpg.Pool,
    *,
    chapter_id: str,
    chapter_number: str,
    chapter_slug: str,
    chapter_title: str | None,
    selected: bool,
) -> dict:
    try:
        number, _number_text = normalize_chapter_number(chapter_number)
        canonical_slug = chapter_slug_from_number(number)
    except ValueError:
        raise HTTPException(400, "Invalid chapter number.")

    # chapter_slug remains in the API payload for backwards compatibility, but
    # it is not authoritative. The number is the chapter identity source.
    _ = chapter_slug

    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter = await _lock_editable_chapter(conn, chapter_id)
            await conn.execute(
                """
                UPDATE scraper_series_draft_chapters
                SET chapter_number=$2, chapter_slug=$3, chapter_title=$4,
                    selected=$5, revision=revision+1, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                chapter_id,
                number,
                canonical_slug,
                chapter_title,
                selected,
            )
    return await get_series_draft(pool, chapter["draft_id"])

async def clear_chapter_titles(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
) -> dict:
    """Clear titles now and keep later discovery results title-free.

    Existing-series update drafts already point at a production series through
    ``published_series_id``.  That reference does not mean the newly discovered
    draft chapters have been published, so it must not disable this operation.
    The policy is persisted in discovery_options so a discovery worker that is
    still finding/saving chapters cannot reintroduce source titles afterwards.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            draft = await conn.fetchrow(
                """
                SELECT
                    workflow_status,
                    operation_cancel_requested_at,
                    COALESCE(discovery_options, '{}'::jsonb) AS discovery_options
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if draft is None:
                raise HTTPException(404, "Series draft not found.")
            if draft["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "Cancelled scraper operations are read-only.")

            # Publication reads chapter metadata.  Do not race a production
            # publish, but allow discovery/staging and existing-series updates.
            if draft["workflow_status"] in {"queued_publish", "publishing", "published", "duplicate"}:
                raise HTTPException(409, "Chapter titles cannot be cleared while publication is active or complete.")

            active_single_publish = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM scraper_series_draft_chapters
                    WHERE draft_id=$1::uuid
                      AND COALESCE(
                            to_jsonb(scraper_series_draft_chapters)->>'publish_status',
                            'pending'
                          )='publishing'
                )
                """,
                draft_id,
            )
            if active_single_publish:
                raise HTTPException(409, "Chapter titles cannot be cleared while a chapter is publishing.")

            options = dict(draft["discovery_options"] or {})
            options["suppress_chapter_titles"] = True
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET discovery_options=$2::jsonb, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                json.dumps(options),
            )
            await conn.execute(
                """
                UPDATE scraper_series_draft_chapters
                SET chapter_title=NULL, updated_at=NOW()
                WHERE draft_id=$1::uuid
                  AND published_chapter_id IS NULL
                """,
                draft_id,
            )
    return await get_series_draft(pool, draft_id)

async def _stage_repair_decision(pages: list[dict]) -> str:
    """Classify a ready chapter before an explicit Stage/Retry request."""
    missing: list[dict] = []
    for page in pages:
        path = str(page.get("staging_path") or "")
        if not path or not await staging_exists(path):
            missing.append(page)
    if not missing:
        return "intact"
    if any(not page.get("source_url") for page in missing):
        return "manual_reupload"
    return "url_repair"


async def _should_queue_stage_chapter(row) -> bool:
    status = str(row["stage_status"])
    if status in {"queued", "staging"}:
        return False
    if status != "ready":
        return True
    repair = await _stage_repair_decision(list(row["pages"] or []))
    if repair == "manual_reupload":
        raise HTTPException(
            409,
            "A manually uploaded staged page is missing; re-upload the missing page before staging again.",
        )
    return repair == "url_repair"


async def queue_stage_chapters(
    pool: asyncpg.Pool,
    redis,
    *,
    draft_id: str,
    chapter_ids: list[str],
    request_id: str | None = None,
) -> dict:
    chapter_ids = list(dict.fromkeys(chapter_ids))
    if not chapter_ids:
        raise HTTPException(400, "Select at least one chapter to stage.")
    try:
        chapter_uuids = [uuid.UUID(value) for value in chapter_ids]
    except ValueError as exc:
        raise HTTPException(400, "One or more chapter IDs are invalid.") from exc

    queued_ids: list[str] = []
    skipped_existing_ids: list[str] = []
    skipped_claimed_ids: list[str] = []
    duplicate_info: dict | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            draft = await conn.fetchrow(
                """
                SELECT id::text, source_url, adapter, title, slug, workflow_status,
                       published_series_id::text, operation_cancel_requested_at
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if draft is None:
                raise HTTPException(404, "Series draft not found.")
            if draft["workflow_status"] not in {
                "draft", "ready", "failed", "staging", "published_partial", "cancelled"
            }:
                raise HTTPException(409, f"Draft cannot stage chapters while status is {draft['workflow_status']}.")

            # Explicit retry from a terminal cancelled state revives the durable
            # operation. A live cancel_requested state is never auto-cleared.
            if draft["workflow_status"] == "cancelled":
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET operation_cancel_requested_at=NULL,
                        operation_cancel_requested_by=NULL,
                        publish_cancel_requested_at=NULL,
                        acknowledged_at=NULL,
                        acknowledged_by=NULL,
                        error_message=NULL,
                        updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                )
            elif draft["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "Operation cancellation is still in progress.")

            if draft["published_series_id"] is None:
                existing = await conn.fetchrow(
                    """
                    SELECT id::text, slug, title
                    FROM series
                    WHERE lower(title)=lower($1) OR slug=$2
                    ORDER BY CASE WHEN slug=$2 THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    draft["title"],
                    draft["slug"],
                )
                if existing is not None:
                    message = f"A production series already exists as {existing['title']} ({existing['slug']})."
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status='duplicate', error_message=$2,
                            duplicate_series_id=$3::uuid, duplicate_series_slug=$4,
                            duplicate_series_title=$5, updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                        message,
                        existing["id"],
                        existing["slug"],
                        existing["title"],
                    )
                    duplicate_info = {
                        "id": existing["id"],
                        "slug": existing["slug"],
                        "title": existing["title"],
                    }
                    await _sync_series_ingestion_operation_tx(conn, draft_id)

            if duplicate_info is None:
                # Existing-series updates are serialized only for the canonical
                # production series while the staging claim is made. Different
                # series remain fully parallel. This closes the race where two
                # admins discover the same missing chapter and click Stage at
                # nearly the same time.
                target_series_id = draft["published_series_id"]
                if target_series_id is not None:
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        f"scraper-stage-series:{target_series_id}",
                    )

                rows = await conn.fetch(
                    """
                    SELECT id::text, chapter_number, stage_status, published_chapter_id::text,
                           pages, revision, stage_generation
                    FROM scraper_series_draft_chapters
                    WHERE draft_id=$1::uuid AND id=ANY($2::uuid[])
                    FOR UPDATE
                    """,
                    draft_id,
                    chapter_uuids,
                )
                if len(rows) != len(chapter_ids):
                    raise HTTPException(400, "One or more chapter IDs do not belong to this draft.")

                existing_by_number: dict[Decimal, str] = {}
                claimed_numbers: set[Decimal] = set()
                if target_series_id is not None:
                    requested_numbers = [Decimal(str(row["chapter_number"])) for row in rows]
                    production_rows = await conn.fetch(
                        """
                        SELECT id::text, chapter_number
                        FROM chapters
                        WHERE series_id=$1::uuid
                          AND chapter_number=ANY($2::numeric[])
                        """,
                        target_series_id,
                        requested_numbers,
                    )
                    existing_by_number = {
                        Decimal(str(value["chapter_number"])): value["id"]
                        for value in production_rows
                    }
                    claim_rows = await conn.fetch(
                        """
                        SELECT DISTINCT c.chapter_number
                        FROM scraper_series_draft_chapters c
                        JOIN scraper_series_drafts d ON d.id=c.draft_id
                        WHERE d.published_series_id=$1::uuid
                          AND d.id<>$2::uuid
                          AND c.published_chapter_id IS NULL
                          AND c.selected=TRUE
                          AND (
                                c.stage_status IN ('queued','staging','ready')
                                OR c.publish_status IN ('queued','publishing')
                              )
                          AND c.chapter_number=ANY($3::numeric[])
                        """,
                        target_series_id,
                        draft_id,
                        requested_numbers,
                    )
                    claimed_numbers = {
                        Decimal(str(value["chapter_number"])) for value in claim_rows
                    }

                for row in rows:
                    number = Decimal(str(row["chapter_number"]))
                    existing_chapter_id = existing_by_number.get(number)
                    if existing_chapter_id is not None:
                        skipped_existing_ids.append(row["id"])
                        await conn.execute(
                            """
                            UPDATE scraper_series_draft_chapters
                            SET selected=FALSE,
                                stage_status='published',
                                published_chapter_id=$2::uuid,
                                publish_status='published',
                                error_message=NULL,
                                stage_progress=COALESCE(stage_progress,'{}'::jsonb) || jsonb_build_object(
                                    'phase','skipped_existing','percent',100,
                                    'message','Skipped because this chapter number already exists in production.',
                                    'updated_at',NOW()
                                ),
                                publish_progress=COALESCE(publish_progress,'{}'::jsonb) || jsonb_build_object(
                                    'phase','already_published','percent',100,
                                    'message','Existing production chapter retained; no duplicate publish was attempted.',
                                    'updated_at',NOW()
                                ),
                                updated_at=NOW()
                            WHERE id=$1::uuid
                            """,
                            row["id"],
                            existing_chapter_id,
                        )
                        continue
                    if number in claimed_numbers:
                        skipped_claimed_ids.append(row["id"])
                        await conn.execute(
                            """
                            UPDATE scraper_series_draft_chapters
                            SET selected=FALSE,
                                stage_status='discovered',
                                error_message='Skipped because another active update for this series already claimed this chapter number.',
                                stage_progress=COALESCE(stage_progress,'{}'::jsonb) || jsonb_build_object(
                                    'phase','skipped_concurrent_update','percent',0,
                                    'message','Another active update already owns this chapter number; it was not staged twice.',
                                    'updated_at',NOW()
                                ),
                                updated_at=NOW()
                            WHERE id=$1::uuid
                            """,
                            row["id"],
                        )
                        continue
                    if row["published_chapter_id"] is not None or row["stage_status"] == "published":
                        skipped_existing_ids.append(row["id"])
                        continue
                    if not await _should_queue_stage_chapter(row):
                        continue
                    queued_ids.append(row["id"])

                if queued_ids:
                    await conn.execute(
                        """
                        UPDATE scraper_series_draft_chapters
                        SET selected=TRUE,
                            stage_status='queued',
                            stage_generation=stage_generation+1,
                            queue_dispatched_at=NULL,
                            error_message=NULL,
                            stage_started_at=NULL,
                            stage_finished_at=NULL,
                            stage_worker_heartbeat_at=NULL,
                            stage_progress=jsonb_build_object(
                                'phase','queued','percent',0,
                                'message','Chapter staging is queued.',
                                'pages_total',0,'pages_completed',0,
                                'request_id',$1::text,
                                'updated_at',NOW()
                            ),
                            publish_status=CASE WHEN published_chapter_id IS NULL THEN 'pending' ELSE publish_status END,
                            publish_error=CASE WHEN published_chapter_id IS NULL THEN NULL ELSE publish_error END,
                            publish_progress=CASE WHEN published_chapter_id IS NULL THEN jsonb_build_object(
                                'phase','waiting_for_stage','percent',0,
                                'message','Chapter will become publishable when staging completes.',
                                'source_pages_total',0,'source_pages_completed',0,'final_pages_written',0,
                                'request_id',$1::text,
                                'updated_at',NOW()
                            ) ELSE publish_progress END,
                            updated_at=NOW()
                        WHERE id=ANY($2::uuid[])
                        """,
                        request_id or "",
                        [uuid.UUID(value) for value in queued_ids],
                    )
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status='staging', error_message=NULL, updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)

    if duplicate_info is not None:
        await record_operation_event(
            pool,
            operation_id=draft_id,
            request_id=request_id,
            service="scraper-api",
            event_type="duplicate_detected",
            phase="duplicate",
            status="blocked",
            message=f"Staging blocked because production series {duplicate_info['title']} ({duplicate_info['slug']}) already exists.",
            metadata=duplicate_info,
        )
        return await get_series_draft(pool, draft_id)

    if skipped_existing_ids or skipped_claimed_ids:
        await record_operation_event(
            pool,
            operation_id=draft_id,
            request_id=request_id,
            service="scraper-api",
            event_type="stage_duplicates_skipped",
            phase="stage_filter",
            status="completed",
            message=(
                f"Skipped {len(skipped_existing_ids)} chapter(s) already in production and "
                f"{len(skipped_claimed_ids)} chapter(s) claimed by another active update."
            ),
            metadata={
                "already_published_count": len(skipped_existing_ids),
                "concurrent_claim_count": len(skipped_claimed_ids),
            },
        )

    if not queued_ids:
        return await get_series_draft(pool, draft_id)

    await record_operation_event(
        pool,
        operation_id=draft_id,
        request_id=request_id,
        service="scraper-api",
        event_type="stage_accepted",
        phase="queued",
        status="queued",
        message=f"Staging committed for {len(queued_ids)} chapter(s).",
        metadata={"chapter_count": len(queued_ids), "chapter_ids": queued_ids[:100]},
    )

    queue_errors: list[str] = []
    for chapter_id in queued_ids:
        try:
            await enqueue_unique(
                redis,
                STAGE_QUEUE,
                chapter_id,
                payload={"operation_id": draft_id, "chapter_id": chapter_id, "request_id": request_id or ""},
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND stage_status='queued'",
                    chapter_id,
                )
        except Exception as exc:
            queue_errors.append(f"{chapter_id}: {type(exc).__name__}: {exc}")

    if queue_errors:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET error_message=$2, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                ("Staging is durable in PostgreSQL and will be requeued by worker recovery when RabbitMQ is available. " + queue_errors[0])[:2000],
            )
        await record_operation_event(
            pool,
            operation_id=draft_id,
            request_id=request_id,
            service="scraper-api",
            event_type="stage_dispatch_deferred",
            phase="queued_recovery",
            status="queued",
            message="One or more staging broker publishes failed; PostgreSQL recovery will requeue them.",
            metadata={"errors": queue_errors[:20]},
        )

    return await get_series_draft(pool, draft_id)

class StageWorkerFenceLost(RuntimeError):
    pass


async def _commit_stage_path_cleanup(
    pool: asyncpg.Pool,
    *,
    chapter_id: str,
    paths: set[str],
    reason: str,
) -> None:
    if not paths:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            for path in sorted(paths):
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=chapter_id,
                    local_prefix=path,
                    reason=reason,
                )


async def stage_one_chapter(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    chapter_id: str,
) -> None:
    # Atomically claim queued work.  RabbitMQ delivery is intentionally
    # at-least-once, so duplicate/redelivered chapter IDs must never let two
    # consumers download/upload the same chapter concurrently.
    async with pool.acquire() as conn:
        chapter = await conn.fetchrow(
            """
            UPDATE scraper_series_draft_chapters AS c
            SET
                stage_status = 'staging',
                stage_started_at = COALESCE(c.stage_started_at, NOW()),
                stage_worker_heartbeat_at = NOW(),
                stage_progress = COALESCE(c.stage_progress, '{}'::jsonb) || jsonb_build_object(
                    'phase', 'discovering_pages',
                    'percent', 5,
                    'message', 'Discovering page images for this chapter.',
                    'updated_at', NOW()
                ),
                updated_at = NOW()
            FROM scraper_series_drafts AS d
            WHERE c.id = $1::uuid
              AND c.draft_id = d.id
              AND c.stage_status = 'queued'
              AND d.operation_cancel_requested_at IS NULL
            RETURNING
                c.id::text,
                c.draft_id::text,
                c.source_url,
                c.stage_status,
                c.revision,
                c.stage_generation,
                d.source_url AS series_source_url,
                d.operation_cancel_requested_at,
                NULLIF(c.stage_progress->>'request_id','') AS request_id
            """,
            chapter_id,
        )

    if chapter is None:
        # A cancellation may have raced the queue pop.  Finalize that durable
        # operation, otherwise duplicate/non-queued deliveries are harmless.
        async with pool.acquire() as conn:
            cancelled = await conn.fetchrow(
                """
                SELECT c.draft_id::text
                FROM scraper_series_draft_chapters c
                JOIN scraper_series_drafts d ON d.id = c.draft_id
                WHERE c.id = $1::uuid
                  AND d.operation_cancel_requested_at IS NOT NULL
                """,
                chapter_id,
            )
        if cancelled is not None:
            await _finalize_cancelled_operation(pool, client, cancelled["draft_id"])
        return

    heartbeat_stop = asyncio.Event()

    async def heartbeat() -> None:
        # Progress updates also refresh the heartbeat, but a single slow source
        # request must not make recovery falsely classify a live worker stale.
        while True:
            try:
                await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                return
            except TimeoutError:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE scraper_series_draft_chapters
                        SET stage_worker_heartbeat_at=NOW()
                        WHERE id=$1::uuid AND stage_status='staging'
                          AND revision=$2::bigint AND stage_generation=$3::bigint
                        """,
                        chapter_id,
                        int(chapter["revision"]),
                        int(chapter["stage_generation"]),
                    )

    heartbeat_task = asyncio.create_task(
        heartbeat(), name=f"scraper-stage-heartbeat-{chapter_id}"
    )
    expected_revision = int(chapter["revision"])
    claimed_stage_generation = int(chapter["stage_generation"])
    staged_paths: set[str] = set()

    async def report_stage_progress(*, phase: str, percent: int, message: str, **fields) -> None:
        await _update_stage_progress(
            pool,
            chapter_id,
            phase=phase,
            percent=percent,
            message=message,
            expected_revision=expected_revision,
            expected_stage_generation=claimed_stage_generation,
            **fields,
        )

    try:
        chapter_prefix = (
            f"_scraper/series-drafts/{chapter['draft_id']}/"
            f"chapters/{chapter_id}"
        )
        # A previous cancellation/removal/failed-stage cleanup may still own an
        # overlapping path. Never restage until that durable cleanup is finished,
        # otherwise a delayed lifecycle worker could delete freshly-written data.
        await wait_for_staging_cleanup(
            pool, entity_id=chapter["draft_id"], requested_prefix=chapter_prefix
        )
        await wait_for_staging_cleanup(
            pool, entity_id=chapter_id, requested_prefix=chapter_prefix
        )
        await _raise_if_operation_cancelled(pool, chapter["draft_id"])
        source_url = chapter["source_url"]

        if is_atsu_url(source_url):
            final_url = source_url
            discovered = await fetch_atsu_chapter_pages(client, source_url)
        else:
            final_url, raw = await _fetch_html(client, source_url)
            adapter = manga_registry.resolve(final_url)
            html = raw.decode("utf-8", errors="replace")

            try:
                discovered = adapter.extract_chapter_pages(final_url, html)
            except ValueError as original_error:
                discovered = None

                # Keep the cheap public mobile fallback for Naver before using
                # a real browser.
                if is_naver_url(final_url):
                    mobile = naver_mobile_url(final_url)
                    if mobile != final_url:
                        try:
                            final_url, raw = await _fetch_html(client, mobile)
                            adapter = manga_registry.resolve(final_url)
                            discovered = adapter.extract_chapter_pages(
                                final_url,
                                raw.decode("utf-8", errors="replace"),
                            )
                        except Exception:
                            discovered = None

                if discovered is None and browser_fallback_available():
                    try:
                        await report_stage_progress(
                            phase="browser_render_fallback",
                            percent=8,
                            message="Static parsing found no reader pages; rendering and scrolling the chapter once with Chromium.",
                        )
                        final_url, raw = await _fetch_html(
                            client,
                            source_url,
                            force_browser=True,
                            browser_scroll=True,
                        )
                        adapter = manga_registry.resolve(final_url)
                        discovered = adapter.extract_chapter_pages(
                            final_url,
                            raw.decode("utf-8", errors="replace"),
                        )
                    except Exception:
                        discovered = None

                if discovered is None:
                    raise original_error

        await _raise_if_operation_cancelled(pool, chapter["draft_id"])

        if len(discovered.page_urls) > MAX_CHAPTER_PAGES:
            raise RuntimeError("Chapter contains too many pages.")
        if not discovered.page_urls:
            raise RuntimeError("Chapter discovery returned no page images.")

        total_pages = len(discovered.page_urls)
        await report_stage_progress(
            phase="downloading_pages",
            percent=10,
            message=f"Downloading {total_pages} source pages into private staging.",
            pages_total=total_pages,
            pages_completed=0,
        )

        semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        progress_lock = asyncio.Lock()
        pages_completed = 0
        last_reported_percent = 10

        async def stage_page(order: int, page_source_url: str) -> dict:
            nonlocal pages_completed, last_reported_percent

            await _raise_if_operation_cancelled(pool, chapter["draft_id"])

            # Deterministic identity makes local staging restart-safe even if a
            # remote PostgreSQL transaction is temporarily unavailable after
            # the image bytes were already downloaded. A retry can reuse the
            # atomically completed local file instead of fetching it again.
            namespace = uuid.UUID(str(chapter_id))
            page_id = str(uuid.uuid5(namespace, f"{order}:{page_source_url}"))
            path_prefix = (
                f"_scraper/series-drafts/{chapter['draft_id']}/"
                f"chapters/{chapter_id}/generations/{claimed_stage_generation}/pages/"
                f"{order:04d}-{page_id}"
            )
            path = await find_staging_by_prefix(path_prefix)
            if path is not None:
                content_type = content_type_for_path(path)
            else:
                async with semaphore:
                    await _raise_if_operation_cancelled(pool, chapter["draft_id"])
                    data, content_type = await _download_image(
                        client,
                        url=page_source_url,
                        referer=final_url,
                    )
                await _raise_if_operation_cancelled(pool, chapter["draft_id"])
                path = (
                    f"{path_prefix}."
                    f"{_extension(content_type, page_source_url)}"
                )
                await _put(client, path, data, content_type)
                await _raise_if_operation_cancelled(pool, chapter["draft_id"])

            async with progress_lock:
                pages_completed += 1
                percent = 10 + int((pages_completed / total_pages) * 80)
                if (
                    percent >= last_reported_percent + 5
                    or pages_completed == total_pages
                ):
                    last_reported_percent = percent
                    await _update_stage_progress(
                        pool,
                        chapter_id,
                        phase="downloading_pages",
                        percent=percent,
                        message=(
                            f"Staged {pages_completed} of {total_pages} pages."
                        ),
                        pages_total=total_pages,
                        pages_completed=pages_completed,
                    )

            staged_paths.add(path)
            return {
                "id": page_id,
                "order": order,
                "source_url": page_source_url,
                "staging_path": path,
                "content_type": content_type,
            }

        page_tasks = [
            asyncio.create_task(stage_page(order, page_source_url))
            for order, page_source_url in enumerate(discovered.page_urls, start=1)
        ]
        try:
            pages = await asyncio.gather(*page_tasks)
        except OperationCancellationRequested:
            for task in page_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*page_tasks, return_exceptions=True)
            raise

        pages.sort(key=lambda page: int(page["order"]))
        await _raise_if_operation_cancelled(pool, chapter["draft_id"])

        async with pool.acquire() as conn:
            async with conn.transaction():
                committed = await conn.fetchrow(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET
                        stage_status = 'ready',
                        pages = $2::jsonb,
                        error_message = NULL,
                        stage_finished_at = NOW(),
                        stage_worker_heartbeat_at = NOW(),
                        stage_progress = jsonb_build_object(
                            'phase', 'completed',
                            'percent', 100,
                            'message', 'Chapter staging completed.',
                            'pages_total', jsonb_array_length($2::jsonb),
                            'pages_completed', jsonb_array_length($2::jsonb),
                            'request_id', COALESCE(stage_progress->>'request_id',''),
                            'updated_at', NOW()
                        ),
                        updated_at = NOW()
                    WHERE id = $1::uuid
                      AND stage_status='staging'
                      AND revision=$3::bigint
                      AND stage_generation=$4::bigint
                    RETURNING id::text
                    """,
                    chapter_id,
                    json.dumps(pages),
                    expected_revision,
                    claimed_stage_generation,
                )
                if committed is None:
                    raise StageWorkerFenceLost(
                        f"stage fence lost for {chapter_id} generation {claimed_stage_generation}"
                    )

                active = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM scraper_series_draft_chapters
                    WHERE draft_id = $1::uuid
                      AND selected = TRUE
                      AND stage_status IN ('queued', 'staging')
                    """,
                    chapter["draft_id"],
                )
                failures = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM scraper_series_draft_chapters
                    WHERE draft_id = $1::uuid
                      AND selected = TRUE
                      AND stage_status = 'error'
                    """,
                    chapter["draft_id"],
                )
                if active == 0:
                    published_series_id = await conn.fetchval(
                        """
                        SELECT published_series_id::text
                        FROM scraper_series_drafts
                        WHERE id = $1::uuid
                        """,
                        chapter["draft_id"],
                    )
                    next_status = (
                        "published_partial"
                        if published_series_id
                        else ("failed" if failures else "ready")
                    )
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET
                            workflow_status = $2::varchar(32),
                            error_message = CASE
                                WHEN $2::varchar(32) = 'failed'
                                THEN 'One or more selected chapters failed staging.'
                                ELSE NULL
                            END,
                            updated_at = NOW()
                        WHERE id = $1::uuid
                          AND workflow_status NOT IN ('queued_publish','publishing','cancel_requested','cancelled')
                        """,
                        chapter["draft_id"],
                        next_status,
                    )

        await record_operation_event(
            pool,
            operation_id=chapter["draft_id"],
            chapter_id=chapter_id,
            request_id=chapter.get("request_id"),
            service="scraper-worker",
            event_type="stage_completed",
            phase="completed",
            status="completed",
            message="Chapter staging completed and page metadata was committed to PostgreSQL.",
            metadata={"pages": len(pages)},
        )

    except StageWorkerFenceLost:
        await _commit_stage_path_cleanup(
            pool,
            chapter_id=chapter_id,
            paths=staged_paths,
            reason="stage_generation_fence_lost",
        )
        return
    except OperationCancellationRequested:
        await _finalize_cancelled_operation(pool, client, chapter["draft_id"])
        return
    except Exception as exc:
        # The final PostgreSQL COMMIT can succeed while its acknowledgement is
        # lost over a network connection. Re-read canonical state before cleanup;
        # if PostgreSQL is unavailable, preserve all local files and let RabbitMQ
        # redelivery/stale-worker recovery decide later.
        async with pool.acquire() as conn:
            canonical = await conn.fetchrow(
                """
                SELECT stage_status, pages, revision, stage_generation
                FROM scraper_series_draft_chapters
                WHERE id=$1::uuid
                """,
                chapter_id,
            )
        if canonical is not None and canonical["stage_status"] == "ready" and list(canonical["pages"] or []):
            return
        if canonical is None or int(canonical["revision"]) != expected_revision or int(canonical["stage_generation"]) != claimed_stage_generation:
            await _commit_stage_path_cleanup(
                pool,
                chapter_id=chapter_id,
                paths=staged_paths,
                reason="stage_generation_fence_lost",
            )
            return

        await _commit_stage_path_cleanup(
            pool,
            chapter_id=chapter_id,
            paths=staged_paths,
            reason=f"chapter_staging_failed:{type(exc).__name__}",
        )
        cleanup_job_id = None
        async with pool.acquire() as conn:
            async with conn.transaction():
                failed = await conn.fetchrow(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET
                        stage_status = 'error',
                        pages = '[]'::jsonb,
                        error_message = $2,
                        stage_finished_at = NOW(),
                        stage_worker_heartbeat_at = NOW(),
                        stage_progress = COALESCE(stage_progress, '{}'::jsonb) || jsonb_build_object(
                            'phase', 'failed',
                            'percent', 100,
                            'message', $2::text,
                            'cleanup_job_id', $3::text,
                            'updated_at', NOW()
                        ),
                        updated_at = NOW()
                    WHERE id = $1::uuid
                      AND revision=$4::bigint AND stage_generation=$5::bigint
                    RETURNING id::text
                    """,
                    chapter_id,
                    str(exc)[:2000],
                    cleanup_job_id,
                    expected_revision,
                    claimed_stage_generation,
                )
                if failed is None:
                    return
                active = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM scraper_series_draft_chapters
                    WHERE draft_id = $1::uuid
                      AND selected = TRUE
                      AND stage_status IN ('queued', 'staging')
                    """,
                    chapter["draft_id"],
                )
                if active == 0:
                    published_series_id = await conn.fetchval(
                        """
                        SELECT published_series_id::text
                        FROM scraper_series_drafts
                        WHERE id = $1::uuid
                        """,
                        chapter["draft_id"],
                    )
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET
                            workflow_status = $2::varchar(32),
                            error_message = 'One or more selected chapters failed staging.',
                            updated_at = NOW()
                        WHERE id = $1::uuid
                          AND workflow_status NOT IN ('queued_publish','publishing','cancel_requested','cancelled')
                        """,
                        chapter["draft_id"],
                        "published_partial" if published_series_id else "failed",
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status='staging',
                            error_message='One or more selected chapters failed; remaining staging work is still running.',
                            updated_at=NOW()
                        WHERE id=$1::uuid
                          AND workflow_status NOT IN ('queued_publish','publishing','cancel_requested','cancelled')
                        """,
                        chapter["draft_id"],
                    )
        await record_operation_event(
            pool,
            operation_id=chapter["draft_id"],
            chapter_id=chapter_id,
            request_id=chapter.get("request_id"),
            service="scraper-worker",
            event_type="stage_failed",
            phase="failed",
            status="failed",
            message=f"Chapter staging failed: {type(exc).__name__}: {exc}",
        )
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _save_pages(
    pool: asyncpg.Pool,
    chapter_id: str,
    pages: list[dict],
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter = await _lock_editable_chapter(conn, chapter_id)
            await _save_manual_pages_locked(
                conn,
                chapter_id=chapter_id,
                draft_id=chapter["draft_id"],
                pages=pages,
            )
    return await get_series_draft(pool, chapter["draft_id"])

async def remove_page(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    chapter_id: str,
    page_id: str,
) -> dict:
    cleanup_job_id: str | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter = await _lock_editable_chapter(conn, chapter_id)
            pages = list(chapter["pages"] or [])
            target = next((page for page in pages if page["id"] == page_id), None)
            if target is None:
                raise HTTPException(404, "Draft page not found.")
            pages = [page for page in pages if page["id"] != page_id]
            await _save_manual_pages_locked(
                conn,
                chapter_id=chapter_id,
                draft_id=chapter["draft_id"],
                pages=pages,
            )
            staging_path = str(target.get("staging_path") or "")
            if staging_path:
                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=chapter_id,
                    local_prefix=staging_path,
                    reason="draft_page_removed",
                )
    return await get_series_draft(pool, chapter["draft_id"])

async def reorder_pages(
    pool: asyncpg.Pool,
    *,
    chapter_id: str,
    page_ids: list[str],
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter = await _lock_editable_chapter(conn, chapter_id)
            pages = list(chapter["pages"] or [])
            current = {page["id"]: page for page in pages}
            if len(page_ids) != len(current) or set(page_ids) != set(current):
                raise HTTPException(400, "page_ids must contain every staged page exactly once.")
            await _save_manual_pages_locked(
                conn,
                chapter_id=chapter_id,
                draft_id=chapter["draft_id"],
                pages=[current[page_id] for page_id in page_ids],
            )
    return await get_series_draft(pool, chapter["draft_id"])

async def add_page_url(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    chapter_id: str,
    url: str,
    position: int | None,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT c.draft_id::text,c.source_url FROM scraper_series_draft_chapters c WHERE c.id=$1::uuid",
            chapter_id,
        )
    if row is None:
        raise HTTPException(404, "Draft chapter not found.")
    data, content_type = await _download_image(client, url=url, referer=row["source_url"])
    page_id = str(uuid.uuid4())
    path = f"_scraper/series-drafts/{row['draft_id']}/chapters/{chapter_id}/pages/manual-{page_id}.{_extension(content_type, url)}"
    await _put(client, path, data, content_type)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                chapter = await _lock_editable_chapter(conn, chapter_id)
                pages = list(chapter["pages"] or [])
                value = {"id": page_id, "order": 0, "source_url": url, "staging_path": path, "content_type": content_type}
                if position is None or position > len(pages):
                    pages.append(value)
                else:
                    pages.insert(max(0, position - 1), value)
                await _save_manual_pages_locked(conn, chapter_id=chapter_id, draft_id=chapter["draft_id"], pages=pages)
    except Exception as exc:
        async with pool.acquire() as conn:
            canonical_pages = await conn.fetchval(
                "SELECT pages FROM scraper_series_draft_chapters WHERE id=$1::uuid",
                chapter_id,
            )
            referenced = any(str(value.get("staging_path") or "") == path for value in (canonical_pages or []))
            if not referenced:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=chapter_id,
                        local_prefix=path,
                        reason=f"draft_page_add_rollback:{type(exc).__name__}",
                    )
        if referenced:
            return await get_series_draft(pool, row["draft_id"])
        raise
    return await get_series_draft(pool, chapter["draft_id"])

async def add_page_upload(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    chapter_id: str,
    file: UploadFile,
    position: int | None,
) -> dict:
    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Uploaded page must be an image.")
    async with pool.acquire() as conn:
        draft_id = await conn.fetchval(
            "SELECT draft_id::text FROM scraper_series_draft_chapters WHERE id=$1::uuid",
            chapter_id,
        )
    if draft_id is None:
        raise HTTPException(404, "Draft chapter not found.")
    page_id = str(uuid.uuid4())
    path = f"_scraper/series-drafts/{draft_id}/chapters/{chapter_id}/pages/manual-{page_id}.{_extension(content_type, file.filename or 'page')}"
    try:
        await put_upload_object(path, file.file, max_bytes=MAX_PAGE_BYTES)
    except ValueError as exc:
        if "empty" in str(exc).lower():
            raise HTTPException(400, "Uploaded page is empty.") from exc
        raise HTTPException(413, "Uploaded page exceeds 50 MiB.") from exc

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                chapter = await _lock_editable_chapter(conn, chapter_id)
                pages = list(chapter["pages"] or [])
                value = {"id": page_id, "order": 0, "source_url": None, "staging_path": path, "content_type": content_type}
                if position is None or position > len(pages):
                    pages.append(value)
                else:
                    pages.insert(max(0, position - 1), value)
                await _save_manual_pages_locked(conn, chapter_id=chapter_id, draft_id=chapter["draft_id"], pages=pages)
    except Exception as exc:
        async with pool.acquire() as conn:
            canonical_pages = await conn.fetchval(
                "SELECT pages FROM scraper_series_draft_chapters WHERE id=$1::uuid",
                chapter_id,
            )
            referenced = any(str(value.get("staging_path") or "") == path for value in (canonical_pages or []))
            if not referenced:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=chapter_id,
                        local_prefix=path,
                        reason=f"draft_page_upload_rollback:{type(exc).__name__}",
                    )
        if referenced:
            return await get_series_draft(pool, draft_id)
        raise
    return await get_series_draft(pool, chapter["draft_id"])

async def preview_page(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    chapter_id: str,
    page_id: str,
) -> tuple[bytes, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pages
            FROM scraper_series_draft_chapters
            WHERE id = $1::uuid
            """,
            chapter_id,
        )

    if row is None:
        raise HTTPException(
            404,
            "Draft chapter not found.",
        )

    page = next(
        (
            page
            for page in row["pages"]
            if page["id"] == page_id
        ),
        None,
    )

    if page is None:
        raise HTTPException(
            404,
            "Draft page not found.",
        )

    return await _get(
        client,
        page["staging_path"],
    )


async def _require_publish_progress_schema(
    pool: asyncpg.Pool,
) -> None:
    """Require durable publish columns without making discovery depend on them."""
    required_draft_columns = {
        "publish_progress",
        "publish_attempt",
        "publish_started_at",
        "publish_finished_at",
        "publish_cancel_requested_at",
        "publish_worker_heartbeat_at",
    }
    required_chapter_columns = {
        "publish_status",
        "publish_error",
        "publish_progress",
        "publish_attempt",
        "publish_started_at",
        "publish_finished_at",
    }

    async with pool.acquire() as conn:
        draft_rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'scraper_series_drafts'
              AND column_name = ANY($1::text[])
            """,
            list(required_draft_columns),
        )
        chapter_rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'scraper_series_draft_chapters'
              AND column_name = ANY($1::text[])
            """,
            list(required_chapter_columns),
        )

    present_draft = {row["column_name"] for row in draft_rows}
    present_chapter = {row["column_name"] for row in chapter_rows}
    missing = sorted(
        [
            *(
                f"scraper_series_drafts.{name}"
                for name in required_draft_columns - present_draft
            ),
            *(
                f"scraper_series_draft_chapters.{name}"
                for name in required_chapter_columns - present_chapter
            ),
        ]
    )

    if missing:
        raise HTTPException(
            503,
            (
                "Scraper resilient-publish migration is required. "
                "Run ./scripts/migrate.sh. Missing columns: "
                + ", ".join(missing)
            ),
        )


class PublishCancellationRequested(Exception):
    pass


async def _is_publish_cancel_requested(
    pool: asyncpg.Pool,
    draft_id: str,
) -> bool:
    cached = _cached_cancel_value("publish", draft_id)
    if cached is not None:
        return cached
    async with pool.acquire() as conn:
        value = await conn.fetchval(
            """
            SELECT (
                publish_cancel_requested_at IS NOT NULL
                OR operation_cancel_requested_at IS NOT NULL
            )
            FROM scraper_series_drafts
            WHERE id = $1::uuid
            """,
            draft_id,
        )
    return _store_cancel_value("publish", draft_id, value is None or bool(value))


async def _update_chapter_publish_state(
    pool: asyncpg.Pool,
    chapter_id: str,
    *,
    status: str | None = None,
    error: str | None = None,
    phase: str | None = None,
    percent: int | None = None,
    message: str | None = None,
    started: bool = False,
    finished: bool = False,
    increment_attempt: bool = False,
    **progress_fields,
) -> None:
    patch = {key: value for key, value in progress_fields.items() if value is not None}
    if phase is not None:
        patch["phase"] = phase
    if percent is not None:
        patch["percent"] = max(0, min(100, int(percent)))
    if message is not None:
        patch["message"] = message
    patch["updated_at"] = _utc_now_iso()

    async with pool.acquire() as conn:
        previous = await conn.fetchrow(
            """
            SELECT draft_id::text, COALESCE(publish_progress->>'phase','') AS phase,
                   NULLIF(publish_progress->>'request_id','') AS request_id
            FROM scraper_series_draft_chapters
            WHERE id=$1::uuid
            """,
            chapter_id,
        )
        await conn.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET publish_status = COALESCE($2::varchar(32), publish_status),
                publish_error=$3,
                publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $4::jsonb,
                publish_attempt=publish_attempt + CASE WHEN $5 THEN 1 ELSE 0 END,
                publish_started_at=CASE WHEN $6 THEN COALESCE(publish_started_at,NOW()) ELSE publish_started_at END,
                publish_finished_at=CASE WHEN $7 THEN NOW() ELSE publish_finished_at END,
                updated_at=NOW()
            WHERE id=$1::uuid
            """,
            chapter_id,
            status,
            error,
            json.dumps(patch),
            increment_attempt,
            started,
            finished,
        )
    if previous and phase and phase != previous["phase"]:
        await record_operation_event(
            pool,
            operation_id=previous["draft_id"],
            chapter_id=chapter_id,
            request_id=previous["request_id"],
            service="scraper-worker",
            event_type="chapter_publish_phase",
            phase=phase,
            status=status or "running",
            message=message or f"Chapter publish phase changed to {phase}.",
            metadata={"percent":patch.get("percent"), "error":error},
        )

async def _ensure_production_series(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft: dict,
) -> str:
    actor_id = str(draft["created_by"])

    async def _read_series_state() -> tuple[str | None, str | None]:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT d.published_series_id::text AS published_series_id,
                       s.id::text AS slug_series_id
                FROM scraper_series_drafts d
                LEFT JOIN series s ON s.slug=d.slug
                WHERE d.id=$1::uuid
                """,
                draft["id"],
            )
        if row is None:
            raise RuntimeError("Series draft disappeared during publish.")
        return (
            str(row["published_series_id"]) if row["published_series_id"] else None,
            str(row["slug_series_id"]) if row["slug_series_id"] else None,
        )

    published_series_id, slug_series_id = await _read_series_state()
    series_id = published_series_id or slug_series_id

    if series_id is None:
        if await _is_publish_cancel_requested(pool, draft["id"]):
            raise PublishCancellationRequested()
        try:
            created = await ensure_catalog_series(
                client,
                title=draft["title"],
                slug=draft["slug"],
                description=draft["description"],
                status=draft["series_status"],
                genre_names=list(draft["genres"] or []),
                tag_names=list(draft["tags"] or []),
                requesting_actor_id=actor_id,
            )
            series_id = str(created["id"])
        except HTTPException:
            # Catalog may have committed successfully while its response was lost.
            # Production reads are allowed here; only Catalog owns the mutation.
            _published, recovered = await _read_series_state()
            if recovered is None:
                raise
            series_id = recovered

    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT published_series_id::text
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft["id"],
            )
            if current is None:
                raise RuntimeError("Series draft disappeared during publish.")
            current_id = str(current["published_series_id"]) if current["published_series_id"] else None
            if current_id and current_id != series_id:
                raise RuntimeError("Series draft was committed to a different production series.")
            if not current_id:
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET published_series_id=$2::uuid, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft["id"],
                    series_id,
                )

    if await _is_publish_cancel_requested(pool, draft["id"]):
        raise PublishCancellationRequested()

    if draft["cover_staging_path"]:
        async with pool.acquire() as conn:
            current_cover = await conn.fetchval(
                "SELECT cover_image_path FROM series WHERE id=$1::uuid",
                series_id,
            )
        if not current_cover:
            await _update_publish_progress(
                pool,
                draft["id"],
                phase="processing_cover",
                percent=3,
                message="Processing the production series cover through Media.",
            )
            cover_raw, cover_content_type = await _get_staged_image(
                client,
                path=draft["cover_staging_path"],
                label="Series cover",
            )
            accepted = await submit_series_cover_to_media(
                client,
                series_slug=draft["slug"],
                image_data=cover_raw,
                content_type=cover_content_type or "application/octet-stream",
                filename=PurePosixPath(draft["cover_staging_path"]).name or "cover.img",
                requesting_actor_id=actor_id,
            )
            job_id = str(accepted.get("job_id") or "")
            if not job_id:
                raise RuntimeError("Media cover acceptance returned no job ID.")
            media_operation = await wait_for_media_job_completion(
                client,
                job_id=job_id,
                requesting_actor_id=actor_id,
            )
            if media_operation.get("status") != "completed":
                raise TransientPublishDeferred("Series cover is still being processed by Media.")
            result = dict(media_operation.get("result") or {})
            if not result.get("image_path"):
                raise RuntimeError("Completed Media cover job returned no canonical image path.")

        async with pool.acquire() as conn:
            async with conn.transaction():
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft["id"],
                    local_prefix=f"_scraper/series-drafts/{draft['id']}/cover",
                    reason="series_cover_published",
                )

    return str(series_id)


def _overall_publish_percent(
    *,
    total_chapters: int,
    processed_chapters: int,
    current_fraction: float = 0.0,
) -> int:
    total = max(1, total_chapters)
    progress = min(
        float(total),
        processed_chapters
        + max(0.0, min(1.0, current_fraction)),
    )
    return min(
        89,
        5 + int(progress / total * 84),
    )


def _new_series_media_operation_id(
    chapter_id: str,
    source_revision: int,
    lease_generation: int,
) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mreader:new-series:{chapter_id}:{int(source_revision)}:{int(lease_generation)}",
        )
    )


async def _publish_one_chapter_commit(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    redis,
    *,
    draft_id: str,
    series_slug: str,
    chapter: dict,
    chapter_index: int,
    total_chapters: int,
    processed_chapters: int,
    global_source_pages_completed: int,
    global_final_pages_written: int,
    requesting_actor_id: str,
) -> tuple[int, int]:
    chapter_id = chapter["id"]

    async with pool.acquire() as canonical_conn:
        already_published = await canonical_conn.fetchval(
            "SELECT published_chapter_id::text FROM scraper_series_draft_chapters WHERE id=$1::uuid",
            chapter_id,
        )
        if already_published:
            async with canonical_conn.transaction():
                await enqueue_local_staging_cleanup(
                    canonical_conn,
                    entity_id=draft_id,
                    local_prefix=f"_scraper/series-drafts/{draft_id}/chapters/{chapter_id}",
                    reason="chapter_already_published_recovery",
                )
            return (0, 0)

    staged_pages = sorted(chapter["pages"], key=lambda value: value["order"])
    if not staged_pages:
        raise RuntimeError("Chapter has no staged pages.")

    await _update_chapter_publish_state(
        pool,
        chapter_id,
        status="publishing",
        error=None,
        phase="media_transform",
        percent=1,
        message="Chapter publication started through Media.",
        started=True,
        increment_attempt=True,
        source_pages_total=len(staged_pages),
        source_pages_completed=0,
        final_pages_written=0,
    )

    if await _is_publish_cancel_requested(pool, draft_id):
        raise PublishCancellationRequested()

    authority = await ensure_ingestion_operation(
        pool,
        operation_id=chapter_id,
        source_kind="new-series-scrape",
        requesting_actor_id=requesting_actor_id,
        parent_operation_id=draft_id,
    )
    source_revision = int(authority["source_revision"])
    lease_generation = int(authority["lease_generation"])
    media_operation_id = _new_series_media_operation_id(
        chapter_id,
        source_revision,
        lease_generation,
    )

    try:
        media_operation = await media_job_status(
            client,
            requesting_actor_id=requesting_actor_id,
            job_id=media_operation_id,
        )
        local_source_completed = 0
        if media_operation.get("status") == "missing":
            raw_pages: list[tuple[int, bytes, str]] = []
            for local_page_index, staged in enumerate(staged_pages, start=1):
                if await _is_publish_cancel_requested(pool, draft_id):
                    raise PublishCancellationRequested()
                raw, content_type = await _get_staged_image(
                    client,
                    path=staged["staging_path"],
                    label=(
                        f"Chapter {chapter.get('chapter_number')} staged page "
                        f"{local_page_index}"
                    ),
                )
                raw_pages.append((int(staged["order"]), raw, content_type))
                local_source_completed = local_page_index
                local_fraction = local_source_completed / max(1, len(staged_pages))
                chapter_percent = min(90, max(1, int(local_fraction * 90)))
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="publishing",
                    error=None,
                    phase="media_transform",
                    percent=chapter_percent,
                    message=(
                        f"Source page {local_page_index}/{len(staged_pages)} "
                        "prepared for Media."
                    ),
                    source_pages_total=len(staged_pages),
                    source_pages_completed=local_source_completed,
                    final_pages_written=0,
                )
                await _update_publish_progress(
                    pool,
                    draft_id,
                    phase="media_transform",
                    percent=_overall_publish_percent(
                        total_chapters=total_chapters,
                        processed_chapters=processed_chapters,
                        current_fraction=local_fraction,
                    ),
                    message=(
                        f"Publishing chapter {chapter_index}/{total_chapters}: "
                        f"{chapter['chapter_slug']} · source page "
                        f"{local_page_index}/{len(staged_pages)}."
                    ),
                    current_chapter_slug=chapter["chapter_slug"],
                    current_chapter_number=str(chapter["chapter_number"]),
                    current_page=local_page_index,
                    chapters_processed=processed_chapters,
                    source_pages_completed=(
                        global_source_pages_completed + local_source_completed
                    ),
                    final_pages_written=global_final_pages_written,
                )

            archive = build_staged_chapter_archive(raw_pages)
            await submit_to_media(
                None,
                MediaSubmission(
                    series_slug=series_slug,
                    chapter_slug=chapter["chapter_slug"],
                    chapter_number=str(chapter["chapter_number"]),
                    title=chapter.get("chapter_title"),
                    archive=archive,
                    source_kind="new-series-scrape",
                    ingestion_operation_id=chapter_id,
                    media_operation_id=media_operation_id,
                    source_revision=source_revision,
                    ingestion_generation=lease_generation,
                    expected_revision=0,
                ),
                client=client,
                requesting_actor_id=requesting_actor_id,
            )
        else:
            local_source_completed = len(staged_pages)

        media_operation = await wait_for_media_publication(
            client,
            requesting_actor_id=requesting_actor_id,
            job_id=media_operation_id,
        )
        result = dict(media_operation.get("result") or {})
        catalog_receipt = result.get("catalog_receipt")
        if media_operation.get("status") != "completed" or not isinstance(catalog_receipt, dict):
            await _update_chapter_publish_state(
                pool,
                chapter_id,
                status="pending",
                error=None,
                phase="media_processing",
                percent=95,
                message="Media accepted the chapter; waiting for the Catalog receipt.",
                finished=False,
                source_pages_total=len(staged_pages),
                source_pages_completed=local_source_completed,
                final_pages_written=0,
                retryable=True,
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL,publish_finished_at=NULL,updated_at=NOW() WHERE id=$1::uuid",
                    chapter_id,
                )
            raise TransientPublishDeferred("Media publication is still reconciling.")

        published_chapter_id = str(catalog_receipt["chapter_id"])
        local_final_written = int(
            catalog_receipt.get("page_count") or result.get("page_count") or 0
        )
        local_source_completed = len(staged_pages)

        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    """
                    SELECT published_chapter_id::text
                    FROM scraper_series_draft_chapters
                    WHERE id=$1::uuid
                    FOR UPDATE
                    """,
                    chapter_id,
                )
                if current is None:
                    raise RuntimeError("Draft chapter disappeared during publish.")
                if current["published_chapter_id"] and str(current["published_chapter_id"]) != published_chapter_id:
                    raise RuntimeError("Chapter was committed by another publisher.")

                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET published_chapter_id=$2::uuid,
                        stage_status='published',publish_status='published',publish_error=NULL,
                        publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                        publish_finished_at=NOW(),updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    chapter_id,
                    published_chapter_id,
                    json.dumps({
                        "phase": "published",
                        "percent": 100,
                        "message": "Chapter committed to production through Catalog.",
                        "source_pages_total": len(staged_pages),
                        "source_pages_completed": local_source_completed,
                        "final_pages_written": local_final_written,
                        "published_chapter_id": published_chapter_id,
                        "updated_at": _utc_now_iso(),
                    }),
                )
                await conn.execute(
                    """
                    UPDATE ingestion_operations
                    SET status='completed',phase='completed',published_count=1,
                        failed_count=0,error_code=NULL,updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    chapter_id,
                )
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft_id,
                    local_prefix=f"_scraper/series-drafts/{draft_id}/chapters/{chapter_id}",
                    reason="chapter_published",
                )

        cache_warnings = await _invalidate_publish_caches(redis)
        if cache_warnings:
            await _update_publish_progress(
                pool,
                draft_id,
                verification_errors=cache_warnings[-20:],
            )
        return local_source_completed, local_final_written

    except PublishCancellationRequested:
        async with pool.acquire() as conn:
            canonical_id = await conn.fetchval(
                "SELECT published_chapter_id::text FROM scraper_series_draft_chapters WHERE id=$1::uuid",
                chapter_id,
            )
        if canonical_id:
            return len(staged_pages), 0
        await _update_chapter_publish_state(
            pool,
            chapter_id,
            status="cancelled",
            error="Publish was cancelled by the administrator.",
            phase="cancelled",
            percent=0,
            message="Chapter stopped before Scraper observed a Catalog receipt.",
            finished=True,
            source_pages_total=len(staged_pages),
            source_pages_completed=0,
            final_pages_written=0,
        )
        raise
    except Exception as exc:
        async with pool.acquire() as conn:
            canonical_id = await conn.fetchval(
                "SELECT published_chapter_id::text FROM scraper_series_draft_chapters WHERE id=$1::uuid",
                chapter_id,
            )
        if canonical_id:
            return len(staged_pages), 0
        if is_transient_error(exc) or isinstance(exc, TransientPublishDeferred):
            await _update_chapter_publish_state(
                pool,
                chapter_id,
                status="pending",
                error=transient_message(exc),
                phase="retry_wait",
                percent=0,
                message=(
                    "Publication is waiting on Media/Catalog reconciliation and will retry "
                    "with the same deterministic operation."
                ),
                finished=False,
                source_pages_total=len(staged_pages),
                source_pages_completed=0,
                final_pages_written=0,
                retryable=True,
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL,publish_finished_at=NULL,updated_at=NOW() WHERE id=$1::uuid",
                    chapter_id,
                )
            if isinstance(exc, TransientPublishDeferred):
                raise
            raise TransientPublishDeferred(transient_message(exc)) from exc

        await _update_chapter_publish_state(
            pool,
            chapter_id,
            status="failed",
            error=str(exc)[:2000],
            phase="failed",
            percent=0,
            message="Chapter failed before Scraper observed a Catalog receipt.",
            finished=True,
            source_pages_total=len(staged_pages),
            source_pages_completed=0,
            final_pages_written=0,
        )
        raise

async def _verification_chapters(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.chapter_number,
                d.chapter_slug,
                c.page_count
            FROM scraper_series_draft_chapters d
            JOIN chapters c
              ON c.id = d.published_chapter_id
            WHERE d.draft_id = $1::uuid
              AND d.selected = TRUE
              AND d.published_chapter_id IS NOT NULL
            ORDER BY d.chapter_number
            """,
            draft_id,
        )

    return [
        {
            "chapter_number": row["chapter_number"],
            "chapter_slug": row["chapter_slug"],
            "final_pages": [None] * int(row["page_count"]),
        }
        for row in rows
    ]


async def queue_publish(
    pool: asyncpg.Pool,
    redis,
    *,
    draft_id: str,
    request_id: str | None = None,
) -> dict:
    await _require_publish_progress_schema(pool)

    async with pool.acquire() as conn:
        async with conn.transaction():
            draft = await conn.fetchrow(
                """
                SELECT id::text, title, slug, workflow_status, published_series_id::text,
                       operation_cancel_requested_at
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if draft is None:
                raise HTTPException(404, "Series draft not found.")
            if draft["workflow_status"] in {"queued_publish", "publishing", "published"}:
                return await get_series_workflow_status(pool, draft_id)
            if draft["workflow_status"] not in {"ready", "failed", "staging", "published_partial", "cancelled"}:
                raise HTTPException(409, f"Series draft cannot publish in its current state: {draft['workflow_status']}.")
            if draft["workflow_status"] == "cancelled":
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET operation_cancel_requested_at=NULL, operation_cancel_requested_by=NULL,
                        publish_cancel_requested_at=NULL, acknowledged_at=NULL, acknowledged_by=NULL,
                        error_message=NULL, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                )
            elif draft["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "Operation cancellation is still in progress.")

            chapters = [dict(row) for row in await conn.fetch(
                """
                SELECT id::text, chapter_number, chapter_slug, selected, stage_status,
                       published_chapter_id::text, publish_status, error_message,
                       jsonb_array_length(COALESCE(pages,'[]'::jsonb))::int AS page_count
                FROM scraper_series_draft_chapters
                WHERE draft_id=$1::uuid
                ORDER BY chapter_number
                FOR UPDATE
                """,
                draft_id,
            )]
            selected = [chapter for chapter in chapters if chapter["selected"]]
            if not selected:
                raise HTTPException(400, "Select at least one chapter.")

            already_published = [c for c in selected if c["published_chapter_id"] or c["stage_status"] == "published" or c.get("publish_status") == "published"]
            published_ids = {c["id"] for c in already_published}
            publishable = [c for c in selected if c["stage_status"] == "ready" and c["id"] not in published_ids]
            publishable_ids = {c["id"] for c in publishable}
            deferred_staging = [c for c in selected if c["id"] not in published_ids and c["id"] not in publishable_ids and c["stage_status"] in {"queued", "staging"}]
            deferred_ids = {c["id"] for c in deferred_staging}
            skipped = [c for c in selected if c["id"] not in published_ids and c["id"] not in publishable_ids and c["id"] not in deferred_ids]
            if not publishable and not deferred_staging:
                if already_published:
                    return await get_series_workflow_status(pool, draft_id)
                raise HTTPException(409, "No selected chapters are ready or still staging. Retry or deselect failed staging chapters.")

            if draft["published_series_id"] is None:
                existing = await conn.fetchrow("SELECT id FROM series WHERE slug=$1", draft["slug"])
                if existing is not None:
                    raise HTTPException(409, "A production series already uses this slug.")

            for chapter in publishable:
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET publish_status='pending', publish_error=NULL, publish_finished_at=NULL,
                        publish_progress=$2::jsonb, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    chapter["id"],
                    json.dumps({
                        "mode":"batch", "phase":"pending", "percent":0,
                        "message":"Waiting for the batch publish coordinator.",
                        "source_pages_total":int(chapter.get("page_count") or 0),
                        "source_pages_completed":0, "final_pages_written":0,
                        "request_id":request_id or "", "updated_at":_utc_now_iso(),
                    }),
                )
            for chapter in deferred_staging:
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET publish_status='pending', publish_error=NULL, publish_finished_at=NULL,
                        publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
                        updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    chapter["id"],
                    json.dumps({
                        "mode":"batch", "phase":"waiting_for_stage", "percent":0,
                        "message":"Batch publish is waiting for this chapter to finish staging.",
                        "request_id":request_id or "", "updated_at":_utc_now_iso(),
                    }),
                )
            for chapter in skipped:
                reason = (chapter.get("error_message") or f"Chapter staging state is {chapter['stage_status']}.")[:2000]
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET publish_status='skipped', publish_error=$2,
                        publish_progress=$3::jsonb, publish_finished_at=NOW(), updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    chapter["id"],
                    reason,
                    json.dumps({
                        "mode":"batch", "phase":"skipped", "percent":100,
                        "message":"Chapter is not staged and is skipped in this publish attempt.",
                        "source_pages_total":int(chapter.get("page_count") or 0),
                        "source_pages_completed":0, "final_pages_written":0,
                        "request_id":request_id or "", "updated_at":_utc_now_iso(),
                    }),
                )

            total_source_pages = sum(int(c.get("page_count") or 0) for c in publishable)
            already_count = len(already_published)
            skipped_count = len(skipped)
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET workflow_status='queued_publish', queue_dispatched_at=NULL,
                    error_message=NULL, publish_attempt=publish_attempt+1,
                    publish_started_at=NULL, publish_finished_at=NULL,
                    publish_cancel_requested_at=NULL, publish_worker_heartbeat_at=NULL,
                    acknowledged_at=NULL, acknowledged_by=NULL,
                    publish_progress=$2::jsonb, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                json.dumps({
                    "mode":"batch", "phase":"queued",
                    "percent":_overall_publish_percent(total_chapters=len(selected), processed_chapters=already_count + skipped_count),
                    "message":f"Publish queued with {len(publishable)} ready, {len(deferred_staging)} staging, and {skipped_count} skipped chapter(s).",
                    "request_id":request_id or "",
                    "total_chapters":len(selected),
                    "chapters_processed":already_count + skipped_count,
                    "chapters_completed":already_count + skipped_count,
                    "chapters_published":already_count,
                    "chapters_failed":0,
                    "chapters_skipped":skipped_count,
                    "chapters_cancelled":0,
                    "chapters_deferred":len(deferred_staging),
                    "total_source_pages":total_source_pages,
                    "source_pages_completed":0,
                    "final_pages_written":0,
                    "catalog_verified":False,
                    "catalog_verified_chapters":0,
                    "reader_verified_chapters":0,
                    "reader_verified_images":0,
                    "verification_errors":[f"{c['chapter_slug']}: skipped because {c.get('error_message') or c['stage_status']}" for c in skipped][-50:],
                    "current_chapter_slug":None,
                    "current_chapter_number":None,
                    "current_page":0,
                    "updated_at":_utc_now_iso(),
                }),
            )
            await _sync_series_ingestion_operation_tx(conn, draft_id)

    await record_operation_event(
        pool,
        operation_id=draft_id,
        service="scraper-api",
        event_type="publish_accepted",
        phase="queued",
        status="queued",
        message=f"Bulk publish accepted for {len(publishable)} ready chapter(s); {len(deferred_staging)} chapter(s) are still staging.",
        request_id=request_id,
        metadata={"ready":len(publishable), "staging":len(deferred_staging), "skipped":len(skipped)},
    )
    try:
        await enqueue_unique(redis, PUBLISH_QUEUE, draft_id, payload={"operation_id":draft_id, "request_id":request_id or ""})
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_series_drafts SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_publish'",
                draft_id,
            )
    except Exception as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET error_message=$2,
                    publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                    updated_at=NOW()
                WHERE id=$1::uuid AND workflow_status='queued_publish'
                """,
                draft_id,
                f"Publish is durable but RabbitMQ enqueue is temporarily unavailable: {exc}"[:2000],
                json.dumps({
                    "phase":"queued_recovery",
                    "message":"Publish is durable in PostgreSQL and will be requeued automatically.",
                    "verification_errors":[f"Queue error: {type(exc).__name__}: {exc}"],
                    "updated_at":_utc_now_iso(),
                }),
            )
        await record_operation_event(
            pool,
            operation_id=draft_id,
            request_id=request_id,
            service="scraper-api",
            event_type="publish_dispatch_deferred",
            phase="queued_recovery",
            status="queued",
            message="RabbitMQ dispatch failed after durable publish acceptance; recovery will requeue it.",
            metadata={"error":f"{type(exc).__name__}: {exc}"},
        )
    return await get_series_draft(pool, draft_id)

async def queue_publish_chapter(
    pool: asyncpg.Pool,
    redis,
    *,
    draft_id: str,
    chapter_id: str,
    request_id: str | None = None,
) -> dict:
    await _require_publish_progress_schema(pool)
    async with pool.acquire() as conn:
        async with conn.transaction():
            draft = await conn.fetchrow(
                """
                SELECT workflow_status, operation_cancel_requested_at
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if draft is None:
                raise HTTPException(404, "Series draft not found.")
            if draft["workflow_status"] in {"queued_publish", "publishing"}:
                raise HTTPException(409, "A batch publish is already running for this series draft.")
            if draft["workflow_status"] in {"queued_discovery", "discovering", "cancel_requested", "duplicate"}:
                raise HTTPException(409, f"Chapter cannot publish while the draft is {draft['workflow_status']}.")
            if draft["workflow_status"] == "cancelled":
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET operation_cancel_requested_at=NULL, operation_cancel_requested_by=NULL,
                        publish_cancel_requested_at=NULL, acknowledged_at=NULL, acknowledged_by=NULL,
                        error_message=NULL, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                )
            elif draft["operation_cancel_requested_at"] is not None:
                raise HTTPException(409, "This scraper operation is being cancelled.")

            chapter = await conn.fetchrow(
                """
                SELECT id::text, stage_status, publish_status, publish_progress,
                       published_chapter_id::text,
                       jsonb_array_length(COALESCE(pages,'[]'::jsonb))::int AS page_count
                FROM scraper_series_draft_chapters
                WHERE id=$1::uuid AND draft_id=$2::uuid
                FOR UPDATE
                """,
                chapter_id,
                draft_id,
            )
            if chapter is None:
                raise HTTPException(404, "Draft chapter not found.")
            if chapter["published_chapter_id"] or chapter["publish_status"] == "published":
                return await get_series_workflow_status(pool, draft_id)
            if chapter["stage_status"] != "ready":
                raise HTTPException(409, "This chapter must finish staging before it can publish.")
            if chapter["publish_status"] == "publishing":
                return await get_series_workflow_status(pool, draft_id)

            queued = await conn.fetchrow(
                """
                UPDATE scraper_series_draft_chapters
                SET selected=TRUE, publish_status='pending', queue_dispatched_at=NULL,
                    publish_error=NULL, publish_finished_at=NULL,
                    publish_progress=jsonb_build_object(
                        'mode','single','phase','queued_single','percent',0,
                        'message','This chapter is queued for independent publish.',
                        'source_pages_total',jsonb_array_length(COALESCE(pages,'[]'::jsonb)),
                        'source_pages_completed',0,'final_pages_written',0,
                        'request_id',$3::text,
                        'updated_at',NOW()
                    ),
                    updated_at=NOW()
                WHERE id=$1::uuid AND draft_id=$2::uuid
                  AND stage_status='ready' AND published_chapter_id IS NULL
                RETURNING id::text
                """,
                chapter_id,
                draft_id,
                request_id or "",
            )
            if queued is None:
                raise HTTPException(409, "Chapter state changed before the publish request could be committed; refresh and retry.")
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET publish_cancel_requested_at=NULL,
                    error_message=CASE WHEN workflow_status='published_partial' THEN error_message ELSE NULL END,
                    acknowledged_at=NULL, acknowledged_by=NULL, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
            )

    await record_operation_event(
        pool,
        operation_id=draft_id,
        chapter_id=chapter_id,
        service="scraper-api",
        event_type="chapter_publish_accepted",
        phase="queued_single",
        status="queued",
        message="Independent chapter publish committed and queued.",
        request_id=request_id,
    )
    try:
        await enqueue_unique(
            redis,
            CHAPTER_PUBLISH_QUEUE,
            chapter_id,
            payload={"operation_id":draft_id, "chapter_id":chapter_id, "request_id":request_id or ""},
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND publish_status='pending'",
                chapter_id,
            )
    except Exception as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scraper_series_draft_chapters
                SET publish_error=$2,
                    publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                    updated_at=NOW()
                WHERE id=$1::uuid
                """,
                chapter_id,
                f"Publish is durable but RabbitMQ enqueue is unavailable: {exc}"[:2000],
                json.dumps({"mode":"single", "phase":"queued_recovery", "message":"Independent publish is durable and will be requeued automatically.", "updated_at":_utc_now_iso()}),
            )
    return await get_series_workflow_status(pool, draft_id)

_LEGACY_TRANSIENT_PUBLISH_ERROR_RE = (
    r"(connect(error|timeout)|readtimeout|writetimeout|pooltimeout|remoteprotocolerror|"
    r"network (is )?unreachable|connection (refused|reset|aborted)|all connection attempts failed|"
    r"temporary failure in name resolution|name or service not known|service unavailable|"
    r"bad gateway|gateway timeout|http[^0-9]*(408|425|429|500|502|503|504)|timed out)"
)


async def recover_incomplete_chapter_publish_jobs(
    pool: asyncpg.Pool,
    redis,
    *,
    stale_seconds: int = 120,
) -> int:
    """Recover durable single-chapter work without duplicating active jobs."""
    try:
        await _require_publish_progress_schema(pool)
    except HTTPException:
        return 0

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id::text, c.draft_id::text, c.publish_status
            FROM scraper_series_draft_chapters c
            JOIN scraper_series_drafts d ON d.id = c.draft_id
            WHERE c.published_chapter_id IS NULL
              AND c.stage_status = 'ready'
              AND COALESCE(c.publish_progress->>'mode', '') = 'single'
              AND d.operation_cancel_requested_at IS NULL
              AND d.workflow_status NOT IN ('queued_publish','publishing','duplicate','cancel_requested')
              AND NOT EXISTS (
                    SELECT 1 FROM scraper_storage_attempts a
                    WHERE a.status IN ('active','cleanup_queued')
                      AND (
                            a.draft_chapter_id=c.id
                            OR (a.draft_id=c.draft_id AND a.operation_type='series_cover')
                      )
              )
              AND (
                    (c.publish_status = 'pending' AND c.queue_dispatched_at IS NULL)
                    OR (
                        c.publish_status = 'publishing'
                        AND c.updated_at < NOW() - ($1::int * INTERVAL '1 second')
                    )
                  )
            ORDER BY c.updated_at
            """,
            stale_seconds,
        )

    queued = 0
    for row in rows:
        chapter_id = row["id"]
        if row["publish_status"] == "publishing":
            async with pool.acquire() as conn:
                async with conn.transaction():
                    projection = await _recover_draft_chapter_publication_tx(conn, chapter_id)
                    if projection == "recovered":
                        await conn.execute(
                            """
                            UPDATE scraper_series_draft_chapters
                            SET publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
                                updated_at=NOW()
                            WHERE id=$1::uuid AND publish_status='pending'
                            """,
                            chapter_id,
                            json.dumps({
                                "mode":"single", "phase":"recovered",
                                "message":"A stale chapter publisher was fenced and requeued.",
                                "updated_at":_utc_now_iso(),
                            }),
                        )
            if projection in {"committed", "cancelled", "terminal"}:
                continue
        try:
            added = await enqueue_unique(
                redis,
                CHAPTER_PUBLISH_QUEUE,
                chapter_id,
                payload={"operation_id": row["draft_id"], "chapter_id": chapter_id},
            )
        except Exception:
            added = False
        if added:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND publish_status='pending'", chapter_id)
            queued += 1
    return queued


async def _refresh_parent_after_single_publish(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    message: str,
) -> None:
    """Refresh parent publish totals without stealing ownership from active workflows."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                d.workflow_status,
                COUNT(c.id) FILTER (WHERE c.selected)::int AS selected_count,
                COUNT(c.id) FILTER (
                    WHERE c.selected AND c.published_chapter_id IS NOT NULL
                )::int AS published_count,
                COUNT(c.id) FILTER (
                    WHERE c.selected AND c.publish_status = 'failed'
                )::int AS failed_count,
                COUNT(c.id) FILTER (
                    WHERE c.selected AND c.publish_status = 'skipped'
                )::int AS skipped_count,
                COUNT(c.id) FILTER (
                    WHERE c.selected AND c.publish_status = 'cancelled'
                )::int AS cancelled_count,
                COUNT(c.id) FILTER (
                    WHERE c.selected AND c.stage_status IN ('queued','staging')
                )::int AS active_stage_count
            FROM scraper_series_drafts d
            LEFT JOIN scraper_series_draft_chapters c ON c.draft_id = d.id
            WHERE d.id = $1::uuid
            GROUP BY d.id
            """,
            draft_id,
        )
        if row is None:
            return

        selected_count = int(row["selected_count"] or 0)
        published_count = int(row["published_count"] or 0)
        failed_count = int(row["failed_count"] or 0)
        skipped_count = int(row["skipped_count"] or 0)
        cancelled_count = int(row["cancelled_count"] or 0)
        active_stage_count = int(row["active_stage_count"] or 0)
        processed_count = published_count + failed_count + skipped_count + cancelled_count
        current_status = str(row["workflow_status"] or "")

        # A chapter-level worker must never overwrite a series coordinator that
        # currently owns discovery, staging, or batch-publish state.
        coordinator_owned = {
            "queued_discovery", "discovering", "staging",
            "queued_publish", "publishing", "cancel_requested", "cancelled",
        }
        if active_stage_count > 0 or current_status in coordinator_owned:
            next_status = current_status
        elif selected_count > 0 and published_count >= selected_count:
            next_status = "published"
        elif processed_count >= selected_count and selected_count > 0:
            next_status = "published_partial" if published_count > 0 else "failed"
        elif published_count > 0:
            next_status = "published_partial"
        else:
            next_status = current_status

        percent = 0
        if selected_count > 0:
            percent = min(100, int(round((processed_count / selected_count) * 100)))
        if next_status == "published":
            percent = 100

        progress_patch = {
            "mode": "single",
            "phase": "chapter_result",
            "percent": percent,
            "message": message,
            "chapters_processed": processed_count,
            "chapters_completed": processed_count,
            "chapters_published": published_count,
            "chapters_failed": failed_count,
            "chapters_skipped": skipped_count,
            "chapters_cancelled": cancelled_count,
            "chapters_deferred": active_stage_count,
            "total_chapters": selected_count,
            "updated_at": _utc_now_iso(),
        }
        await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET
                workflow_status = $2::varchar(32),
                publish_progress = COALESCE(publish_progress, '{}'::jsonb) || $3::jsonb,
                error_message = CASE
                    WHEN $2::varchar(32) = 'published_partial'
                    THEN 'Some chapters are live while others still need staging or publish retry.'
                    WHEN $2::varchar(32) = 'published' THEN NULL
                    ELSE error_message
                END,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            next_status,
            json.dumps(progress_patch),
        )
        await _sync_series_ingestion_operation_tx(conn, draft_id)


def _canonical_publish_lock_key(
    *,
    draft_id: str,
    published_series_id: str | None,
    slug: str | None,
) -> str:
    """Return the lock identity for the logical production series.

    Existing-series update drafts share the production series UUID. New-series
    drafts use the normalized slug so two admins cannot create/publish the same
    logical series concurrently. Different series receive different keys and
    therefore continue to publish in parallel.
    """
    if published_series_id:
        return f"scraper-publish:series:{published_series_id}"
    normalized_slug = (slug or "").strip().lower()
    if normalized_slug:
        return f"scraper-publish:slug:{normalized_slug}"
    return f"scraper-publish:draft:{draft_id}"


async def publish_one_chapter(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    redis,
    chapter_id: str,
) -> None:
    """Publish one staged chapter using the canonical chapter commit path."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.draft_id::text,
                   d.published_series_id::text,
                   d.slug
            FROM scraper_series_draft_chapters c
            JOIN scraper_series_drafts d ON d.id=c.draft_id
            WHERE c.id = $1::uuid
            """,
            chapter_id,
        )
    if row is None:
        return
    draft_id = row["draft_id"]
    publish_lock_key = _canonical_publish_lock_key(
        draft_id=draft_id,
        published_series_id=row["published_series_id"],
        slug=row["slug"],
    )

    async with pool.acquire() as lock_conn:
        acquired = await lock_conn.fetchval(
            """
            SELECT pg_try_advisory_lock(hashtextextended($1, 0))
            """,
            publish_lock_key,
        )
        if not acquired:
            # Keep the durable request pending. Recovery requeues it later; do
            # not hot-loop the same Redis item while another publisher owns the lock.
            await _update_chapter_publish_state(
                pool, chapter_id, status="pending", phase="waiting_for_publish_lock",
                percent=0, message="Waiting for another chapter/batch publisher to release the series lock."
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL, updated_at=NOW() WHERE id=$1::uuid AND publish_status='pending'",
                    chapter_id,
                )
            return

        heartbeat_stop = asyncio.Event()

        async def chapter_publish_heartbeat() -> None:
            while True:
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                    return
                except TimeoutError:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraper_series_draft_chapters SET updated_at=NOW() WHERE id=$1::uuid AND publish_status='publishing'",
                            chapter_id,
                        )

        heartbeat_task = asyncio.create_task(
            chapter_publish_heartbeat(), name=f"scraper-chapter-publish-heartbeat-{chapter_id}"
        )
        try:
            draft = await get_series_draft(pool, draft_id)
            if draft["workflow_status"] in {"queued_publish", "publishing"}:
                await _update_chapter_publish_state(
                    pool, chapter_id, status="pending", phase="waiting_for_batch",
                    percent=0, message="Waiting for the active batch publisher to finish."
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL, updated_at=NOW() WHERE id=$1::uuid AND publish_status='pending'",
                        chapter_id,
                    )
                return
            if await _is_operation_cancel_requested(pool, draft_id):
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="cancelled",
                    error="Scraper operation was cancelled by the administrator.",
                    phase="cancelled",
                    percent=0,
                    message="Independent chapter publish cancelled before processing.",
                    finished=True,
                )
                return

            chapter = next(
                (value for value in draft["chapters"] if value["id"] == chapter_id),
                None,
            )
            if chapter is None:
                return
            if chapter.get("published_chapter_id") or chapter.get("publish_status") == "published":
                return
            if chapter["stage_status"] != "ready":
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="failed",
                    error=f"Chapter staging state changed to {chapter['stage_status']}.",
                    phase="failed",
                    percent=0,
                    message="Chapter is no longer staged and cannot publish yet.",
                    finished=True,
                )
                return
            if (chapter.get("publish_progress") or {}).get("mode") != "single":
                return

            try:
                series_id = await _ensure_production_series(pool, client, draft=draft)
                local_source, local_final = await _publish_one_chapter_commit(
                    pool,
                    client,
                    redis,
                    draft_id=draft_id,
                    series_slug=draft["slug"],
                    chapter=chapter,
                    chapter_index=1,
                    total_chapters=1,
                    processed_chapters=0,
                    global_source_pages_completed=0,
                    global_final_pages_written=0,
                    requesting_actor_id=str(draft["created_by"]),
                )
                await _invalidate_publish_caches(redis)
                verify = await _verify_published_interfaces(
                    pool,
                    client,
                    draft_id=draft_id,
                    slug=draft["slug"],
                    series_id=series_id,
                    chapters=[{
                        "chapter_number": chapter["chapter_number"],
                        "chapter_slug": chapter["chapter_slug"],
                        "final_pages": [None] * max(1, local_final),
                    }],
                )
                warnings = verify.get("verification_errors") or []
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="published",
                    error=None,
                    phase="published",
                    percent=100,
                    message=(
                        "Chapter is live and verified."
                        if not warnings
                        else "Chapter is live; post-publish verification returned warnings."
                    ),
                    finished=True,
                    source_pages_completed=local_source,
                    final_pages_written=local_final,
                    verification_errors=warnings[-20:],
                    mode="single",
                )
                await _refresh_parent_after_single_publish(
                    pool,
                    draft_id=draft_id,
                    message=f"{chapter['chapter_slug']} published independently.",
                )
            except PublishCancellationRequested:
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="cancelled",
                    error="Publish was cancelled by the administrator.",
                    phase="cancelled",
                    percent=0,
                    message="Independent chapter publish was cancelled before commit.",
                    finished=True,
                    mode="single",
                )
                if await _is_operation_cancel_requested(pool, draft_id):
                    await _finalize_cancelled_operation(pool, client, draft_id)
            except TransientPublishDeferred as exc:
                await _update_chapter_publish_state(
                    pool,
                    chapter_id,
                    status="pending",
                    error=str(exc)[:2000],
                    phase="retry_wait",
                    percent=0,
                    message=(
                        "Temporary storage/network interruption detected. "
                        "This chapter will retry automatically after recovery."
                    ),
                    finished=False,
                    mode="single",
                    retryable=True,
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL, publish_finished_at=NULL, updated_at=NOW() WHERE id=$1::uuid",
                        chapter_id,
                    )
                await _refresh_parent_after_single_publish(
                    pool,
                    draft_id=draft_id,
                    message=f"{chapter['chapter_slug']} is waiting for automatic publish retry after a temporary outage.",
                )
            except Exception as exc:
                if is_transient_error(exc):
                    # If PostgreSQL is reachable, persist a retryable state and
                    # ACK this delivery. If PostgreSQL is also unavailable, the
                    # update raises and RabbitMQ redelivery/stale recovery keeps
                    # the durable operation alive.
                    await _update_chapter_publish_state(
                        pool, chapter_id, status="pending", error=transient_message(exc),
                        phase="retry_wait", percent=0,
                        message="Temporary infrastructure outage; automatic retry is pending.",
                        finished=False, mode="single", retryable=True,
                    )
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NULL, publish_finished_at=NULL, updated_at=NOW() WHERE id=$1::uuid",
                            chapter_id,
                        )
                    return
                # _publish_one_chapter_commit already records processing errors.
                # Ensure failures that occur before chapter conversion are also visible.
                async with pool.acquire() as conn:
                    published = await conn.fetchval(
                        "SELECT published_chapter_id IS NOT NULL FROM scraper_series_draft_chapters WHERE id=$1::uuid",
                        chapter_id,
                    )
                if not published:
                    await _update_chapter_publish_state(
                        pool,
                        chapter_id,
                        status="failed",
                        error=str(exc)[:2000],
                        phase="failed",
                        percent=0,
                        message="Independent chapter publish failed. Fix the issue and retry this chapter only.",
                        finished=True,
                        mode="single",
                    )
                await _refresh_parent_after_single_publish(
                    pool,
                    draft_id=draft_id,
                    message=f"{chapter['chapter_slug']} publish failed; other chapters remain independent.",
                )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await lock_conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1, 0))",
                publish_lock_key,
            )


async def request_publish_cancel(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
) -> dict:
    await _require_publish_progress_schema(pool)
    draft = await get_series_draft(pool, draft_id)

    if draft["workflow_status"] not in {
        "queued_publish",
        "publishing",
    }:
        return draft

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _cancel_draft_chapter_publications_tx(conn, draft_id)
            if draft["workflow_status"] == "queued_publish":
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET
                        workflow_status = 'cancelled',
                        publish_cancel_requested_at = NOW(),
                        publish_finished_at = NOW(),
                        publish_progress =
                            publish_progress
                            || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    draft_id,
                    json.dumps({
                        "phase": "cancelled",
                        "message": (
                            "Publish was cancelled before the worker started. "
                            "No committed chapters were removed."
                        ),
                        "updated_at": _utc_now_iso(),
                    }),
                )
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET
                        publish_status = CASE
                            WHEN publish_status = 'pending'
                            THEN 'cancelled'
                            ELSE publish_status
                        END,
                        publish_error = CASE
                            WHEN publish_status = 'pending'
                            THEN 'Publish was cancelled by the administrator.'
                            ELSE publish_error
                        END,
                        publish_finished_at = CASE
                            WHEN publish_status = 'pending'
                            THEN NOW()
                            ELSE publish_finished_at
                        END,
                        updated_at = NOW()
                    WHERE draft_id = $1::uuid
                      AND selected = TRUE
                    """,
                    draft_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET
                        publish_cancel_requested_at = NOW(),
                        publish_progress =
                            publish_progress
                            || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    draft_id,
                    json.dumps({
                        "phase": "cancel_requested",
                        "message": (
                            "Cancellation requested. The worker will stop "
                            "at the next safe page/chapter boundary."
                        ),
                        "updated_at": _utc_now_iso(),
                    }),
                )

    return await get_series_draft(pool, draft_id)


async def _recover_stale_parent_publish_tx(
    conn: asyncpg.Connection,
    draft_id: str,
) -> bool:
    """Fence active chapter attempts and queue the parent only when recovery is safe."""
    active_chapters = await conn.fetch(
        """
        SELECT id::text
        FROM scraper_series_draft_chapters
        WHERE draft_id=$1::uuid
          AND published_chapter_id IS NULL
          AND publish_status='publishing'
        ORDER BY updated_at
        FOR UPDATE
        """,
        draft_id,
    )
    for chapter in active_chapters:
        projection = await _recover_draft_chapter_publication_tx(conn, str(chapter["id"]))
        if projection in {"cancelled", "terminal"}:
            return False

    await conn.execute(
        """
        UPDATE scraper_series_drafts
        SET workflow_status='queued_publish',
            queue_dispatched_at=NULL,
            publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
            updated_at=NOW()
        WHERE id=$1::uuid AND workflow_status='publishing'
        """,
        draft_id,
        json.dumps({
            "phase":"recovered",
            "message":"A stale batch publisher was fenced and requeued.",
            "updated_at":_utc_now_iso(),
        }),
    )
    await _sync_series_ingestion_operation_tx(conn, draft_id)
    return True


async def _stale_parent_publish_rows(
    pool: asyncpg.Pool,
    stale_seconds: int,
):
    return await pool.fetch(
        """
        SELECT id::text, workflow_status, publish_cancel_requested_at
        FROM scraper_series_drafts
        WHERE operation_cancel_requested_at IS NULL
          AND NOT EXISTS (
                SELECT 1 FROM scraper_storage_attempts a
                WHERE a.draft_id=scraper_series_drafts.id AND a.status IN ('active','cleanup_queued')
          )
          AND (
                (workflow_status='queued_publish' AND queue_dispatched_at IS NULL)
                OR (
                    workflow_status='publishing'
                    AND (
                        publish_worker_heartbeat_at IS NULL
                        OR publish_worker_heartbeat_at < NOW() - ($1::int * INTERVAL '1 second')
                    )
                )
              )
        ORDER BY updated_at
        """,
        stale_seconds,
    )


async def _recover_parent_publish_row(pool, redis, row) -> int:
    draft_id = row["id"]
    if row["publish_cancel_requested_at"] is not None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET workflow_status='cancelled', publish_finished_at=NOW(),
                    publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
                    updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                json.dumps({
                    "phase":"cancelled",
                    "message":"Cancellation recovered after worker restart. Previously committed chapters remain published.",
                    "updated_at":_utc_now_iso(),
                }),
            )
            await _sync_series_ingestion_operation_tx(conn, draft_id)
        return 0

    if row["workflow_status"] == "publishing":
        async with pool.acquire() as conn:
            async with conn.transaction():
                if not await _recover_stale_parent_publish_tx(conn, draft_id):
                    return 0
    try:
        added = await enqueue_unique(redis, PUBLISH_QUEUE, draft_id, payload={"operation_id": draft_id})
    except Exception:
        return 0
    if not added:
        return 0
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE scraper_series_drafts SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_publish'",
            draft_id,
        )
    return 1


async def recover_incomplete_publish_jobs(
    pool: asyncpg.Pool,
    redis,
    *,
    stale_seconds: int = 120,
) -> int:
    """Recover queued or stale batch publishes without duplicating active work."""
    try:
        await _require_publish_progress_schema(pool)
    except HTTPException:
        return 0

    rows = await _stale_parent_publish_rows(pool, stale_seconds)
    queued = 0
    for row in rows:
        queued += await _recover_parent_publish_row(pool, redis, row)
    return queued


async def _get_series_publish_metadata(
    pool: asyncpg.Pool,
    draft_id: str,
) -> dict:
    """Load only parent metadata needed by the publisher, never all page JSON."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id::text,
                title,
                slug,
                description,
                series_status,
                source_url,
                cover_source_url,
                cover_staging_path,
                genres,
                tags,
                workflow_status,
                published_series_id::text
            FROM scraper_series_drafts
            WHERE id=$1::uuid
            """,
            draft_id,
        )
    if row is None:
        raise HTTPException(404, "Series draft not found.")
    return dict(row)


async def _batch_publish_summary(pool: asyncpg.Pool, draft_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE selected)::int AS selected_count,
                COUNT(*) FILTER (
                    WHERE selected AND published_chapter_id IS NOT NULL
                )::int AS published_count,
                COUNT(*) FILTER (
                    WHERE selected AND stage_status IN ('queued','staging')
                )::int AS active_stage_count,
                COUNT(*) FILTER (
                    WHERE selected AND published_chapter_id IS NULL
                      AND publish_status='failed'
                )::int AS publish_failed_count,
                COUNT(*) FILTER (
                    WHERE selected AND published_chapter_id IS NULL
                      AND publish_status='skipped'
                )::int AS skipped_count,
                COUNT(*) FILTER (
                    WHERE selected AND published_chapter_id IS NULL
                      AND publish_status='cancelled'
                )::int AS cancelled_count,
                COUNT(*) FILTER (
                    WHERE selected AND published_chapter_id IS NULL
                      AND stage_status='ready'
                      AND COALESCE(publish_status,'pending') NOT IN ('failed','skipped','cancelled','published')
                )::int AS ready_pending_count,
                COALESCE(SUM(
                    CASE WHEN selected THEN jsonb_array_length(COALESCE(pages,'[]'::jsonb)) ELSE 0 END
                ), 0)::bigint AS total_source_pages
            FROM scraper_series_draft_chapters
            WHERE draft_id=$1::uuid
            """,
            draft_id,
        )
    return dict(row or {})


async def _next_batch_publish_chapter(
    pool: asyncpg.Pool,
    draft_id: str,
) -> dict | None:
    """Load page JSON for only the next chapter that can actually publish."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id::text,
                draft_id::text,
                chapter_number,
                chapter_slug,
                chapter_title,
                source_url,
                selected,
                stage_status,
                pages,
                error_message,
                publish_status,
                publish_error,
                COALESCE(publish_progress,'{}'::jsonb) AS publish_progress,
                published_chapter_id::text
            FROM scraper_series_draft_chapters
            WHERE draft_id=$1::uuid
              AND selected=TRUE
              AND published_chapter_id IS NULL
              AND stage_status='ready'
              AND COALESCE(publish_status,'pending') NOT IN ('failed','skipped','cancelled','published')
              AND NOT EXISTS (
                    SELECT 1 FROM scraper_storage_attempts a
                    WHERE a.draft_chapter_id=scraper_series_draft_chapters.id
                      AND a.status IN ('active','cleanup_queued')
              )
            ORDER BY chapter_number ASC
            LIMIT 1
            """,
            draft_id,
        )
    return dict(row) if row else None


async def _mark_unpublishable_selected_as_skipped(
    pool: asyncpg.Pool,
    draft_id: str,
) -> list[str]:
    """Only skip chapters after staging is no longer active."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE scraper_series_draft_chapters
            SET
                publish_status='skipped',
                publish_error=COALESCE(
                    error_message,
                    publish_error,
                    'Chapter did not reach a publishable staged state.'
                ),
                publish_progress=COALESCE(publish_progress,'{}'::jsonb) || jsonb_build_object(
                    'phase','skipped',
                    'percent',100,
                    'message','Staging did not produce a publishable chapter in this batch.',
                    'updated_at',NOW()
                ),
                publish_finished_at=NOW(),
                updated_at=NOW()
            WHERE draft_id=$1::uuid
              AND selected=TRUE
              AND published_chapter_id IS NULL
              AND stage_status NOT IN ('queued','staging','ready','published')
              AND COALESCE(publish_status,'pending') NOT IN ('failed','cancelled','published','skipped')
            RETURNING chapter_slug, COALESCE(error_message,publish_error,'not staged') AS reason
            """,
            draft_id,
        )
    return [f"{row['chapter_slug']}: skipped because {row['reason']}" for row in rows]


async def _defer_series_publish_retry(
    pool: asyncpg.Pool,
    draft_id: str,
    *,
    message: str,
    error: str | None = None,
) -> None:
    """Return a batch publish to its durable queue instead of failing it.

    This is used only for transient infrastructure failures or while an earlier
    partial-storage cleanup is still resolving. The recovery loop republishes
    the compact RabbitMQ reference once the blocking attempt is gone.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET workflow_status='queued_publish',
                queue_dispatched_at=NULL,
                publish_finished_at=NULL,
                error_message=$2,
                publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                updated_at=NOW()
            WHERE id=$1::uuid
              AND workflow_status IN ('queued_publish','publishing')
            """,
            draft_id,
            (error or None),
            json.dumps({
                "phase":"retry_wait",
                "message":message,
                "retryable":True,
                "updated_at":_utc_now_iso(),
            }),
        )
        await _sync_series_ingestion_operation_tx(conn, draft_id)
    await record_operation_event(
        pool,
        operation_id=draft_id,
        service="scraper-worker",
        event_type="publish_retry_wait",
        phase="retry_wait",
        status="queued",
        message=message,
        metadata={"error": error},
    )


async def publish_one_series(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    redis,
    draft_id: str,
) -> None:
    async with pool.acquire() as identity_conn:
        identity = await identity_conn.fetchrow(
            """
            SELECT published_series_id::text, slug
            FROM scraper_series_drafts
            WHERE id=$1::uuid
            """,
            draft_id,
        )
    if identity is None:
        return
    publish_lock_key = _canonical_publish_lock_key(
        draft_id=draft_id,
        published_series_id=identity["published_series_id"],
        slug=identity["slug"],
    )

    async with pool.acquire() as lock_conn:
        acquired = await lock_conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1, 0))",
            publish_lock_key,
        )
        if not acquired:
            # RabbitMQ will ACK a normal return. Clear the dispatch marker first
            # so the durable recovery loop can publish a new broker signal.
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE scraper_series_drafts SET queue_dispatched_at=NULL, updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_publish'",
                    draft_id,
                )
            await record_operation_event(
                pool,
                operation_id=draft_id,
                service="scraper-worker",
                event_type="publish_deferred",
                phase="waiting_for_publish_lock",
                status="queued",
                message="Another publisher owns the series lock; durable recovery will requeue this batch.",
            )
            return

        heartbeat_stop = asyncio.Event()

        async def publish_heartbeat() -> None:
            while True:
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                    return
                except TimeoutError:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraper_series_drafts SET publish_worker_heartbeat_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='publishing'",
                            draft_id,
                        )

        heartbeat_task = asyncio.create_task(
            publish_heartbeat(), name=f"scraper-publish-heartbeat-{draft_id}"
        )
        try:
            draft = await _get_series_publish_metadata(pool, draft_id)
            if draft["workflow_status"] not in {"queued_publish", "publishing"}:
                return

            if await _is_publish_cancel_requested(pool, draft_id):
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status='cancelled', publish_finished_at=NOW(),
                            publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
                            updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                        json.dumps({
                            "phase":"cancelled",
                            "percent":100,
                            "message":"Publish cancelled before the coordinator resumed.",
                            "updated_at":_utc_now_iso(),
                        }),
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)
                return

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET workflow_status='publishing',
                        publish_started_at=COALESCE(publish_started_at,NOW()),
                        publish_worker_heartbeat_at=NOW(),
                        queue_dispatched_at=NOW(),
                        updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    draft_id,
                )
                await _sync_series_ingestion_operation_tx(conn, draft_id)

            await record_operation_event(
                pool,
                operation_id=draft_id,
                service="scraper-worker",
                event_type="publish_worker_started",
                phase="starting",
                status="running",
                message="Batch publish coordinator claimed the durable operation.",
            )

            summary = await _batch_publish_summary(pool, draft_id)
            total_chapters = int(summary.get("selected_count") or 0)
            if total_chapters <= 0:
                raise RuntimeError("Publish operation has no selected chapters.")

            chapters_published = int(summary.get("published_count") or 0)
            chapters_failed = int(summary.get("publish_failed_count") or 0)
            chapters_skipped = int(summary.get("skipped_count") or 0)
            chapters_cancelled = int(summary.get("cancelled_count") or 0)
            processed_chapters = chapters_published + chapters_failed + chapters_skipped + chapters_cancelled
            source_pages_completed = 0
            final_pages_written = 0
            issue_messages: list[str] = []

            await _update_publish_progress(
                pool,
                draft_id,
                phase="starting",
                percent=_overall_publish_percent(
                    total_chapters=total_chapters,
                    processed_chapters=processed_chapters,
                ),
                message=(
                    "Publish coordinator started. It will publish every ready chapter and "
                    "wait for selected staging jobs to finish instead of requiring manual per-chapter clicks."
                ),
                total_chapters=total_chapters,
                chapters_processed=processed_chapters,
                chapters_completed=processed_chapters,
                chapters_published=chapters_published,
                chapters_failed=chapters_failed,
                chapters_skipped=chapters_skipped,
                chapters_cancelled=chapters_cancelled,
                chapters_deferred=int(summary.get("active_stage_count") or 0),
                total_source_pages=int(summary.get("total_source_pages") or 0),
            )

            try:
                await _validate_publish_staging(pool, draft_id)
                series_id = await _ensure_production_series(pool, client, draft=draft)
            except PublishCancellationRequested:
                if await _is_operation_cancel_requested(pool, draft_id):
                    await _finalize_cancelled_operation(pool, client, draft_id)
                    return
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraper_series_drafts SET workflow_status='cancelled', publish_finished_at=NOW(), updated_at=NOW() WHERE id=$1::uuid",
                        draft_id,
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)
                return
            except TransientPublishDeferred as exc:
                await _defer_series_publish_retry(
                    pool,
                    draft_id,
                    message=(
                        "Publish paused because production storage/network connectivity was interrupted. "
                        "It will resume automatically after connectivity and durable cleanup recover."
                    ),
                    error=str(exc)[:2000],
                )
                return
            except Exception as exc:
                if is_transient_error(exc):
                    await _defer_series_publish_retry(
                        pool,
                        draft_id,
                        message=(
                            "Publish preparation hit a temporary infrastructure/network failure. "
                            "The operation remains queued and will retry automatically."
                        ),
                        error=transient_message(exc),
                    )
                    return
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status=CASE WHEN published_series_id IS NOT NULL THEN 'published_partial' ELSE 'failed' END,
                            error_message=$2,
                            publish_finished_at=NOW(),
                            publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                            updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                        str(exc)[:2000],
                        json.dumps({
                            "phase":"failed",
                            "percent":100,
                            "message":"The production series could not be prepared; no previously committed chapter was removed.",
                            "verification_errors":[f"{type(exc).__name__}: {exc}"],
                            "updated_at":_utc_now_iso(),
                        }),
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)
                await record_operation_event(
                    pool,
                    operation_id=draft_id,
                    service="scraper-worker",
                    event_type="publish_failed",
                    phase="prepare_series",
                    status="failed",
                    message=f"Production series preparation failed: {type(exc).__name__}: {exc}",
                )
                return

            cancelled = False
            while True:
                if await _is_publish_cancel_requested(pool, draft_id):
                    cancelled = True
                    break

                chapter = await _next_batch_publish_chapter(pool, draft_id)
                if chapter is not None:
                    summary = await _batch_publish_summary(pool, draft_id)
                    total_chapters = int(summary.get("selected_count") or total_chapters)
                    chapters_published = int(summary.get("published_count") or 0)
                    chapters_failed = int(summary.get("publish_failed_count") or 0)
                    chapters_skipped = int(summary.get("skipped_count") or 0)
                    chapters_cancelled = int(summary.get("cancelled_count") or 0)
                    processed_chapters = chapters_published + chapters_failed + chapters_skipped + chapters_cancelled
                    chapter_index = min(total_chapters, processed_chapters + 1)

                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraper_series_drafts SET publish_worker_heartbeat_at=NOW(), updated_at=NOW() WHERE id=$1::uuid",
                            draft_id,
                        )

                    try:
                        local_source, local_final = await _publish_one_chapter_commit(
                            pool,
                            client,
                            redis,
                            draft_id=draft_id,
                            series_slug=draft["slug"],
                            chapter=chapter,
                            chapter_index=chapter_index,
                            total_chapters=total_chapters,
                            processed_chapters=processed_chapters,
                            global_source_pages_completed=source_pages_completed,
                            global_final_pages_written=final_pages_written,
                            requesting_actor_id=str(draft["created_by"]),
                        )
                        source_pages_completed += local_source
                        final_pages_written += local_final
                    except PublishCancellationRequested:
                        cancelled = True
                        issue_messages.append(f"{chapter['chapter_slug']}: cancelled before commit.")
                        break
                    except TransientPublishDeferred as exc:
                        issue_messages.append(f"{chapter['chapter_slug']}: retry_wait: {exc}")
                        await _defer_series_publish_retry(
                            pool,
                            draft_id,
                            message=(
                                f"{chapter['chapter_slug']} paused on a temporary storage/network outage. "
                                "The batch will resume automatically after recovery."
                            ),
                            error=str(exc)[:2000],
                        )
                        return
                    except Exception as exc:
                        issue_messages.append(f"{chapter['chapter_slug']}: {type(exc).__name__}: {exc}")
                        await _update_publish_progress(
                            pool,
                            draft_id,
                            phase="chapter_failed_continuing",
                            message=f"{chapter['chapter_slug']} failed; the batch is continuing with other chapters.",
                            verification_errors=issue_messages[-50:],
                        )
                    else:
                        await _update_publish_progress(
                            pool,
                            draft_id,
                            phase="chapter_committed",
                            message=f"{chapter['chapter_slug']} committed successfully; continuing automatically.",
                            current_chapter_slug=chapter["chapter_slug"],
                            current_chapter_number=str(chapter["chapter_number"]),
                            current_page=0,
                        )
                    continue

                summary = await _batch_publish_summary(pool, draft_id)
                active_stage = int(summary.get("active_stage_count") or 0)
                if active_stage > 0:
                    published_now = int(summary.get("published_count") or 0)
                    failed_now = int(summary.get("publish_failed_count") or 0)
                    skipped_now = int(summary.get("skipped_count") or 0)
                    cancelled_now = int(summary.get("cancelled_count") or 0)
                    processed_now = published_now + failed_now + skipped_now + cancelled_now
                    await _update_publish_progress(
                        pool,
                        draft_id,
                        phase="waiting_for_staging",
                        percent=_overall_publish_percent(
                            total_chapters=int(summary.get("selected_count") or total_chapters),
                            processed_chapters=processed_now,
                        ),
                        message=f"Waiting for {active_stage} selected chapter(s) still staging; newly-ready chapters will publish automatically.",
                        chapters_processed=processed_now,
                        chapters_completed=processed_now,
                        chapters_published=published_now,
                        chapters_failed=failed_now,
                        chapters_skipped=skipped_now,
                        chapters_cancelled=cancelled_now,
                        chapters_deferred=active_stage,
                    )
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE scraper_series_drafts SET publish_worker_heartbeat_at=NOW(), updated_at=NOW() WHERE id=$1::uuid",
                            draft_id,
                        )
                    await asyncio.sleep(1.0)
                    continue

                ready_pending = int(summary.get("ready_pending_count") or 0)
                if ready_pending > 0:
                    # A ready chapter can be temporarily blocked while durable
                    # cleanup resolves a partial production attempt. Do not
                    # finalize the batch as partial/failed; return it to the
                    # durable recovery queue and let lifecycle cleanup finish.
                    await _defer_series_publish_retry(
                        pool,
                        draft_id,
                        message=(
                            f"Waiting for recovery of {ready_pending} ready chapter(s) after a temporary "
                            "storage/network interruption. Publishing will resume automatically."
                        ),
                    )
                    return

                issue_messages.extend(await _mark_unpublishable_selected_as_skipped(pool, draft_id))
                # No active staging and no ready pending chapter means the batch
                # has exhausted all work for this attempt.
                break

            if cancelled:
                if await _is_operation_cancel_requested(pool, draft_id):
                    await _finalize_cancelled_operation(pool, client, draft_id)
                    return
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status='cancelled', publish_finished_at=NOW(),
                            publish_worker_heartbeat_at=NOW(),
                            publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $2::jsonb,
                            updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                        json.dumps({
                            "phase":"cancelled",
                            "percent":100,
                            "message":"Publish cancelled; chapters already committed remain live.",
                            "updated_at":_utc_now_iso(),
                        }),
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)
                return

            summary = await _batch_publish_summary(pool, draft_id)
            total_chapters = int(summary.get("selected_count") or total_chapters)
            chapters_published = int(summary.get("published_count") or 0)
            chapters_failed = int(summary.get("publish_failed_count") or 0)
            chapters_skipped = int(summary.get("skipped_count") or 0)
            chapters_cancelled = int(summary.get("cancelled_count") or 0)
            processed_chapters = chapters_published + chapters_failed + chapters_skipped + chapters_cancelled

            await _update_publish_progress(
                pool,
                draft_id,
                phase="invalidating_cache",
                percent=90,
                message="Chapter processing finished. Refreshing caches before Catalog/Reader verification.",
                chapters_processed=processed_chapters,
                chapters_completed=processed_chapters,
                chapters_published=chapters_published,
                chapters_failed=chapters_failed,
                chapters_skipped=chapters_skipped,
                chapters_cancelled=chapters_cancelled,
                chapters_deferred=0,
                source_pages_completed=source_pages_completed,
                final_pages_written=final_pages_written,
                verification_errors=issue_messages[-50:],
            )

            issue_messages.extend(await _invalidate_publish_caches(redis))
            verification_chapters = await _verification_chapters(pool, draft_id=draft_id)
            verification = {
                "catalog_verified": False,
                "catalog_verified_chapters": 0,
                "reader_verified_chapters": 0,
                "reader_verified_images": 0,
                "verification_errors": [],
            }
            if verification_chapters:
                verification = await _verify_published_interfaces(
                    pool,
                    client,
                    draft_id=draft_id,
                    slug=draft["slug"],
                    series_id=series_id,
                    chapters=verification_chapters,
                )
                issue_messages.extend(verification["verification_errors"])

            expected_published = len(verification_chapters)
            fully_verified = (
                expected_published > 0
                and verification["catalog_verified"]
                and verification["catalog_verified_chapters"] == expected_published
                and verification["reader_verified_chapters"] == expected_published
                and verification["reader_verified_images"] == expected_published
            )
            partial = (
                chapters_failed > 0
                or chapters_skipped > 0
                or chapters_cancelled > 0
                or chapters_published < total_chapters
            )
            final_status = "published_partial" if partial else "published"
            if partial:
                final_phase = "completed_with_chapter_failures"
                final_message = "Publish completed with partial success. Successful chapters are live; only genuine failed/skipped chapters need attention."
            elif fully_verified and not issue_messages:
                final_phase = "completed"
                final_message = "Publish complete. Every selected chapter committed and Catalog/Reader availability was verified."
            else:
                final_phase = "completed_with_warnings"
                final_message = "All chapters committed, but post-publish verification reported warnings."

            cleanup_warning = None
            cleanup_job_id: str | None = None

            async with pool.acquire() as conn:
                async with conn.transaction():
                    if final_status == "published":
                        cleanup_job_id = await enqueue_local_staging_cleanup(
                            conn,
                            entity_id=draft_id,
                            local_prefix=f"_scraper/series-drafts/{draft_id}",
                            reason="series_publish_completed",
                        )
                    await conn.execute(
                        """
                        UPDATE scraper_series_drafts
                        SET workflow_status=$2::varchar(32),
                            publish_finished_at=NOW(),
                            publish_worker_heartbeat_at=NOW(),
                            publish_cancel_requested_at=NULL,
                            error_message=CASE WHEN $2::varchar(32)='published_partial' THEN 'One or more chapters require staging or publish retry.' ELSE NULL END,
                            publish_progress=COALESCE(publish_progress,'{}'::jsonb) || $3::jsonb,
                            updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        draft_id,
                        final_status,
                        json.dumps({
                            "phase":final_phase,
                            "percent":100,
                            "message":final_message,
                            "database_committed":True,
                            "published_series_id":series_id,
                            "total_chapters":total_chapters,
                            "chapters_processed":processed_chapters,
                            "chapters_completed":processed_chapters,
                            "chapters_published":chapters_published,
                            "chapters_failed":chapters_failed,
                            "chapters_skipped":chapters_skipped,
                            "chapters_cancelled":chapters_cancelled,
                            "chapters_deferred":0,
                            "source_pages_completed":source_pages_completed,
                            "final_pages_written":final_pages_written,
                            "catalog_verified":verification["catalog_verified"],
                            "catalog_verified_chapters":verification["catalog_verified_chapters"],
                            "reader_verified_chapters":verification["reader_verified_chapters"],
                            "reader_verified_images":verification["reader_verified_images"],
                            "verification_errors":issue_messages[-50:],
                            "cleanup_warning":cleanup_warning,
                            "current_chapter_slug":None,
                            "current_chapter_number":None,
                            "current_page":0,
                            "updated_at":_utc_now_iso(),
                        }),
                    )
                    await _sync_series_ingestion_operation_tx(conn, draft_id)
            await record_operation_event(
                pool,
                operation_id=draft_id,
                service="scraper-worker",
                event_type="publish_completed",
                phase=final_phase,
                status=final_status,
                message=final_message,
                metadata={
                    "published":chapters_published,
                    "failed":chapters_failed,
                    "skipped":chapters_skipped,
                    "catalog_verified":verification["catalog_verified"],
                    "reader_verified_chapters":verification["reader_verified_chapters"],
                },
            )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await lock_conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1, 0))",
                publish_lock_key,
            )


async def finalize_pending_cancelled_operations(
    pool: asyncpg.Pool,
    redis,
    client: httpx.AsyncClient,
) -> int:
    """Finish operation-wide cancellations after crashes/restarts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text
            FROM scraper_series_drafts
            WHERE operation_cancel_requested_at IS NOT NULL
              AND workflow_status = 'cancel_requested'
            ORDER BY operation_cancel_requested_at ASC
            """
        )

    finalized = 0
    for row in rows:
        draft_id = row["id"]
        async with pool.acquire() as conn:
            chapter_ids = await conn.fetch(
                "SELECT id::text FROM scraper_series_draft_chapters WHERE draft_id = $1::uuid",
                draft_id,
            )
        try:
            await remove_pending(redis, DISCOVERY_QUEUE, draft_id)
            await remove_pending(redis, PUBLISH_QUEUE, draft_id)
            for chapter in chapter_ids:
                await remove_pending(redis, STAGE_QUEUE, chapter["id"])
                await remove_pending(redis, CHAPTER_PUBLISH_QUEUE, chapter["id"])
        except Exception:
            pass
        await _finalize_cancelled_operation(pool, client, draft_id)
        finalized += 1
    return finalized


async def recover_incomplete_discovery_jobs(
    pool: asyncpg.Pool,
    redis,
    *,
    stale_seconds: int = 90,
) -> int:
    """Recover durable discovery jobs after RabbitMQ/worker restarts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, workflow_status
            FROM scraper_series_drafts
            WHERE operation_cancel_requested_at IS NULL
              AND (
                   (workflow_status = 'queued_discovery' AND queue_dispatched_at IS NULL)
                   OR (
                    workflow_status = 'discovering'
                    AND (
                        discovery_worker_heartbeat_at IS NULL
                        OR discovery_worker_heartbeat_at < NOW() - ($1::int * INTERVAL '1 second')
                    )
                   )
              )
            ORDER BY updated_at ASC
            """,
            stale_seconds,
        )

    queued = 0
    for row in rows:
        draft_id = row["id"]
        if row["workflow_status"] == "discovering":
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scraper_series_drafts
                    SET
                        workflow_status = 'queued_discovery',
                        queue_dispatched_at = NULL,
                        discovery_progress = COALESCE(discovery_progress, '{}'::jsonb) || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                      AND workflow_status = 'discovering'
                    """,
                    draft_id,
                    json.dumps({
                        "phase": "recovered",
                        "message": "A stale discovery worker was detected; the job was safely requeued.",
                        "updated_at": _utc_now_iso(),
                    }),
                )
                await _sync_series_ingestion_operation_tx(conn, draft_id)

        try:
            added = await enqueue_unique(redis, DISCOVERY_QUEUE, draft_id, payload={"operation_id": draft_id})
        except Exception:
            added = False
        if added:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE scraper_series_drafts SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_discovery'", draft_id)
            queued += 1
    return queued


async def recover_incomplete_stage_jobs(
    pool: asyncpg.Pool,
    redis,
    *,
    stale_seconds: int = 120,
) -> int:
    """Recover chapter-stage work that was durable in PostgreSQL but deferred from RabbitMQ."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id::text, c.draft_id::text, c.stage_status
            FROM scraper_series_draft_chapters c
            JOIN scraper_series_drafts d ON d.id = c.draft_id
            WHERE d.operation_cancel_requested_at IS NULL
              AND (
                   (c.stage_status = 'queued' AND c.queue_dispatched_at IS NULL)
                   OR (
                    c.stage_status = 'staging'
                    AND (
                        c.stage_worker_heartbeat_at IS NULL
                        OR c.stage_worker_heartbeat_at < NOW() - ($1::int * INTERVAL '1 second')
                    )
                   )
              )
            ORDER BY c.updated_at ASC
            """,
            stale_seconds,
        )

    queued = 0
    for row in rows:
        chapter_id = row["id"]
        if row["stage_status"] == "staging":
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE scraper_series_draft_chapters
                    SET
                        stage_status = 'queued',
                        stage_generation = stage_generation + 1,
                        queue_dispatched_at = NULL,
                        stage_progress = COALESCE(stage_progress, '{}'::jsonb) || $2::jsonb,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                      AND stage_status = 'staging'
                    """,
                    chapter_id,
                    json.dumps({
                        "phase": "recovered",
                        "message": "A stale staging worker was detected; this chapter was requeued.",
                        "updated_at": _utc_now_iso(),
                    }),
                )
        try:
            added = await enqueue_unique(
                redis,
                STAGE_QUEUE,
                chapter_id,
                payload={"operation_id": row["draft_id"], "chapter_id": chapter_id},
            )
        except Exception:
            added = False
        if added:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE scraper_series_draft_chapters SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND stage_status='queued'", chapter_id)
            queued += 1
    return queued


def _operation_group(operation_status: str | None, workflow_status: str, acknowledged_at) -> str:
    if acknowledged_at is not None:
        return "acknowledged"
    if operation_status in {"queued", "running", "cancel_requested"}:
        return "running"
    if operation_status == "needs_review":
        return "awaiting_admin"
    if operation_status == "completed":
        return "completed"
    if operation_status in {"completed_with_errors", "failed", "cancelled"}:
        return "attention"
    # Compatibility fallback for pre-059 rows while the migration is rolling out.
    if workflow_status in {
        "queued_discovery", "discovering", "staging", "queued_publish", "publishing"
    }:
        return "running"
    if workflow_status in {"draft", "ready"}:
        return "awaiting_admin"
    if workflow_status == "published":
        return "completed"
    if workflow_status in {"published_partial", "failed", "cancelled", "duplicate"}:
        return "attention"
    return "unknown"


def _operation_progress(row: dict) -> dict:
    status = row["workflow_status"]
    if status in {"queued_discovery", "discovering"}:
        return dict(row.get("discovery_progress") or {})
    if status == "staging":
        total = int(row.get("selected_chapters") or 0)
        ready = int(row.get("ready_chapters") or 0)
        errors = int(row.get("stage_error_chapters") or 0)
        completed = ready + errors
        percent = int((completed / total) * 100) if total else 0
        return {
            "phase": "staging",
            "percent": percent,
            "message": f"Staged {completed} of {total} selected chapters.",
            "chapters_total": total,
            "chapters_completed": completed,
            "chapters_ready": ready,
            "chapters_failed": errors,
        }
    if status in {"queued_publish", "publishing", "published", "published_partial", "cancelled"}:
        return dict(row.get("publish_progress") or {})
    if status == "failed" and (row.get("publish_progress") or {}).get("percent", 0):
        return dict(row.get("publish_progress") or {})
    if status == "duplicate":
        return dict(row.get("discovery_progress") or {})
    progress = dict(row.get("discovery_progress") or {})
    if status in {"draft", "ready"}:
        progress.update({
            "phase": "awaiting_admin",
            "percent": 100,
            "message": "Discovery is complete and waiting for administrator review/action.",
        })
    return progress


async def list_scraper_operations(
    pool: asyncpg.Pool,
    redis,
    *,
    state: str = "unacknowledged",
    limit: int = 200,
) -> dict:
    allowed = {"unacknowledged", "running", "awaiting_admin", "completed", "attention", "acknowledged", "all"}
    if state not in allowed:
        raise HTTPException(400, "Invalid scraper operation state filter.")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.id::text,
                d.source_url,
                d.adapter,
                d.title,
                d.slug,
                d.workflow_status,
                io.status AS operation_status,
                io.phase AS operation_phase,
                io.revision AS operation_revision,
                io.lease_generation AS operation_lease_generation,
                io.cancel_requested_at AS operation_cancel_requested_at,
                io.error_code AS operation_error_code,
                d.error_message,
                d.discovery_options,
                d.discovery_progress,
                d.discovery_attempt,
                d.discovery_started_at,
                d.discovery_finished_at,
                d.discovery_worker_heartbeat_at,
                d.operation_cancel_requested_at,
                d.duplicate_series_id::text,
                d.duplicate_series_slug,
                d.duplicate_series_title,
                d.publish_progress,
                d.publish_attempt,
                d.publish_started_at,
                d.publish_finished_at,
                d.publish_worker_heartbeat_at,
                d.published_series_id::text,
                d.acknowledged_at,
                d.acknowledged_by::text,
                d.created_by::text,
                d.created_at,
                d.updated_at,
                COUNT(c.id)::int AS chapter_count,
                COUNT(c.id) FILTER (WHERE c.selected)::int AS selected_chapters,
                COUNT(c.id) FILTER (WHERE c.selected AND c.stage_status IN ('ready','published'))::int AS ready_chapters,
                COUNT(c.id) FILTER (WHERE c.selected AND c.stage_status = 'error')::int AS stage_error_chapters,
                COUNT(c.id) FILTER (WHERE c.publish_status = 'published' OR c.published_chapter_id IS NOT NULL)::int AS published_chapters,
                COUNT(c.id) FILTER (WHERE c.publish_status = 'failed')::int AS publish_failed_chapters
            FROM scraper_series_drafts d
            LEFT JOIN ingestion_operations io ON io.id = d.id
            LEFT JOIN scraper_series_draft_chapters c ON c.draft_id = d.id
            GROUP BY d.id, io.id
            ORDER BY
                CASE WHEN d.acknowledged_at IS NULL THEN 0 ELSE 1 END,
                d.updated_at DESC
            LIMIT $1
            """,
            max(1, min(500, limit)),
        )

    try:
        queue_depths = {
            "discovery": await queue_depth(redis, DISCOVERY_QUEUE),
            "staging": await queue_depth(redis, STAGE_QUEUE),
            "publish": await queue_depth(redis, PUBLISH_QUEUE),
            "chapter_publish": await queue_depth(redis, CHAPTER_PUBLISH_QUEUE),
        }
    except Exception:
        queue_depths = {"discovery": None, "staging": None, "publish": None, "chapter_publish": None}

    items = []
    summary = {
        "running": 0,
        "awaiting_admin": 0,
        "completed": 0,
        "attention": 0,
        "acknowledged": 0,
        "total": 0,
    }

    for record in rows:
        row = dict(record)
        group = _operation_group(row.get("operation_status"), row["workflow_status"], row.get("acknowledged_at"))
        summary[group] = summary.get(group, 0) + 1
        summary["total"] += 1

        if state == "unacknowledged" and group == "acknowledged":
            continue
        if state not in {"all", "unacknowledged"} and group != state:
            continue

        queue_name = None
        queue_position = None
        queue_value = row["id"]
        if row["workflow_status"] == "queued_discovery":
            queue_name = "discovery"
            queue_key = DISCOVERY_QUEUE
        elif row["workflow_status"] == "queued_publish":
            queue_name = "publish"
            queue_key = PUBLISH_QUEUE
        else:
            queue_key = None

        if queue_key is not None:
            try:
                position = await queue_position(redis, queue_key, queue_value)
                if position is not None:
                    queue_position = int(position) + 1
            except Exception:
                queue_position = None

        row["operation_group"] = group
        row["progress"] = _operation_progress(row)
        row["queue_name"] = queue_name
        row["queue_position"] = queue_position
        items.append(row)

    return {
        "items": items,
        "summary": summary,
        "queue_depths": queue_depths,
    }


async def acknowledge_scraper_operation(
    pool: asyncpg.Pool,
    redis,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    admin_id: str,
    request_id: str | None = None,
) -> dict:
    """Archive a terminal operation and durably queue disposable staging cleanup."""
    cleanup_job_id: str | None = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT workflow_status, acknowledged_at
                FROM scraper_series_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if row is None:
                raise HTTPException(404, "Scraper operation not found.")
            if row["workflow_status"] not in {"published", "published_partial", "failed", "cancelled", "duplicate"}:
                raise HTTPException(409, "Only terminal scraper operations can be acknowledged.")
            chapter_ids = [r["id"] for r in await conn.fetch(
                "SELECT id::text FROM scraper_series_draft_chapters WHERE draft_id=$1::uuid",
                draft_id,
            )]
            cleanup_job_id = await enqueue_local_staging_cleanup(
                conn,
                entity_id=draft_id,
                local_prefix=f"_scraper/series-drafts/{draft_id}",
                reason="scraper_operation_acknowledged",
            )
            # The cleanup job owns the entire raw staging tree. Clear every DB
            # pointer into that tree in the very same transaction so the admin
            # UI/API can never advertise a preview path that is scheduled for
            # deletion. Production chapter/page identity remains untouched.
            await conn.execute(
                """
                UPDATE scraper_series_draft_chapters
                SET pages='[]'::jsonb, updated_at=NOW()
                WHERE draft_id=$1::uuid
                """,
                draft_id,
            )
            await conn.execute(
                """
                UPDATE scraper_series_drafts
                SET acknowledged_at=COALESCE(acknowledged_at,NOW()),
                    cover_staging_path=NULL,
                    acknowledged_by=COALESCE(acknowledged_by,$2::uuid),
                    publish_progress=COALESCE(publish_progress,'{}'::jsonb)
                        || jsonb_build_object(
                            'cleanup_job_id',$3::text,
                            'cleanup_durable',TRUE,
                            'updated_at',NOW()
                        ),
                    updated_at=NOW()
                WHERE id=$1::uuid
                """,
                draft_id,
                admin_id,
                cleanup_job_id,
            )
            await _sync_series_ingestion_operation_tx(conn, draft_id)

    await record_operation_event(
        pool,
        operation_id=draft_id,
        request_id=request_id,
        service="scraper-api",
        event_type="operation_acknowledged",
        phase="archived",
        status="acknowledged",
        message="Administrator acknowledged the terminal operation. Staging cleanup is durable and retryable; history is retained.",
        metadata={"workflow_status": row["workflow_status"], "cleanup_job_id": cleanup_job_id},
    )

    # Queue removal is only an optimization. PostgreSQL remains canonical, so
    # stale RabbitMQ deliveries are harmless even when the broker is unavailable.
    try:
        await remove_pending(redis, DISCOVERY_QUEUE, draft_id)
        await remove_pending(redis, PUBLISH_QUEUE, draft_id)
        for chapter_id in chapter_ids:
            await remove_pending(redis, STAGE_QUEUE, chapter_id)
            await remove_pending(redis, CHAPTER_PUBLISH_QUEUE, chapter_id)
    except Exception:
        pass

    return {
        "status": "acknowledged",
        "operation_id": draft_id,
        "removed_from_dashboard": True,
        "acknowledged_by": admin_id,
        "history_retained": True,
        "cleanup_job_id": cleanup_job_id,
    }

async def unacknowledge_scraper_operation(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
) -> dict:
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET acknowledged_at = NULL, acknowledged_by = NULL, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
        )
        if not result.endswith("0"):
            await _sync_series_ingestion_operation_tx(conn, draft_id)
    if result.endswith("0"):
        raise HTTPException(404, "Scraper operation not found.")
    return await get_series_draft(pool, draft_id)


async def retry_series_discovery(
    pool: asyncpg.Pool,
    redis,
    *,
    draft_id: str,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT workflow_status, published_series_id, discovery_progress
            FROM scraper_series_drafts
            WHERE id = $1::uuid
            """,
            draft_id,
        )
        if row is None:
            raise HTTPException(404, "Scraper operation not found.")
        if row["workflow_status"] != "failed" or row["published_series_id"] is not None:
            raise HTTPException(409, "This operation cannot restart series discovery.")
        if (row["discovery_progress"] or {}).get("phase") != "failed":
            raise HTTPException(409, "The failure was not a discovery failure; retry the failed workflow step instead.")

        await conn.execute(
            """
            UPDATE scraper_series_drafts
            SET
                workflow_status = 'queued_discovery',
                queue_dispatched_at = NULL,
                error_message = NULL,
                discovery_finished_at = NULL,
                discovery_worker_heartbeat_at = NULL,
                acknowledged_at = NULL,
                acknowledged_by = NULL,
                discovery_progress = discovery_progress || $2::jsonb,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            json.dumps({
                "phase": "queued",
                "percent": 0,
                "message": "Discovery retry is queued.",
                "updated_at": _utc_now_iso(),
            }),
        )
        await _sync_series_ingestion_operation_tx(conn, draft_id)

    try:
        await enqueue_unique(redis, DISCOVERY_QUEUE, draft_id, payload={"operation_id": draft_id})
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_series_drafts SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND workflow_status='queued_discovery'",
                draft_id,
            )
    except Exception as exc:
        await _update_discovery_progress(
            pool,
            draft_id,
            phase="queued_recovery",
            percent=0,
            message="Discovery retry is durable and will be requeued when RabbitMQ recovers.",
            queue_error=f"{type(exc).__name__}: {exc}"[:1000],
        )
    return await get_series_draft(pool, draft_id)


async def list_series_drafts(
    pool: asyncpg.Pool,
    *,
    limit: int,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                d.id::text,
                d.source_url,
                d.title,
                d.slug,
                d.series_status,
                d.workflow_status,
                d.error_message,
                COALESCE(
                    to_jsonb(d)->'discovery_options',
                    '{"recursive":true,"max_depth":1,"max_pages":20}'::jsonb
                ) AS discovery_options,
                COALESCE(
                    to_jsonb(d)->'discovery_progress',
                    '{"phase":"completed","percent":100,"message":"Legacy discovery completed."}'::jsonb
                ) AS discovery_progress,
                COALESCE(
                    NULLIF(to_jsonb(d)->>'discovery_attempt', '')::integer,
                    0
                ) AS discovery_attempt,
                NULLIF(to_jsonb(d)->>'discovery_started_at', '')::timestamptz AS discovery_started_at,
                NULLIF(to_jsonb(d)->>'discovery_finished_at', '')::timestamptz AS discovery_finished_at,
                NULLIF(to_jsonb(d)->>'discovery_worker_heartbeat_at', '')::timestamptz AS discovery_worker_heartbeat_at,
                NULLIF(to_jsonb(d)->>'acknowledged_at', '')::timestamptz AS acknowledged_at,
                NULLIF(to_jsonb(d)->>'acknowledged_by', '')::uuid::text AS acknowledged_by,
                COALESCE(
                    to_jsonb(d)->'publish_progress',
                    '{"phase":"not_started","percent":0,"message":"Publish progress migration has not been applied yet.","total_chapters":0,"chapters_completed":0,"total_source_pages":0,"source_pages_completed":0,"final_pages_written":0,"catalog_verified":false,"catalog_verified_chapters":0,"reader_verified_chapters":0,"reader_verified_images":0,"verification_errors":[]}'::jsonb
                ) AS publish_progress,
                COALESCE(
                    NULLIF(to_jsonb(d)->>'publish_attempt', '')::integer,
                    0
                ) AS publish_attempt,
                NULLIF(
                    to_jsonb(d)->>'publish_started_at',
                    ''
                )::timestamptz AS publish_started_at,
                NULLIF(
                    to_jsonb(d)->>'publish_finished_at',
                    ''
                )::timestamptz AS publish_finished_at,
                NULLIF(
                    to_jsonb(d)->>'publish_cancel_requested_at',
                    ''
                )::timestamptz AS publish_cancel_requested_at,
                NULLIF(
                    to_jsonb(d)->>'publish_worker_heartbeat_at',
                    ''
                )::timestamptz AS publish_worker_heartbeat_at,
                d.published_series_id::text,
                d.created_at,
                d.updated_at
            FROM scraper_series_drafts d
            ORDER BY d.created_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        dict(row)
        for row in rows
    ]
