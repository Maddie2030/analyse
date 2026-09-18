import asyncio
import json
import mimetypes
import re
import tempfile
import time
import uuid
import zipfile
from decimal import Decimal
from pathlib import PurePosixPath

import asyncpg
import httpx
from fastapi import HTTPException, UploadFile

from app.config import settings
from app.ingestion import MediaSubmission, media_job_status, submit_to_media, wait_for_media_publication
from app.publication_bridge import (
    append_staged_chapter_page,
    ensure_ingestion_operation,
    recover_ingestion_operation_lease_tx,
)
from app.staging_store import get_object, put_object, put_upload_object, StagedObjectMissing, staging_root
from app.queueing import enqueue_unique
from app.storage_attempts import (
    begin_storage_attempt,
    enqueue_local_staging_cleanup,
    mark_storage_attempt_committed,
    resolve_storage_attempt,
    storage_attempt_heartbeat_loop,
)


QUEUE_KEY = "mreader.scraper.batch"
SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".avif",
}
CHAPTER_FOLDER_RE = re.compile(
    r"^ch-(\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_CHAPTER_BYTES = 500 * 1024 * 1024
MAX_BATCH_FILES = 5000


def _parse_relative_path(raw: str) -> tuple[str, str, Decimal]:
    normalized = raw.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized).parts

    if len(parts) < 2:
        raise HTTPException(
            400,
            f"Each file must be inside a chapter folder such as ch-21/. Got: {raw}",
        )

    chapter_folder = parts[0]
    match = CHAPTER_FOLDER_RE.fullmatch(chapter_folder)

    if not match:
        raise HTTPException(
            400,
            f"Invalid chapter folder '{chapter_folder}'. Expected ch-21, ch-22, ch-21.5, etc.",
        )

    chapter_number = Decimal(match.group(1))
    filename = parts[-1]

    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise HTTPException(
            415,
            f"Unsupported image '{filename}' in {chapter_folder}.",
        )

    return chapter_folder.lower(), filename, chapter_number


def _natural_key(filename: str) -> list:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", filename)
    ]


async def _get_filer(
    client: httpx.AsyncClient,
    path: str,
) -> bytes:
    try:
        data, _ = await get_object(client, path)
        return data
    except StagedObjectMissing as exc:
        raise RuntimeError(
            f"Staged batch source is missing: logical_path={path} local_root={staging_root()}. "
            "Batch uploads cannot be reconstructed. Restore the file into the canonical scraper staging PVC "
            "or re-upload the batch before retrying. No PostgreSQL staging metadata was deleted."
        ) from exc


