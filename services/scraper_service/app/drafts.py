import asyncio
import json
import mimetypes
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import httpx
from fastapi import HTTPException, UploadFile

from app.config import settings
from app.chapter_identity import chapter_slug_from_number, normalize_chapter_number
from app.staging_store import (
    get_object,
    put_object,
    put_upload_object,
    StagedObjectMissing,
    staging_root,
    staging_exists,
)
from app.ingestion import (
    MediaSubmission,
    discover_chapter,
    media_job_status,
    submit_to_media,
    wait_for_media_publication,
)
from app.fetcher import fetch_image
from app.publication_bridge import (
    build_staged_chapter_archive,
    ensure_ingestion_operation,
)
from app.storage_attempts import (
    begin_storage_attempt,
    enqueue_local_staging_cleanup,
    mark_storage_attempt_committed,
    resolve_storage_attempt,
    storage_attempt_heartbeat_loop,
)


MAX_DRAFT_PAGES = 1000
MAX_SOURCE_PAGE_BYTES = 50 * 1024 * 1024
DOWNLOAD_CONCURRENCY = max(1, settings.scraper_image_download_concurrency)


async def _series_detail(
    pool: asyncpg.Pool,
    series_id: str,
) -> dict | None:
    async with pool.acquire() as conn:
        series = await conn.fetchrow(
            """
            SELECT
                id::text,
                title,
                slug,
                description,
                cover_image_path,
                status,
                created_at,
                updated_at
            FROM series
            WHERE id = $1::uuid
            """,
            series_id,
        )

        if series is None:
            return None

        chapters = await conn.fetch(
            """
            SELECT
                id::text,
                chapter_number,
                title,
                slug,
                status,
                page_count,
                created_at,
                updated_at
            FROM chapters
            WHERE series_id = $1::uuid
            ORDER BY chapter_number DESC
            """,
            series_id,
        )

        genres = await conn.fetch(
            """
            SELECT g.id, g.name
            FROM genres g
            JOIN series_genres sg ON sg.genre_id = g.id
            WHERE sg.series_id = $1::uuid
            ORDER BY g.name
            """,
            series_id,
        )

        tags = await conn.fetch(
            """
            SELECT t.id, t.name
            FROM tags t
            JOIN series_tags st ON st.tag_id = t.id
            WHERE st.series_id = $1::uuid
            ORDER BY t.name
            """,
            series_id,
        )

    value = dict(series)
    value["chapters"] = [dict(row) for row in chapters]
    value["genres"] = [dict(row) for row in genres]
    value["tags"] = [dict(row) for row in tags]
    return value


