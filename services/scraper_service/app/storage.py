import hashlib
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx

from app.config import settings


async def save_history(
    pool: asyncpg.Pool,
    *,
    url: str,
    mode: str,
    adapter: str,
    title: str | None,
    summary: str | None,
    status: str,
    result: dict,
    snapshot_path: str | None,
    created_by: str,
) -> str:
    row = await pool.fetchrow(
        """
        INSERT INTO scraper_history (
            url,
            mode,
            adapter,
            title,
            summary,
            status,
            result,
            snapshot_path,
            created_by
        )
        VALUES (
            $1,
            $2,
            $3,
            $4,
            $5,
            $6,
            $7::jsonb,
            $8,
            $9::uuid
        )
        RETURNING id::text
        """,
        url,
        mode,
        adapter,
        title,
        summary,
        status,
        __import__("json").dumps(result),
        snapshot_path,
        created_by,
    )
    return row["id"]


async def list_history(
    pool: asyncpg.Pool,
    limit: int,
    offset: int,
) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT
            id::text,
            url,
            mode,
            adapter,
            title,
            summary,
            status,
            snapshot_path,
            created_by::text,
            created_at
        FROM scraper_history
        ORDER BY created_at DESC
        OFFSET $1
        LIMIT $2
        """,
        offset,
        limit,
    )

    return [dict(row) for row in rows]


async def get_history(
    pool: asyncpg.Pool,
    history_id: str,
) -> dict | None:
    row = await pool.fetchrow(
        """
        SELECT
            id::text,
            url,
            mode,
            adapter,
            title,
            summary,
            status,
            result,
            snapshot_path,
            created_by::text,
            created_at
        FROM scraper_history
        WHERE id = $1::uuid
        """,
        history_id,
    )

    return dict(row) if row else None


async def store_raw_snapshot(
    http: httpx.AsyncClient,
    *,
    url: str,
    html: bytes,
) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc)
    path = (
        f"_scraper/raw/{now:%Y/%m/%d}/"
        f"{digest}-{uuid.uuid4().hex}.html"
    )

    response = await http.put(
        f"{settings.seaweedfs_filer_url.rstrip('/')}/{path}",
        content=html,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    response.raise_for_status()

    return path