async def create_batch(
    pool: asyncpg.Pool,
    broker,
    client: httpx.AsyncClient,
    *,
    series_id: str,
    created_by: str,
    files: list[UploadFile],
    relative_paths: list[str],
) -> dict:
    if not files:
        raise HTTPException(400, "No files were uploaded.")
    if len(files) != len(relative_paths):
        raise HTTPException(400, "Each uploaded file must include its relative folder path.")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(413, f"Batch exceeds {MAX_BATCH_FILES} files.")

    async with pool.acquire() as conn:
        series = await conn.fetchrow(
            "SELECT id::text, title, slug FROM series WHERE id=$1::uuid",
            series_id,
        )
    if series is None:
        raise HTTPException(404, "Series not found.")

    # Validate all relative paths before mutating durable staging.
    parsed: list[tuple[str, str, Decimal]] = [
        _parse_relative_path(relative_path) for relative_path in relative_paths
    ]
    batch_id = str(uuid.uuid4())
    local_prefix = f"_scraper/batches/{batch_id}"
    attempt_id = await begin_storage_attempt(
        pool,
        operation_type="batch_stage_create",
        local_staging_prefix=local_prefix,
    )
    attempt_stop = asyncio.Event()
    attempt_heartbeat = asyncio.create_task(
        storage_attempt_heartbeat_loop(pool, attempt_id, attempt_stop),
        name=f"batch-stage-attempt-{attempt_id}",
    )
    grouped: dict[str, dict] = {}

    try:
        # Starlette already spools multipart uploads. Copy each upload directly
        # into the durable scraper spool, one at a time, instead of retaining an
        # entire multi-chapter batch as Python bytes in RAM.
        for upload, relative_path, parsed_value in zip(files, relative_paths, parsed, strict=True):
            chapter_slug, filename, chapter_number = parsed_value
            content_type = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            if not content_type.startswith("image/"):
                raise HTTPException(415, f"Unsupported non-image file: {relative_path}")

            item = grouped.setdefault(
                chapter_slug,
                {
                    "chapter_slug": chapter_slug,
                    "chapter_number": chapter_number,
                    "files": [],
                    "total_bytes": 0,
                },
            )
            suffix = PurePosixPath(filename).suffix.lower().lstrip(".") or "img"
            source_id = str(uuid.uuid4())
            path = f"{local_prefix}/{chapter_slug}/incoming-{source_id}.{suffix}"
            try:
                size = await put_upload_object(path, upload.file, max_bytes=MAX_FILE_BYTES)
            except ValueError as exc:
                message = str(exc)
                if "empty" in message.lower():
                    raise HTTPException(400, f"Empty image: {relative_path}") from exc
                raise HTTPException(413, f"Image too large: {relative_path}") from exc

            item["total_bytes"] += size
            if item["total_bytes"] > MAX_CHAPTER_BYTES:
                raise HTTPException(413, f"{chapter_slug} exceeds 500 MiB.")
            item["files"].append(
                {
                    "filename": filename,
                    "staging_path": path,
                    "content_type": content_type,
                    "size_bytes": size,
                }
            )

        for item in grouped.values():
            item["files"].sort(key=lambda value: _natural_key(value["filename"]))
            for index, source in enumerate(item["files"], start=1):
                source["order"] = index

        queued_item_ids: list[str] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO scraper_batch_uploads (id,target_series_id,status,total_items,created_by)
                    VALUES ($1::uuid,$2::uuid,'queued',$3,$4::uuid)
                    """,
                    batch_id,
                    series_id,
                    len(grouped),
                    created_by,
                )
                # Bind the pre-storage attempt to the canonical batch in the
                # same transaction that creates it. An ambiguous COMMIT can
                # therefore be resolved without deleting a successfully-created
                # batch's local source files.
                await conn.execute(
                    "UPDATE scraper_storage_attempts SET batch_id=$2::uuid, updated_at=NOW() WHERE id=$1::uuid",
                    attempt_id,
                    batch_id,
                )

                for chapter_slug, item in grouped.items():
                    existing = await conn.fetchrow(
                        """
                        SELECT id::text FROM chapters
                        WHERE series_id=$1::uuid AND (slug=$2 OR chapter_number=$3)
                        LIMIT 1
                        """,
                        series_id,
                        chapter_slug,
                        item["chapter_number"],
                    )
                    status = "failed_conflict" if existing is not None else "queued"
                    error = "Chapter already exists. Admin action required." if existing is not None else None
                    row = await conn.fetchrow(
                        """
                        INSERT INTO scraper_batch_items (
                            batch_id,target_series_id,chapter_number,chapter_slug,source_files,
                            status,existing_chapter_id,error_message
                        ) VALUES ($1::uuid,$2::uuid,$3,$4,$5::jsonb,$6,$7::uuid,$8)
                        RETURNING id::text
                        """,
                        batch_id,
                        series_id,
                        item["chapter_number"],
                        chapter_slug,
                        json.dumps(item["files"]),
                        status,
                        existing["id"] if existing else None,
                        error,
                    )
                    if status == "queued":
                        queued_item_ids.append(row["id"])

                await mark_storage_attempt_committed(conn, attempt_id, batch_id)

        # PostgreSQL is canonical; RabbitMQ is only an execution signal.
        for queued_item_id in queued_item_ids:
            try:
                await enqueue_unique(broker, QUEUE_KEY, queued_item_id)
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraper_batch_items SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND status='queued'",
                        queued_item_id,
                    )
            except Exception:
                pass
        return await get_batch(pool, batch_id)

    except Exception as exc:
        # Never infer DB rollback from a failed COMMIT acknowledgement. Resolve
        # the attempt against canonical PostgreSQL state first. If PostgreSQL is
        # unreachable, resolve_storage_attempt raises and all local bytes are
        # deliberately retained for later recovery.
        outcome = await resolve_storage_attempt(
            pool,
            attempt_id,
            error=f"batch create failed: {type(exc).__name__}: {exc}"[:2000],
        )
        if outcome == "committed":
            return await get_batch(pool, batch_id)
        raise
    finally:
        attempt_stop.set()
        attempt_heartbeat.cancel()
        await asyncio.gather(attempt_heartbeat, return_exceptions=True)

async def get_batch(
    pool: asyncpg.Pool,
    batch_id: str,
) -> dict:
    async with pool.acquire() as conn:
        batch = await conn.fetchrow(
            """
            SELECT
                b.id::text,
                b.target_series_id::text,
                s.title AS series_title,
                s.slug AS series_slug,
                b.status,
                b.total_items,
                b.created_by::text,
                b.created_at,
                b.updated_at
            FROM scraper_batch_uploads b
            JOIN series s ON s.id = b.target_series_id
            WHERE b.id = $1::uuid
            """,
            batch_id,
        )

        if batch is None:
            raise HTTPException(404, "Batch not found.")

        items = await conn.fetch(
            """
            SELECT
                id::text,
                batch_id::text,
                target_series_id::text,
                chapter_number,
                chapter_slug,
                status,
                existing_chapter_id::text,
                published_chapter_id::text,
                error_message,
                source_files,
                created_at,
                updated_at
            FROM scraper_batch_items
            WHERE batch_id = $1::uuid
            ORDER BY chapter_number ASC
            """,
            batch_id,
        )

    value = dict(batch)
    value["items"] = [dict(row) for row in items]
    return value


async def list_batches(
    pool: asyncpg.Pool,
    *,
    series_id: str | None,
    limit: int,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                b.id::text,
                b.target_series_id::text,
                s.title AS series_title,
                s.slug AS series_slug,
                b.status,
                b.total_items,
                COUNT(*) FILTER (
                    WHERE i.status = 'completed'
                )::int AS completed_items,
                COUNT(*) FILTER (
                    WHERE i.status = 'failed_conflict'
                )::int AS conflict_items,
                COUNT(*) FILTER (
                    WHERE i.status = 'failed_error'
                )::int AS error_items,
                COUNT(*) FILTER (
                    WHERE i.status = 'queued'
                )::int AS queued_items,
                COUNT(*) FILTER (
                    WHERE i.status = 'processing'
                )::int AS processing_items,
                b.created_at,
                b.updated_at
            FROM scraper_batch_uploads b
            JOIN series s ON s.id = b.target_series_id
            LEFT JOIN scraper_batch_items i ON i.batch_id = b.id
            WHERE (
                $1::uuid IS NULL
                OR b.target_series_id = $1::uuid
            )
            GROUP BY
                b.id,
                b.target_series_id,
                s.title,
                s.slug,
                b.status,
                b.total_items,
                b.created_at,
                b.updated_at
            ORDER BY b.created_at DESC
            LIMIT $2
            """,
            series_id,
            limit,
        )

    return [dict(row) for row in rows]