async def search_series(
    pool: asyncpg.Pool,
    *,
    search: str,
    limit: int,
) -> list[dict]:
    pattern = f"%{search.strip()}%"

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.id::text,
                s.title,
                s.slug,
                s.status,
                s.cover_image_path,
                COUNT(c.id)::int AS chapter_count
            FROM series s
            LEFT JOIN chapters c ON c.series_id = s.id
            WHERE (
                $1 = ''
                OR s.title ILIKE $2
                OR s.slug ILIKE $2
            )
            GROUP BY
                s.id,
                s.title,
                s.slug,
                s.status,
                s.cover_image_path
            ORDER BY s.updated_at DESC, s.title ASC
            LIMIT $3
            """,
            search.strip(),
            pattern,
            limit,
        )

    return [dict(row) for row in rows]


async def get_series_detail(
    pool: asyncpg.Pool,
    series_id: str,
) -> dict:
    value = await _series_detail(pool, series_id)

    if value is None:
        raise HTTPException(404, "Series not found.")

    return value


def _staging_path(
    draft_id: str,
    page_id: str,
    extension: str,
) -> str:
    extension = extension.lower().lstrip(".") or "bin"
    return (
        f"_scraper/staging/{draft_id}/"
        f"pages/{page_id}.{extension}"
    )


async def _put_filer(
    client: httpx.AsyncClient,
    path: str,
    data: bytes,
    content_type: str,
) -> None:
    await put_object(client, path, data, content_type)


async def _get_filer(
    client: httpx.AsyncClient,
    path: str,
) -> tuple[bytes, str]:
    try:
        return await get_object(client, path)
    except StagedObjectMissing as exc:
        raise HTTPException(404, "Staged image not found.") from exc


async def _get_staged_draft_page(
    client: httpx.AsyncClient,
    *,
    staging_path: str,
    label: str,
) -> tuple[bytes, str]:
    try:
        return await get_object(client, staging_path)
    except StagedObjectMissing as exc:
        raise RuntimeError(
            f"{label} is missing from the canonical scraper staging PVC. "
            f"logical_path={staging_path}; container_root={staging_root()}. Re-stage or re-upload this page."
        ) from exc


async def _download_source_page(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    url: str,
    chapter_url: str,
) -> tuple[bytes, str]:
    async with semaphore:
        fetched = await fetch_image(
            client,
            url=url,
            referer=chapter_url,
            max_bytes=MAX_SOURCE_PAGE_BYTES,
        )

    return fetched.content, fetched.content_type


def _extension(content_type: str, source_url: str) -> str:
    guessed = mimetypes.guess_extension(
        content_type.split(";")[0].strip()
    )

    if guessed == ".jpe":
        guessed = ".jpg"

    if guessed:
        return guessed.lstrip(".")

    suffix = Path(
        source_url.split("?", 1)[0]
    ).suffix.lower()

    if suffix in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".avif",
    }:
        return suffix.lstrip(".")

    return "img"


def _download_failure(
    *,
    order: int,
    source_url: str,
    exc: BaseException,
) -> dict:
    detail = getattr(exc, "detail", None)
    status_code = getattr(exc, "status_code", None)

    if detail is None:
        detail = str(exc) or type(exc).__name__

    return {
        "order": order,
        "source_url": source_url,
        "status_code": status_code,
        "error": str(detail)[:1000],
    }


async def create_existing_series_draft(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    series_id: str,
    chapter_url: str,
    created_by: str,
) -> dict:
    series = await get_series_detail(
        pool,
        series_id,
    )

    adapter, discovered = await discover_chapter(
        client,
        chapter_url,
    )

    if len(discovered.page_urls) == 0:
        raise HTTPException(
            422,
            "No chapter page images were discovered.",
        )

    if len(discovered.page_urls) > MAX_DRAFT_PAGES:
        raise HTTPException(
            413,
            "Chapter contains too many pages.",
        )

    draft_id = str(uuid.uuid4())
    staging_prefix = f"_scraper/staging/{draft_id}"
    attempt_id = await begin_storage_attempt(
        pool,
        operation_type="existing_draft_stage_create",
        local_staging_prefix=staging_prefix,
        recovery_entity_id=draft_id,
    )
    attempt_stop = asyncio.Event()
    attempt_heartbeat = asyncio.create_task(
        storage_attempt_heartbeat_loop(pool, attempt_id, attempt_stop),
        name=f"existing-draft-stage-attempt-{attempt_id}",
    )
    semaphore = asyncio.Semaphore(
        DOWNLOAD_CONCURRENCY
    )

    async def stage(
        index: int,
        source_url: str,
    ) -> dict:
        data, content_type = await _download_source_page(
            client,
            semaphore,
            url=source_url,
            chapter_url=chapter_url,
        )

        page_id = str(uuid.uuid4())
        extension = _extension(
            content_type,
            source_url,
        )
        path = _staging_path(
            draft_id,
            page_id,
            extension,
        )

        await _put_filer(
            client,
            path,
            data,
            content_type,
        )

        return {
            "id": page_id,
            "order": index,
            "source_order": index,
            "source_url": source_url,
            "staging_path": path,
            "content_type": content_type,
            "enabled": True,
        }

    # Important: one bad CDN image must not destroy the entire editable draft.
    results = await asyncio.gather(
        *[
            stage(index, source_url)
            for index, source_url in enumerate(
                discovered.page_urls,
                start=1,
            )
        ],
        return_exceptions=True,
    )

    pages: list[dict] = []
    failures: list[dict] = []

    for index, (source_url, result) in enumerate(
        zip(discovered.page_urls, results),
        start=1,
    ):
        if isinstance(result, BaseException):
            failures.append(
                _download_failure(
                    order=index,
                    source_url=source_url,
                    exc=result,
                )
            )
        else:
            pages.append(result)

    pages.sort(
        key=lambda page: page.get(
            "source_order",
            page["order"],
        )
    )

    # Re-number visible order after skipped failures.
    for visible_order, page in enumerate(
        pages,
        start=1,
    ):
        page["order"] = visible_order

    discovered_number = discovered.chapter.chapter_number or "1"
    try:
        _number, discovered_number_text = normalize_chapter_number(discovered_number)
    except ValueError:
        discovered_number_text = "1"

    chapter_data = {
        "chapter_number": discovered_number_text,
        "chapter_slug": chapter_slug_from_number(discovered_number_text),
        "chapter_title": (
            discovered.chapter.title
        ),
        "chapter_url": chapter_url,
        "adapter": adapter,
        "scrape_summary": {
            "discovered_count": len(
                discovered.page_urls
            ),
            "staged_count": len(pages),
            "failed_count": len(failures),
            "failures": failures,
        },
    }

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO scraper_drafts (
                        id,
                        draft_type,
                        source_url,
                        target_series_id,
                        series_data,
                        chapter_data,
                        pages,
                        status,
                        created_by
                    )
                    VALUES (
                        $1::uuid,
                        'existing-series-chapter',
                        $2,
                        $3::uuid,
                        $4::jsonb,
                        $5::jsonb,
                        $6::jsonb,
                        'draft',
                        $7::uuid
                    )
                    """,
                    draft_id,
                    chapter_url,
                    series_id,
                    json.dumps({
                        "id": series["id"],
                        "title": series["title"],
                        "slug": series["slug"],
                        "status": series["status"],
                    }),
                    json.dumps(chapter_data),
                    json.dumps(pages),
                    created_by,
                )
                await mark_storage_attempt_committed(conn, attempt_id, draft_id)
    except Exception as exc:
        try:
            outcome = await resolve_storage_attempt(
                pool, attempt_id, error=f"{type(exc).__name__}: {exc}"[:2000]
            )
        except Exception:
            # If remote PostgreSQL cannot tell us whether the INSERT committed,
            # preserve every local page. Durable recovery will decide later.
            raise
        if outcome == "committed":
            return await get_draft(pool, draft_id)
        raise
    finally:
        attempt_stop.set()
        attempt_heartbeat.cancel()
        await asyncio.gather(attempt_heartbeat, return_exceptions=True)

    return await get_draft(
        pool,
        draft_id,
    )


