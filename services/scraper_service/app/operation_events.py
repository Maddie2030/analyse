from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger("scraper.operation-events")


async def record_operation_event(
    pool: asyncpg.Pool,
    *,
    operation_id: str,
    service: str,
    event_type: str,
    message: str,
    phase: str | None = None,
    status: str | None = None,
    chapter_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort append-only operation event.

    Operation execution must never fail only because observability storage is
    temporarily unavailable. The admin timeline endpoint itself is strict and
    will explain when migration 031 is missing.
    """
    try:
        async with pool.acquire() as conn:
            resolved_request_id = request_id or ""
            if not resolved_request_id:
                if chapter_id:
                    resolved_request_id = await conn.fetchval(
                        """
                        SELECT COALESCE(
                            NULLIF(c.publish_progress->>'request_id',''),
                            NULLIF(c.stage_progress->>'request_id',''),
                            NULLIF(d.publish_progress->>'request_id',''),
                            NULLIF(d.discovery_progress->>'request_id',''),
                            ''
                        )
                        FROM scraper_series_draft_chapters c
                        JOIN scraper_series_drafts d ON d.id=c.draft_id
                        WHERE c.id=$1::uuid AND d.id=$2::uuid
                        """,
                        chapter_id,
                        operation_id,
                    ) or ""
                else:
                    resolved_request_id = await conn.fetchval(
                        """
                        SELECT COALESCE(
                            NULLIF(publish_progress->>'request_id',''),
                            NULLIF(discovery_progress->>'request_id',''),
                            ''
                        )
                        FROM scraper_series_drafts
                        WHERE id=$1::uuid
                        """,
                        operation_id,
                    ) or ""
            await conn.execute(
                """
                INSERT INTO scraper_operation_events (
                    operation_id,
                    chapter_id,
                    request_id,
                    service,
                    event_type,
                    phase,
                    status,
                    message,
                    metadata
                )
                VALUES (
                    $1::uuid,
                    NULLIF($2, '')::uuid,
                    NULLIF($3, ''),
                    $4,
                    $5,
                    NULLIF($6, ''),
                    NULLIF($7, ''),
                    $8,
                    $9::jsonb
                )
                """,
                operation_id,
                chapter_id or "",
                resolved_request_id,
                service[:64],
                event_type[:64],
                phase or "",
                status or "",
                message[:4000],
                json.dumps(metadata or {}),
            )
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        log.warning(
            "operation event migration missing operation_id=%s service=%s event_type=%s",
            operation_id,
            service,
            event_type,
        )
    except Exception:
        log.exception(
            "operation event write failed operation_id=%s service=%s event_type=%s",
            operation_id,
            service,
            event_type,
        )


async def list_operation_events(
    pool: asyncpg.Pool,
    *,
    operation_id: str,
    limit: int = 250,
    before_id: str | None = None,
) -> dict[str, Any]:
    """Return one stable newest-first page plus the exact operation event count.

    Cursoring by the last event id avoids offset drift while the workflow is still
    appending newer events. The UI can therefore poll the newest page and load
    older history without skipping/duplicating records.
    """
    limit = max(1, min(500, int(limit)))
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM scraper_series_drafts WHERE id=$1::uuid",
                operation_id,
            )
            if exists is None:
                return {"items": [], "total": 0, "next_before_id": None}

            total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM scraper_operation_events WHERE operation_id=$1::uuid",
                operation_id,
            ) or 0)

            cursor_created_at = None
            cursor_uuid = None
            if before_id:
                cursor = await conn.fetchrow(
                    """
                    SELECT created_at, id
                    FROM scraper_operation_events
                    WHERE operation_id=$1::uuid AND id=$2::uuid
                    """,
                    operation_id,
                    before_id,
                )
                if cursor is not None:
                    cursor_created_at = cursor["created_at"]
                    cursor_uuid = cursor["id"]

            if before_id and cursor_created_at is None:
                rows = []
            elif cursor_created_at is None:
                rows = await conn.fetch(
                    """
                    SELECT
                        id, operation_id::text, chapter_id::text, request_id,
                        service, event_type, phase, status, message, metadata, created_at
                    FROM scraper_operation_events
                    WHERE operation_id = $1::uuid
                    ORDER BY created_at DESC, id DESC
                    LIMIT $2
                    """,
                    operation_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT
                        id, operation_id::text, chapter_id::text, request_id,
                        service, event_type, phase, status, message, metadata, created_at
                    FROM scraper_operation_events
                    WHERE operation_id = $1::uuid
                      AND (created_at, id) < ($2::timestamptz, $3::uuid)
                    ORDER BY created_at DESC, id DESC
                    LIMIT $4
                    """,
                    operation_id,
                    cursor_created_at,
                    cursor_uuid,
                    limit,
                )
    except asyncpg.UndefinedTableError as exc:
        raise RuntimeError(
            "Scraper operation timeline migration 031 has not been applied. Run ./scripts/migrate.sh."
        ) from exc

    items = [dict(row) for row in rows]
    next_before_id = str(items[-1]["id"]) if items and len(items) == limit else None
    for item in items:
        item["id"] = str(item["id"])
    return {"items": items, "total": total, "next_before_id": next_before_id}