async def list_failed_items(
    pool: asyncpg.Pool,
    *,
    series_id: str | None,
    limit: int,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                i.id::text,
                i.batch_id::text,
                i.target_series_id::text,
                s.title AS series_title,
                s.slug AS series_slug,
                i.chapter_number,
                i.chapter_slug,
                i.status,
                i.existing_chapter_id::text,
                i.error_message,
                i.created_at,
                i.updated_at
            FROM scraper_batch_items i
            JOIN series s ON s.id = i.target_series_id
            WHERE i.status IN (
                'failed_conflict',
                'failed_error'
            )
              AND (
                $1::uuid IS NULL
                OR i.target_series_id = $1::uuid
              )
            ORDER BY i.updated_at DESC
            LIMIT $2
            """,
            series_id,
            limit,
        )

    return [dict(row) for row in rows]


async def _refresh_batch_status(
    conn: asyncpg.Connection,
    batch_id: str,
) -> None:
    counts = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE status IN ('queued', 'processing')
            )::int AS active,
            COUNT(*) FILTER (
                WHERE status IN ('failed_conflict', 'failed_error')
            )::int AS failed,
            COUNT(*) FILTER (
                WHERE status = 'completed'
            )::int AS completed,
            COUNT(*) FILTER (
                WHERE status = 'discarded'
            )::int AS discarded,
            COUNT(*)::int AS total
        FROM scraper_batch_items
        WHERE batch_id = $1::uuid
        """,
        batch_id,
    )

    if counts["active"] > 0:
        status = "processing"
    elif counts["failed"] > 0:
        status = "needs_attention"
    elif counts["completed"] + counts["discarded"] == counts["total"]:
        status = "completed"
    else:
        status = "queued"

    await conn.execute(
        """
        UPDATE scraper_batch_uploads
        SET
            status = $2::varchar(32),
            updated_at = NOW()
        WHERE id = $1::uuid
        """,
        batch_id,
        status,
    )