async def _classify_existing_draft_retry(
    draft: dict,
) -> tuple[list[dict], list[dict]]:
    """Return missing URL-backed pages and missing manual pages."""
    url_backed: list[dict] = []
    manual: list[dict] = []
    for page in list(draft.get("pages") or []):
        path = str(page.get("staging_path") or "")
        if path and await staging_exists(path):
            continue
        (url_backed if page.get("source_url") else manual).append(page)
    return url_backed, manual


async def _claim_existing_draft_retry(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    revision: int,
    stage_generation: int,
) -> tuple[int, int]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            changed = await conn.execute(
                """
                UPDATE scraper_drafts
                SET stage_generation=stage_generation+1, updated_at=NOW()
                WHERE id=$1::uuid AND status='draft'
                  AND revision=$2::bigint AND stage_generation=$3::bigint
                """,
                draft_id,
                revision,
                stage_generation,
            )
            if changed != "UPDATE 1":
                raise HTTPException(
                    409, "Draft retry fence changed; reload the draft before retrying."
                )
            claimed_generation = await conn.fetchval(
                "SELECT stage_generation FROM scraper_drafts WHERE id=$1::uuid",
                draft_id,
            )
    return revision, int(claimed_generation)


async def _commit_retry_fence_loss_cleanup(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    paths: list[str],
) -> None:
    """Durably enqueue exact repair paths before the caller reports 409."""
    if not paths:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            for path in dict.fromkeys(paths):
                if path:
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=path,
                        reason="existing_draft_retry_fence_lost",
                    )


def _existing_draft_retry_targets(
    failures: list[dict],
    repair_pages: list[dict],
    existing_pages: list[dict],
) -> list[dict]:
    existing_by_url = {
        str(page.get("source_url")): page
        for page in existing_pages
        if page.get("source_url")
    }
    repair_by_url = {str(page["source_url"]): page for page in repair_pages}
    targets: list[dict] = []
    target_urls: set[str] = set()
    for failure in failures:
        source_url = str(failure["source_url"])
        repair_page = repair_by_url.get(source_url)
        if source_url in existing_by_url and repair_page is None:
            continue
        targets.append({
            "order": int(failure.get("order", 0)),
            "source_url": source_url,
            "existing": repair_page,
        })
        target_urls.add(source_url)
    for page in repair_pages:
        source_url = str(page["source_url"])
        if source_url in target_urls:
            continue
        targets.append({
            "order": int(page.get("source_order", page.get("order", 0))),
            "source_url": source_url,
            "existing": page,
        })
    return targets


async def _retry_existing_draft_target(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    context: dict,
    target: dict,
) -> dict:
    source_url = str(target["source_url"])
    data, content_type = await _download_source_page(
        client,
        semaphore,
        url=source_url,
        chapter_url=str(context["chapter_url"]),
    )
    old = target.get("existing")
    page_id = str(old.get("id")) if old else str(uuid.uuid4())
    path = _staging_path(
        str(context["draft_id"]),
        f"{page_id}-g{int(context['stage_generation'])}",
        _extension(content_type, source_url),
    )
    await _put_filer(client, path, data, content_type)
    return {
        **(dict(old) if old else {}),
        "id": page_id,
        "order": int(target["order"]),
        "source_order": int(target["order"]),
        "source_url": source_url,
        "staging_path": path,
        "content_type": content_type,
        "enabled": True,
    }


def _merge_existing_draft_retry_results(
    existing_pages: list[dict],
    targets: list[dict],
    results: list,
) -> tuple[list[dict], list[dict], list[str]]:
    remaining_failures: list[dict] = []
    successful: list[dict] = []
    for target, result in zip(targets, results):
        if isinstance(result, BaseException):
            remaining_failures.append(
                _download_failure(
                    order=int(target["order"]),
                    source_url=str(target["source_url"]),
                    exc=result,
                )
            )
        else:
            successful.append(result)

    by_id = {str(page.get("id")): dict(page) for page in existing_pages}
    by_id.update({str(page["id"]): dict(page) for page in successful})
    merged_pages = list(by_id.values())
    merged_pages.sort(key=lambda page: int(page.get("source_order", page.get("order", 0))))
    for visible_order, page in enumerate(merged_pages, start=1):
        page["order"] = visible_order
    staged_paths = [str(page.get("staging_path") or "") for page in successful]
    return merged_pages, remaining_failures, staged_paths


async def _commit_existing_draft_retry(
    pool: asyncpg.Pool,
    state: dict,
) -> None:
    draft_id = str(state["draft_id"])
    staged_paths = list(state["staged_paths"])
    try:
        async with pool.acquire() as conn:
            committed = await conn.fetchval(
                """
                UPDATE scraper_drafts
                SET chapter_data=$2::jsonb, pages=$3::jsonb, updated_at=NOW()
                WHERE id=$1::uuid AND status='draft'
                  AND revision=$4::bigint AND stage_generation=$5::bigint
                RETURNING id::text
                """,
                draft_id,
                json.dumps(state["chapter_data"]),
                json.dumps(state["pages"]),
                int(state["revision"]),
                int(state["stage_generation"]),
            )
        if committed is None:
            await _commit_retry_fence_loss_cleanup(
                pool, draft_id=draft_id, paths=staged_paths
            )
            raise HTTPException(
                409,
                "Draft retry fence changed; staged repair bytes were discarded. Reload and retry.",
            )
    except HTTPException:
        raise
    except Exception:
        async with pool.acquire() as conn:
            canonical = await conn.fetchval(
                "SELECT pages FROM scraper_drafts WHERE id=$1::uuid", draft_id
            )
            referenced = {str(page.get("staging_path") or "") for page in (canonical or [])}
            async with conn.transaction():
                for path in staged_paths:
                    if path and path not in referenced:
                        await enqueue_local_staging_cleanup(
                            conn,
                            entity_id=draft_id,
                            local_prefix=path,
                            reason="existing_draft_retry_page_not_committed",
                        )
        if any(path in referenced for path in staged_paths):
            return
        raise


async def retry_failed_draft_pages(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
) -> dict:
    draft = await get_draft(pool, draft_id)
    if draft["status"] != "draft":
        raise HTTPException(409, "Published drafts cannot retry staged images.")

    chapter_data = dict(draft["chapter_data"])
    summary = dict(chapter_data.get("scrape_summary", {}))
    failures = list(summary.get("failures", []))
    repair_pages, missing_manual = await _classify_existing_draft_retry(draft)
    if missing_manual:
        raise HTTPException(
            409,
            "One or more manually uploaded staged pages are missing; re-upload the missing page before retrying.",
        )
    if not failures and not repair_pages:
        return draft

    revision, generation = await _claim_existing_draft_retry(
        pool,
        draft_id=draft_id,
        revision=int(draft["revision"]),
        stage_generation=int(draft["stage_generation"]),
    )
    existing_pages = list(draft["pages"])
    targets = _existing_draft_retry_targets(failures, repair_pages, existing_pages)
    context = {
        "draft_id": draft_id,
        "chapter_url": str(chapter_data["chapter_url"]),
        "stage_generation": generation,
    }
    semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    results = await asyncio.gather(
        *(_retry_existing_draft_target(client, semaphore, context, target) for target in targets),
        return_exceptions=True,
    )
    pages, remaining_failures, staged_paths = _merge_existing_draft_retry_results(
        existing_pages, targets, results
    )
    summary.update({
        "staged_count": len(pages),
        "failed_count": len(remaining_failures),
        "failures": remaining_failures,
    })
    chapter_data["scrape_summary"] = summary
    await _commit_existing_draft_retry(
        pool,
        {
            "draft_id": draft_id,
            "chapter_data": chapter_data,
            "pages": pages,
            "revision": revision,
            "stage_generation": generation,
            "staged_paths": staged_paths,
        },
    )
    return await get_draft(pool, draft_id)


def _decode_json_value(
    value,
    *,
    field: str,
    expected_type,
):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                500,
                f"Stored scraper draft field '{field}' is invalid JSON.",
            ) from exc

    if not isinstance(value, expected_type):
        raise HTTPException(
            500,
            (
                f"Stored scraper draft field '{field}' has invalid type "
                f"{type(value).__name__}."
            ),
        )

    return value