async def resolve_conflict(
    pool: asyncpg.Pool,
    broker,
    client: httpx.AsyncClient,
    *,
    item_id: str,
    action: str,
) -> dict:
    async with pool.acquire() as conn:
        item = await conn.fetchrow(
            """
            SELECT
                id::text,
                batch_id::text,
                target_series_id::text,
                chapter_number,
                chapter_slug,
                status,
                existing_chapter_id::text,
                overwrite_requested_at,
                source_files
            FROM scraper_batch_items
            WHERE id = $1::uuid
            """,
            item_id,
        )

        if item is None:
            raise HTTPException(404, "Batch item not found.")

        if item["status"] not in {
            "failed_conflict",
            "failed_error",
        }:
            raise HTTPException(
                409,
                "This item is not waiting for admin action.",
            )

    if action == "discard":
        cleanup_job_id: str | None = None
        async with pool.acquire() as conn:
            async with conn.transaction():
                cleanup_job_id = await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=item_id,
                    local_prefix=f"_scraper/batches/{item['batch_id']}/{item['chapter_slug']}",
                    reason="batch_item_discarded",
                )
                await conn.execute(
                    """
                    UPDATE scraper_batch_items
                    SET status='discarded', overwrite_requested_at=NULL,
                        error_message=NULL, source_files='[]'::jsonb, updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    item_id,
                )
                await _refresh_batch_status(conn, item["batch_id"])

        return {
            "id": item_id,
            "status": "discarded",
            "cleanup_job_id": cleanup_job_id,
        }

    if action != "overwrite":
        raise HTTPException(400, "Unsupported action.")

    # Explicit admin overwrite is intentionally non-destructive. The existing
    # chapter remains live while the worker converts/uploads replacement assets.
    # The worker later swaps the page rows inside one DB transaction and queues
    # old immutable objects for lifecycle cleanup after commit.
    if not item["existing_chapter_id"]:
        raise HTTPException(409, "The existing chapter is no longer available for overwrite.")

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT 1
            FROM chapters
            WHERE id = $1::uuid AND series_id = $2::uuid
            """,
            item["existing_chapter_id"],
            item["target_series_id"],
        )
        if not exists:
            raise HTTPException(409, "The existing chapter is no longer available for overwrite.")
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE scraper_batch_items
                SET status='queued', queue_dispatched_at=NULL,
                    overwrite_requested_at=NOW(), error_message=NULL, updated_at=NOW()
                WHERE id=$1::uuid
                """,
                item_id,
            )
            await _advance_batch_ingestion_fence(conn, item_id)
            await _refresh_batch_status(conn, item["batch_id"])

    try:
        await enqueue_unique(broker, QUEUE_KEY, item_id)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_batch_items SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND status='queued'",
                item_id,
            )
    except Exception:
        # Durable queued state remains recoverable when RabbitMQ returns.
        pass

    return {
        "id": item_id,
        "status": "queued",
        "action": "overwrite",
    }


async def retry_failed_item(
    pool: asyncpg.Pool,
    broker,
    *,
    item_id: str,
) -> dict:
    async with pool.acquire() as conn:
        item = await conn.fetchrow(
            """
            SELECT
                id::text,
                batch_id::text,
                status
            FROM scraper_batch_items
            WHERE id = $1::uuid
            """,
            item_id,
        )

        if item is None:
            raise HTTPException(404, "Batch item not found.")

        if item["status"] != "failed_error":
            raise HTTPException(
                409,
                "Only processing failures can be retried directly.",
            )

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE scraper_batch_items
                SET
                    status = 'queued',
                    queue_dispatched_at = NULL,
                    error_message = NULL,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                item_id,
            )
            await _advance_batch_ingestion_fence(conn, item_id)
            await _refresh_batch_status(
                conn,
                item["batch_id"],
            )

    try:
        await enqueue_unique(broker, QUEUE_KEY, item_id)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE scraper_batch_items SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND status='queued'",
                item_id,
            )
    except Exception:
        pass

    return {
        "id": item_id,
        "status": "queued",
    }


async def recover_batch_jobs(
    pool: asyncpg.Pool,
    broker,
    *,
    reset_processing: bool = False,
    stale_seconds: int = 180,
) -> dict[str, int]:
    """Repair deferred or stale durable batch work without stealing live replicas.

    RabbitMQ quorum queues retain successfully dispatched jobs. PostgreSQL's
    queue_dispatched_at therefore identifies only work that still needs a
    broker signal. Processing rows are reset only when their heartbeat is stale,
    which is safe when Kubernetes starts additional worker replicas.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            reset_rows = await _recover_stale_batch_items_tx(
                conn,
                stale_seconds=max(30, int(stale_seconds)),
            )
            reset_count = sum(1 for row in reset_rows if row.get("legacy_status") == "queued")
            for batch_id in {row["batch_id"] for row in reset_rows}:
                await _refresh_batch_status(conn, batch_id)

    async with pool.acquire() as conn:
        queued_rows = await conn.fetch(
            """
            SELECT id::text
            FROM scraper_batch_items
            WHERE status='queued'
              AND queue_dispatched_at IS NULL
            ORDER BY updated_at ASC
            """
        )

    enqueued = 0
    for row in queued_rows:
        try:
            if await enqueue_unique(broker, QUEUE_KEY, row["id"]):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE scraper_batch_items SET queue_dispatched_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND status='queued'",
                        row["id"],
                    )
                enqueued += 1
        except Exception:
            # Keep durable queued state; the next recovery tick retries.
            break

    return {
        "reset_processing": reset_count,
        "enqueued_missing": enqueued,
        "queued_rows": len(queued_rows),
    }


async def _recover_stale_batch_item_tx(
    conn: asyncpg.Connection,
    row,
) -> dict:
    """Project canonical ingestion recovery back into the legacy batch row."""
    item_id = str(row["id"])
    outcome = await recover_ingestion_operation_lease_tx(conn, item_id)
    canonical_status = str((outcome or {}).get("status") or "")

    if (outcome or {}).get("committed") and (outcome or {}).get("chapter_id"):
        await conn.execute(
            """
            UPDATE scraper_batch_items
            SET status='completed',published_chapter_id=$2::uuid,
                processing_heartbeat_at=NULL,error_message=NULL,updated_at=NOW()
            WHERE id=$1::uuid
            """,
            item_id,
            outcome["chapter_id"],
        )
        legacy_status = "completed"
    elif canonical_status == 'cancelled':
        await conn.execute(
            """
            UPDATE scraper_batch_items
            SET status='discarded',queue_dispatched_at=NULL,processing_heartbeat_at=NULL,
                error_message=COALESCE(error_message,'Canonical ingestion operation was cancelled.'),updated_at=NOW()
            WHERE id=$1::uuid
            """,
            item_id,
        )
        legacy_status = "discarded"
    elif (outcome or {}).get("recovered"):
        await conn.execute(
            """
            UPDATE scraper_batch_items
            SET status='queued',queue_dispatched_at=NULL,processing_heartbeat_at=NULL,
                error_message=COALESCE(error_message,'Recovered stale scraper batch worker.'),updated_at=NOW()
            WHERE id=$1::uuid
            """,
            item_id,
        )
        legacy_status = "queued"
    else:
        legacy_status = str(row.get("status") or "processing") if hasattr(row, "get") else "processing"

    return {
        "id": item_id,
        "batch_id": str(row["batch_id"]),
        "canonical_status": canonical_status,
        "legacy_status": legacy_status,
    }