async def get_draft(
    pool: asyncpg.Pool,
    draft_id: str,
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id::text,
                draft_type,
                source_url,
                target_series_id::text,
                series_data,
                chapter_data,
                pages,
                revision,
                stage_generation,
                status,
                published_chapter_id::text,
                created_by::text,
                created_at,
                updated_at
            FROM scraper_drafts
            WHERE id = $1::uuid
            """,
            draft_id,
        )

    if row is None:
        raise HTTPException(
            404,
            "Scraper draft not found.",
        )

    value = dict(row)
    value["series_data"] = _decode_json_value(
        value["series_data"],
        field="series_data",
        expected_type=dict,
    )
    value["chapter_data"] = _decode_json_value(
        value["chapter_data"],
        field="chapter_data",
        expected_type=dict,
    )
    value["pages"] = _decode_json_value(
        value["pages"],
        field="pages",
        expected_type=list,
    )

    return value


async def update_draft_chapter(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    chapter_number: str,
    chapter_slug: str,
    chapter_title: str | None,
) -> dict:
    try:
        _number, canonical_number = normalize_chapter_number(chapter_number)
        canonical_slug = chapter_slug_from_number(canonical_number)
    except ValueError:
        raise HTTPException(
            400,
            "Invalid chapter number.",
        )

    # Kept in the request contract for backwards compatibility; ignored by
    # design so title/manual slug edits cannot diverge from chapter_number.
    _ = chapter_slug

    draft = await get_draft(
        pool,
        draft_id,
    )

    if draft["status"] != "draft":
        raise HTTPException(
            409,
            "Only draft records can be edited.",
        )

    chapter_data = dict(
        draft["chapter_data"]
    )
    chapter_data["chapter_number"] = canonical_number
    chapter_data["chapter_slug"] = canonical_slug
    chapter_data["chapter_title"] = chapter_title

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE scraper_drafts
            SET
                chapter_data = $2::jsonb,
                revision = revision + 1,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            json.dumps(chapter_data),
        )

    return await get_draft(
        pool,
        draft_id,
    )


async def _save_pages(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    pages: list[dict],
) -> dict:
    for index, page in enumerate(
        pages,
        start=1,
    ):
        page["order"] = index

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE scraper_drafts
            SET
                pages = $2::jsonb,
                revision = revision + 1,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            draft_id,
            json.dumps(pages),
        )

    return await get_draft(
        pool,
        draft_id,
    )


async def _save_pages_after_new_staging(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    pages: list[dict],
    new_path: str,
    rollback_reason: str,
) -> dict:
    try:
        return await _save_pages(pool, draft_id=draft_id, pages=pages)
    except Exception:
        # If COMMIT succeeded but its acknowledgement was lost, PostgreSQL is
        # canonical. Never delete a path that the committed page list now uses.
        async with pool.acquire() as conn:
            canonical = await conn.fetchval(
                "SELECT pages FROM scraper_drafts WHERE id=$1::uuid", draft_id
            )
            referenced = any(
                str(page.get("staging_path") or "") == new_path
                for page in (canonical or [])
            )
            if not referenced:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=new_path,
                        reason=rollback_reason,
                    )
        if referenced:
            return await get_draft(pool, draft_id)
        raise


async def remove_draft_page(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    page_id: str,
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT status, pages
                FROM scraper_drafts
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                draft_id,
            )
            if row is None:
                raise HTTPException(404, "Scraper draft not found.")
            if row["status"] != "draft":
                raise HTTPException(409, "Published drafts cannot be edited.")
            pages = list(row["pages"] or [])
            target = next((page for page in pages if page.get("id") == page_id), None)
            if target is None:
                raise HTTPException(404, "Draft page not found.")
            pages = [page for page in pages if page.get("id") != page_id]
            for index, page in enumerate(pages, start=1):
                page["order"] = index
            await conn.execute(
                "UPDATE scraper_drafts SET pages=$2::jsonb, revision=revision+1, updated_at=NOW() WHERE id=$1::uuid",
                draft_id,
                json.dumps(pages),
            )
            staging_path = str(target.get("staging_path") or "")
            if staging_path:
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=draft_id,
                    local_prefix=staging_path,
                    reason="existing_draft_page_removed",
                )
    return await get_draft(pool, draft_id)


async def reorder_draft_pages(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    page_ids: list[str],
) -> dict:
    draft = await get_draft(
        pool,
        draft_id,
    )

    if draft["status"] != "draft":
        raise HTTPException(
            409,
            "Published drafts cannot be edited.",
        )

    pages = list(draft["pages"])

    current = {
        page["id"]: page
        for page in pages
    }

    if set(page_ids) != set(current):
        raise HTTPException(
            400,
            "page_ids must contain every draft page exactly once.",
        )

    ordered = [
        current[page_id]
        for page_id in page_ids
    ]

    return await _save_pages(
        pool,
        draft_id=draft_id,
        pages=ordered,
    )


async def add_draft_page_from_url(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    url: str,
    position: int | None,
) -> dict:
    draft = await get_draft(
        pool,
        draft_id,
    )

    if draft["status"] != "draft":
        raise HTTPException(
            409,
            "Published drafts cannot be edited.",
        )

    chapter_url = str(
        draft["chapter_data"]["chapter_url"]
    )

    data, content_type = await _download_source_page(
        client,
        asyncio.Semaphore(1),
        url=url,
        chapter_url=chapter_url,
    )

    page_id = str(uuid.uuid4())
    path = _staging_path(
        draft_id,
        page_id,
        _extension(content_type, url),
    )

    await _put_filer(
        client,
        path,
        data,
        content_type,
    )

    page = {
        "id": page_id,
        "order": 0,
        "source_url": url,
        "staging_path": path,
        "content_type": content_type,
        "enabled": True,
    }

    pages = list(draft["pages"])

    if position is None or position > len(pages):
        pages.append(page)
    else:
        pages.insert(
            max(0, position - 1),
            page,
        )

    return await _save_pages_after_new_staging(
        pool,
        draft_id=draft_id,
        pages=pages,
        new_path=path,
        rollback_reason="existing_draft_page_add_not_committed",
    )


async def add_draft_page_upload(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    file: UploadFile,
    position: int | None,
) -> dict:
    draft = await get_draft(pool, draft_id)
    if draft["status"] != "draft":
        raise HTTPException(409, "Published drafts cannot be edited.")

    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Uploaded file must be an image.")

    page_id = str(uuid.uuid4())
    path = _staging_path(
        draft_id,
        page_id,
        _extension(content_type, file.filename or "upload"),
    )
    try:
        await put_upload_object(path, file.file, max_bytes=MAX_SOURCE_PAGE_BYTES)
    except ValueError as exc:
        if "empty" in str(exc).lower():
            raise HTTPException(400, "Uploaded image is empty.") from exc
        raise HTTPException(413, "Uploaded image exceeds 50 MiB.") from exc

    page = {
        "id": page_id,
        "order": 0,
        "source_url": None,
        "staging_path": path,
        "content_type": content_type,
        "enabled": True,
    }
    pages = list(draft["pages"])
    if position is None or position > len(pages):
        pages.append(page)
    else:
        pages.insert(max(0, position - 1), page)

    return await _save_pages_after_new_staging(
        pool,
        draft_id=draft_id,
        pages=pages,
        new_path=path,
        rollback_reason="existing_draft_page_upload_not_committed",
    )


async def replace_draft_page_from_url(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    page_id: str,
    url: str,
) -> dict:
    draft = await get_draft(pool, draft_id)
    if draft["status"] != "draft":
        raise HTTPException(409, "Published drafts cannot be edited.")
    pages = list(draft["pages"])
    index = next((i for i, page in enumerate(pages) if page["id"] == page_id), None)
    if index is None:
        raise HTTPException(404, "Draft page not found.")
    old = pages[index]

    data, content_type = await _download_source_page(
        client,
        asyncio.Semaphore(1),
        url=url,
        chapter_url=str(draft["chapter_data"]["chapter_url"]),
    )
    # Never overwrite the canonical staged object before the DB transaction.
    # A unique generation path lets rollback keep the old page intact.
    path = _staging_path(
        draft_id,
        f"{page_id}-{uuid.uuid4().hex}",
        _extension(content_type, url),
    )
    await _put_filer(client, path, data, content_type)
    pages[index] = {
        **old,
        "source_url": url,
        "staging_path": path,
        "content_type": content_type,
    }
    for order, page in enumerate(pages, start=1):
        page["order"] = order

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT status, pages FROM scraper_drafts WHERE id=$1::uuid FOR UPDATE",
                    draft_id,
                )
                if row is None:
                    raise HTTPException(404, "Scraper draft not found.")
                if row["status"] != "draft":
                    raise HTTPException(409, "Published drafts cannot be edited.")
                await conn.execute(
                    "UPDATE scraper_drafts SET pages=$2::jsonb, revision=revision+1, updated_at=NOW() WHERE id=$1::uuid",
                    draft_id,
                    json.dumps(pages),
                )
                old_path = str(old.get("staging_path") or "")
                if old_path and old_path != path:
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=old_path,
                        reason="existing_draft_page_replaced",
                    )
    except Exception:
        async with pool.acquire() as conn:
            canonical = await conn.fetchval(
                "SELECT pages FROM scraper_drafts WHERE id=$1::uuid", draft_id
            )
            referenced = any(
                str(page.get("staging_path") or "") == path
                for page in (canonical or [])
            )
            if not referenced:
                async with conn.transaction():
                    await enqueue_local_staging_cleanup(
                        conn,
                        entity_id=draft_id,
                        local_prefix=path,
                        reason="existing_draft_page_replace_not_committed",
                    )
        if referenced:
            return await get_draft(pool, draft_id)
        raise

    return await get_draft(pool, draft_id)


async def preview_draft_page(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    page_id: str,
) -> tuple[bytes, str]:
    draft = await get_draft(
        pool,
        draft_id,
    )

    page = next(
        (
            page
            for page in draft["pages"]
            if page["id"] == page_id
        ),
        None,
    )

    if page is None:
        raise HTTPException(
            404,
            "Draft page not found.",
        )

    return await _get_staged_draft_page(
        client,
        staging_path=page["staging_path"],
        label=f"Draft page {page_id}",
    )


@dataclass(frozen=True)
class ExistingSeriesPublishRequest:
    draft_id: str
    actor_id: str
    session_id: str


@dataclass(frozen=True)
class ExistingSeriesDraftInput:
    draft: dict
    series: dict
    chapter_data: dict
    chapter_number: Decimal
    chapter_slug: str
    pages: list[dict]


@dataclass(frozen=True)
class ExistingSeriesPublicationContext:
    draft_id: str
    operation_id: str
    series: dict


async def _existing_series_publish_input(
    pool: asyncpg.Pool,
    draft_id: str,
) -> ExistingSeriesDraftInput:
    draft = await get_draft(pool, draft_id)
    if draft["status"] != "draft":
        raise HTTPException(409, "Draft is not publishable.")
    series = await get_series_detail(pool, draft["target_series_id"])
    chapter_data = dict(draft["chapter_data"])
    try:
        chapter_number = Decimal(str(chapter_data["chapter_number"]))
    except InvalidOperation as exc:
        raise HTTPException(400, "Invalid chapter number.") from exc
    chapter_slug = str(chapter_data["chapter_slug"]).strip()
    if not chapter_slug:
        raise HTTPException(400, "Chapter slug is required.")
    pages = sorted(list(draft["pages"]), key=lambda value: value["order"])
    if not pages:
        raise HTTPException(400, "Draft has no pages.")
    async with pool.acquire() as conn:
        conflict = await conn.fetchrow(
            """
            SELECT id FROM chapters
            WHERE series_id=$1::uuid AND (chapter_number=$2 OR slug=$3)
            """,
            series["id"],
            chapter_number,
            chapter_slug,
        )
    if conflict is not None:
        raise HTTPException(409, "A chapter with this number or slug already exists.")
    return ExistingSeriesDraftInput(
        draft=draft,
        series=series,
        chapter_data=chapter_data,
        chapter_number=chapter_number,
        chapter_slug=chapter_slug,
        pages=pages,
    )


async def _freeze_existing_series_publication(
    pool: asyncpg.Pool,
    publication: ExistingSeriesDraftInput,
    request: ExistingSeriesPublishRequest,
) -> tuple[str, dict]:
    operation_id = str(uuid.uuid4())
    chapter_data = dict(publication.chapter_data)
    chapter_data.update(
        {
            "publication_operation_id": operation_id,
            "publication_media_job_id": operation_id,
            "publication_actor_id": request.actor_id,
        }
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchrow(
                "SELECT status FROM scraper_drafts WHERE id=$1::uuid FOR UPDATE",
                request.draft_id,
            )
            if locked is None:
                raise HTTPException(404, "Scraper draft not found.")
            if locked["status"] != "draft":
                raise HTTPException(409, "Draft publication already started.")
            await conn.execute(
                "UPDATE scraper_drafts SET status='publishing',chapter_data=$2::jsonb,updated_at=NOW() WHERE id=$1::uuid",
                request.draft_id,
                json.dumps(chapter_data),
            )
    return operation_id, chapter_data


async def _raw_staged_archive(client: httpx.AsyncClient, pages: list[dict]) -> bytes:
    staged_pages: list[tuple[int, bytes, str]] = []
    for draft_page in pages:
        raw, content_type = await _get_staged_draft_page(
            client,
            staging_path=draft_page["staging_path"],
            label=f"Draft page {draft_page.get('order')}",
        )
        staged_pages.append((int(draft_page["order"]), raw, content_type))
    return build_staged_chapter_archive(staged_pages)


def _published_chapter(media_operation: dict) -> tuple[dict, dict]:
    result = dict(media_operation.get("result") or {})
    receipt = result.get("catalog_receipt")
    command = result.get("publication_command")
    if not result.get("published") or not isinstance(receipt, dict) or not isinstance(command, dict):
        raise HTTPException(503, "Media transformation completed but Catalog receipt is still reconciling.")
    manifest = dict(command.get("manifest") or {})
    chapter = {
        "id": str(receipt["chapter_id"]),
        "chapter_number": command.get("chapter_number"),
        "title": command.get("title"),
        "slug": manifest.get("chapter_slug"),
        "status": "published",
        "page_count": int(receipt.get("page_count") or result.get("page_count") or 0),
        "catalog_revision": int(receipt.get("chapter_revision") or 1),
    }
    return chapter, result


async def _finalize_existing_series_media_publication(
    pool: asyncpg.Pool,
    context: ExistingSeriesPublicationContext,
    media_operation: dict,
) -> dict:
    chapter, result = _published_chapter(media_operation)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT status FROM scraper_drafts WHERE id=$1::uuid FOR UPDATE",
                context.draft_id,
            )
            if row is None:
                raise HTTPException(404, "Scraper draft not found.")
            if row["status"] != "published":
                await conn.execute(
                    "UPDATE scraper_drafts SET status='published',published_chapter_id=$2::uuid,updated_at=NOW() WHERE id=$1::uuid",
                    context.draft_id,
                    chapter["id"],
                )
                await conn.execute(
                    """
                    UPDATE ingestion_operations
                    SET status='completed',phase='completed',published_count=1,
                        failed_count=0,error_code=NULL,updated_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    context.operation_id,
                )
                await enqueue_local_staging_cleanup(
                    conn,
                    entity_id=context.draft_id,
                    local_prefix=f"_scraper/staging/{context.draft_id}",
                    reason="existing_draft_published",
                )
    return {
        "status": "published",
        "series": {key: context.series[key] for key in ("id", "title", "slug")},
        "chapter": chapter,
        "pages": list(result.get("pages") or []),
        "media_job": media_operation,
    }


async def _reset_existing_series_publication(
    pool: asyncpg.Pool,
    *,
    draft_id: str,
    operation_id: str,
    chapter_data: dict,
    error: BaseException,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE ingestion_operations
            SET status='failed',phase='failed',failed_count=1,
                error_code='media_submission_failed',updated_at=NOW()
            WHERE id=$1::uuid AND status NOT IN ('completed','completed_with_errors')
            """,
            operation_id,
        )
    updated = dict(chapter_data)
    updated.pop("publication_operation_id", None)
    updated.pop("publication_media_job_id", None)
    updated["publication_last_error"] = f"{type(error).__name__}: {error}"[:500]
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE scraper_drafts SET status='draft',chapter_data=$2::jsonb,updated_at=NOW() WHERE id=$1::uuid",
            draft_id,
            json.dumps(updated),
        )


async def reconcile_existing_series_draft(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    *,
    draft_id: str,
    session_id: str | None,
) -> dict:
    draft = await get_draft(pool, draft_id)
    if draft["status"] != "publishing" or not session_id:
        return draft
    chapter_data = dict(draft["chapter_data"])
    operation_id = str(chapter_data.get("publication_operation_id") or "")
    media_job_id = str(chapter_data.get("publication_media_job_id") or "")
    if not operation_id or not media_job_id:
        return draft
    media_operation = await media_job_status(client, session_id=session_id, job_id=media_job_id)
    if media_operation.get("status") == "completed":
        result = dict(media_operation.get("result") or {})
        if result.get("published") and isinstance(result.get("catalog_receipt"), dict):
            series = await get_series_detail(pool, draft["target_series_id"])
            await _finalize_existing_series_media_publication(
                pool,
                ExistingSeriesPublicationContext(draft_id, operation_id, series),
                media_operation,
            )
            return await get_draft(pool, draft_id)
    if media_operation.get("status") == "failed":
        await _reset_existing_series_publication(
            pool,
            draft_id=draft_id,
            operation_id=operation_id,
            chapter_data=chapter_data,
            error=RuntimeError(str(media_operation.get("error") or "media_transform_failed")),
        )
        return await get_draft(pool, draft_id)
    return draft


async def _resume_existing_series_publication(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    request: ExistingSeriesPublishRequest,
    draft: dict,
) -> dict:
    chapter_data = dict(draft["chapter_data"])
    operation_id = str(chapter_data.get("publication_operation_id") or "")
    media_job_id = str(chapter_data.get("publication_media_job_id") or "")
    if not operation_id or not media_job_id:
        raise HTTPException(409, "Draft publication state is incomplete; retry after reconciliation.")
    series = await get_series_detail(pool, draft["target_series_id"])
    media_operation = await wait_for_media_publication(
        client,
        session_id=request.session_id,
        job_id=media_job_id,
    )
    if media_operation.get("status") != "completed":
        return {"status": "publishing", "media_job": media_operation}
    return await _finalize_existing_series_media_publication(
        pool,
        ExistingSeriesPublicationContext(request.draft_id, operation_id, series),
        media_operation,
    )


async def publish_existing_series_draft(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    request: ExistingSeriesPublishRequest,
) -> dict:
    if not request.session_id:
        raise HTTPException(401, "Not authenticated.")
    draft = await get_draft(pool, request.draft_id)
    if draft["status"] == "publishing":
        return await _resume_existing_series_publication(pool, client, request, draft)

    publication = await _existing_series_publish_input(pool, request.draft_id)
    operation_id, chapter_data = await _freeze_existing_series_publication(pool, publication, request)
    try:
        authority = await ensure_ingestion_operation(
            pool,
            operation_id=operation_id,
            source_kind="existing-series-scrape",
            requesting_actor_id=request.actor_id,
        )
        archive = await _raw_staged_archive(client, publication.pages)
        await submit_to_media(
            None,
            MediaSubmission(
                series_slug=publication.series["slug"],
                chapter_slug=publication.chapter_slug,
                chapter_number=str(publication.chapter_number),
                title=publication.chapter_data.get("chapter_title"),
                archive=archive,
                source_kind="existing-series-scrape",
                ingestion_operation_id=operation_id,
                media_operation_id=operation_id,
                source_revision=int(authority["source_revision"]),
                ingestion_generation=int(authority["lease_generation"]),
            ),
            client=client,
            session_id=request.session_id,
        )
        media_operation = await wait_for_media_publication(
            client,
            session_id=request.session_id,
            job_id=operation_id,
        )
        if media_operation.get("status") != "completed":
            return {"status": "publishing", "media_job": media_operation}
        return await _finalize_existing_series_media_publication(
            pool,
            ExistingSeriesPublicationContext(request.draft_id, operation_id, publication.series),
            media_operation,
        )
    except Exception as exc:
        try:
            media_operation = await media_job_status(
                client,
                session_id=request.session_id,
                job_id=operation_id,
            )
        except Exception:
            media_operation = {"status": "unknown"}
        if media_operation.get("status") not in {"queued", "processing", "retry", "completed"}:
            await _reset_existing_series_publication(
                pool,
                draft_id=request.draft_id,
                operation_id=operation_id,
                chapter_data=chapter_data,
                error=exc,
            )
        raise