async def _recover_stale_batch_items_tx(
    conn: asyncpg.Connection,
    *,
    stale_seconds: int,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT i.id::text,i.batch_id::text,i.status
        FROM scraper_batch_items AS i
        WHERE i.status='processing'
          AND (
            i.processing_heartbeat_at IS NULL
            OR i.processing_heartbeat_at < NOW() - ($1::int * INTERVAL '1 second')
          )
          AND NOT EXISTS (
            SELECT 1 FROM scraper_storage_attempts a
            WHERE a.batch_item_id=i.id AND a.status='active'
          )
        ORDER BY i.updated_at ASC
        FOR UPDATE OF i
        """,
        stale_seconds,
    )
    recovered: list[dict] = []
    for row in rows:
        recovered.append(await _recover_stale_batch_item_tx(conn, row))
    return recovered


async def _set_batch_ingestion_terminal(
    conn: asyncpg.Connection,
    operation_id: str,
    *,
    status: str,
    phase: str,
    error_code: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE ingestion_operations
        SET status=$2,phase=$3,error_code=$4,updated_at=NOW()
        WHERE id=$1::uuid
        """,
        operation_id,
        status,
        phase,
        error_code,
    )


async def _advance_batch_ingestion_fence(conn: asyncpg.Connection, operation_id: str) -> None:
    """Start an explicit new attempt without changing identity of the batch item."""
    await conn.execute(
        """
        UPDATE ingestion_operations
        SET source_revision=source_revision+1,
            revision=revision+1,
            lease_generation=lease_generation+1,
            status='running',phase='media_transform',error_code=NULL,updated_at=NOW()
        WHERE id=$1::uuid
          AND status NOT IN ('completed','completed_with_errors','cancelled')
        """,
        operation_id,
    )


def _batch_media_operation_id(item_id: str, source_revision: int, lease_generation: int) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mreader:batch:{item_id}:{int(source_revision)}:{int(lease_generation)}",
        )
    )


async def _current_conflicting_chapter(
    conn: asyncpg.Connection,
    *,
    series_id: str,
    chapter_slug: str,
    chapter_number,
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id::text,catalog_revision
        FROM chapters
        WHERE series_id=$1::uuid AND (slug=$2 OR chapter_number=$3)
        LIMIT 1
        """,
        series_id,
        chapter_slug,
        chapter_number,
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "catalog_revision": int(row["catalog_revision"] or 0),
    }


async def process_item(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    item_id: str,
) -> None:
    """Publish one staged batch chapter through Media evidence -> Catalog receipt."""
    async with pool.acquire() as conn:
        item = await conn.fetchrow(
            """
            UPDATE scraper_batch_items AS i
            SET status='processing', processing_started_at=NOW(),
                processing_heartbeat_at=NOW(), updated_at=NOW()
            FROM series AS s, scraper_batch_uploads AS b
            WHERE i.id=$1::uuid
              AND i.target_series_id=s.id
              AND i.batch_id=b.id
              AND i.status='queued'
            RETURNING i.id::text,i.batch_id::text,i.target_series_id::text,
                      i.chapter_number,i.chapter_slug,i.status,i.source_files,
                      i.existing_chapter_id::text,i.overwrite_requested_at,
                      s.slug AS series_slug,b.created_by::text
            """,
            item_id,
        )
    if item is None:
        return

    item = dict(item)
    publication_receipt: dict | None = None
    media_operation_id: str | None = None
    authority: dict | None = None

    try:
        async with pool.acquire() as conn:
            conflict = await _current_conflicting_chapter(
                conn,
                series_id=item["target_series_id"],
                chapter_slug=item["chapter_slug"],
                chapter_number=item["chapter_number"],
            )
        overwrite_allowed = bool(
            conflict is not None
            and item["overwrite_requested_at"] is not None
            and item["existing_chapter_id"]
            and str(conflict["id"]) == str(item["existing_chapter_id"])
        )
        if conflict is not None and not overwrite_allowed:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE scraper_batch_items
                        SET status='failed_conflict',processing_heartbeat_at=NULL,
                            existing_chapter_id=$2::uuid,overwrite_requested_at=NULL,
                            error_message='Chapter already exists. Admin action required.',updated_at=NOW()
                        WHERE id=$1::uuid
                        """,
                        item_id,
                        conflict["id"],
                    )
                    await _refresh_batch_status(conn, item["batch_id"])
            return

        authority = await ensure_ingestion_operation(
            pool,
            operation_id=item_id,
            source_kind="batch-upload",
            requesting_actor_id=str(item["created_by"]),
        )
        source_revision = int(authority["source_revision"])
        lease_generation = int(authority["lease_generation"])
        media_operation_id = _batch_media_operation_id(item_id, source_revision, lease_generation)
        expected_revision = int(conflict["catalog_revision"]) if overwrite_allowed and conflict else 0
        overwrite_chapter_id = str(conflict["id"]) if overwrite_allowed and conflict else None

        media_operation = await media_job_status(
            client,
            requesting_actor_id=str(item["created_by"]),
            job_id=media_operation_id,
        )
        if media_operation.get("status") == "missing":
            sources = sorted(list(item["source_files"]), key=lambda value: value["order"])
            if not sources:
                raise RuntimeError("Batch item has no staged source files.")

            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as archive_file:
                with zipfile.ZipFile(archive_file, mode="w", compression=zipfile.ZIP_STORED) as archive:
                    last_heartbeat_at = 0.0
                    for source in sources:
                        raw = await _get_filer(client, source["staging_path"])
                        append_staged_chapter_page(
                            archive,
                            int(source["order"]),
                            raw,
                            str(source.get("content_type") or "application/octet-stream"),
                        )
                        now = time.monotonic()
                        if (now - last_heartbeat_at) >= max(
                            15.0,
                            float(settings.scraper_progress_min_interval_seconds),
                        ):
                            async with pool.acquire() as heartbeat_conn:
                                await heartbeat_conn.execute(
                                    "UPDATE scraper_batch_items SET processing_heartbeat_at=NOW(), updated_at=NOW() WHERE id=$1::uuid AND status='processing'",
                                    item_id,
                                )
                            last_heartbeat_at = now
                archive_file.seek(0)
                await submit_to_media(
                    None,
                    MediaSubmission(
                        series_slug=item["series_slug"],
                        chapter_slug=item["chapter_slug"],
                        chapter_number=str(item["chapter_number"]),
                        title=None,
                        archive=archive_file,
                        source_kind="batch-upload",
                        ingestion_operation_id=item_id,
                        media_operation_id=media_operation_id,
                        source_revision=source_revision,
                        ingestion_generation=lease_generation,
                        chapter_id=overwrite_chapter_id,
                        expected_revision=expected_revision,
                    ),
                    client=client,
                    requesting_actor_id=str(item["created_by"]),
                )

        media_operation = await wait_for_media_publication(
            client,
            requesting_actor_id=str(item["created_by"]),
            job_id=media_operation_id,
        )
        result = dict(media_operation.get("result") or {})
        receipt = result.get("catalog_receipt")
        if media_operation.get("status") != "completed" or not isinstance(receipt, dict):
            # Accepted durable work is not a new attempt. Preserve the same Media
            # operation/fence and let the at-least-once worker resume it.
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE scraper_batch_items
                        SET status='queued',queue_dispatched_at=NULL,
                            processing_heartbeat_at=NULL,error_message=NULL,updated_at=NOW()
                        WHERE id=$1::uuid AND status='processing'
                        """,
                        item_id,
                    )
                    await _refresh_batch_status(conn, item["batch_id"])
            return

        publication_receipt = dict(receipt)
        chapter_id = str(publication_receipt["chapter_id"])
        async with pool.acquire() as conn:
            async with conn.transaction():
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=item_id,
                    local_prefix=f"_scraper/batches/{item['batch_id']}/{item['chapter_slug']}",
                    reason="batch_item_published",
                )
                await conn.execute(
                    """
                    UPDATE scraper_batch_items
                    SET status='completed',processing_heartbeat_at=NULL,
                        published_chapter_id=$2::uuid,existing_chapter_id=NULL,
                        overwrite_requested_at=NULL,error_message=NULL,
                        source_files='[]'::jsonb,updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    item_id,
                    chapter_id,
                )
                await _set_batch_ingestion_terminal(
                    conn,
                    item_id,
                    status="completed",
                    phase="completed",
                )
                await _refresh_batch_status(conn, item["batch_id"])

    except HTTPException as exc:
        # Once Catalog produced a receipt, Scraper finalization is the only
        # remaining work. Requeue against the same fence instead of republishing.
        if publication_receipt is not None:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE scraper_batch_items
                        SET status='queued',queue_dispatched_at=NULL,
                            processing_heartbeat_at=NULL,error_message=$2,updated_at=NOW()
                        WHERE id=$1::uuid AND status='processing'
                        """,
                        item_id,
                        f"Scraper finalization pending after Catalog receipt: {exc}"[:2000],
                    )
                    await _refresh_batch_status(conn, item["batch_id"])
            return

        status_value = "failed_conflict" if exc.status_code == 409 else "failed_error"
        existing_id = item.get("existing_chapter_id")
        if status_value == "failed_conflict":
            async with pool.acquire() as lookup_conn:
                conflict = await _current_conflicting_chapter(
                    lookup_conn,
                    series_id=item["target_series_id"],
                    chapter_slug=item["chapter_slug"],
                    chapter_number=item["chapter_number"],
                )
                if conflict:
                    existing_id = conflict["id"]
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE scraper_batch_items
                    SET status=$2::varchar(32),processing_heartbeat_at=NULL,
                        existing_chapter_id=$3::uuid,error_message=$4,updated_at=NOW()
                    WHERE id=$1::uuid AND status='processing'
                    """,
                    item_id,
                    status_value,
                    existing_id,
                    str(exc.detail)[:2000],
                )
                await _set_batch_ingestion_terminal(
                    conn,
                    item_id,
                    status="needs_review" if status_value == "failed_conflict" else "failed",
                    phase="needs_review" if status_value == "failed_conflict" else "failed",
                    error_code="catalog_publication_conflict" if status_value == "failed_conflict" else "media_submission_failed",
                )
                await _refresh_batch_status(conn, item["batch_id"])
    except Exception as exc:
        if publication_receipt is not None:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        UPDATE scraper_batch_items
                        SET status='queued',queue_dispatched_at=NULL,
                            processing_heartbeat_at=NULL,error_message=$2,updated_at=NOW()
                        WHERE id=$1::uuid AND status='processing'
                        """,
                        item_id,
                        f"Scraper finalization pending after Catalog receipt: {type(exc).__name__}: {exc}"[:2000],
                    )
                    await _refresh_batch_status(conn, item["batch_id"])
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE scraper_batch_items
                    SET status='failed_error',processing_heartbeat_at=NULL,
                        error_message=$2,updated_at=NOW()
                    WHERE id=$1::uuid AND status='processing'
                    """,
                    item_id,
                    f"{type(exc).__name__}: {exc}"[:2000],
                )
                await _set_batch_ingestion_terminal(
                    conn,
                    item_id,
                    status="failed",
                    phase="failed",
                    error_code="media_submission_failed",
                )
                await _refresh_batch_status(conn, item["batch_id"])

