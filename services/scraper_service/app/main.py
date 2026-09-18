import logging
import time
import uuid
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from redis.asyncio import Redis

from app.config import settings
from app.db import configure_connection
from app.rabbitmq import RabbitQueueBroker
from app.operation_events import list_operation_events
from app.database_facade import router as database_facade_router
from app.batch_queue import (
    create_batch,
    get_batch,
    list_batches,
    list_failed_items,
    resolve_conflict,
    retry_failed_item,
)
from app.drafts import (
    add_draft_page_from_url,
    add_draft_page_upload,
    create_existing_series_draft,
    get_series_detail,
    preview_draft_page,
    remove_draft_page,
    reorder_draft_pages,
    replace_draft_page_from_url,
    retry_failed_draft_pages,
    search_series,
    update_draft_chapter,
)
from app.models import (
    BatchConflictAction,
    BatchRetryAction,
    DraftChapterUpdate,
    DraftPageFromUrl,
    DraftPageReorder,
    DraftPageReplaceUrl,
    ExistingSeriesDraftCreate,
    IngestChapterRequest,
    NewSeriesDiscoverRequest,
    SeriesDraftChapterUpdate,
    SeriesDraftCoverUrl,
    SeriesDraftPageReorder,
    SeriesDraftPageUrl,
    SeriesDraftStageRequest,
    SeriesDraftUpdate,
    ScrapeRequest,
    ScrapeResponse,
)
from app.scraper import scrape_url
from app.ingestion import MediaSubmission, build_chapter_archive, discover_chapter, submit_to_media
from app.existing_series_publication_routes import router as existing_series_publication_router
from app.security import require_admin, resolve_public_addresses
from app.fetcher import browser_fallback_available, fetch_html
from app.adapters.manga_registry import manga_registry
from app.source_api import discover_naver_manifest, is_naver_url
from app.series_drafts import (
    add_page_upload as series_add_page_upload,
    clear_chapter_titles as series_clear_chapter_titles,
    add_page_url as series_add_page_url,
    acknowledge_scraper_operation,
    cancel_scraper_operation,
    get_series_draft,
    get_series_draft_chapter_pages,
    get_series_workflow_status,
    list_scraper_operations,
    list_series_drafts,
    queue_series_discovery,
    retry_series_discovery,
    unacknowledge_scraper_operation,
    preview_cover as series_preview_cover,
    preview_page as series_preview_page,
    queue_publish as series_queue_publish,
    queue_publish_chapter as series_queue_publish_chapter,
    request_publish_cancel as series_request_publish_cancel,
    queue_stage_chapters,
    remove_cover as series_remove_cover,
    remove_page as series_remove_page,
    reorder_pages as series_reorder_pages,
    replace_cover_from_url as series_replace_cover_from_url,
    update_chapter as series_update_chapter,
    update_series_metadata,
    upload_cover as series_upload_cover,
)

from app.staging_store import cleanup_incomplete_staging_files, ensure_staging_spool, staging_reference_status, staging_runtime_status
from app.storage import (
    get_history,
    list_history,
    save_history,
    store_raw_snapshot,
)


log = logging.getLogger("scraper")
logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)

# libvips emits very verbose per-operation diagnostics at INFO. Keep
# warnings/errors visible, but do not let image internals drown workflow logs.
logging.getLogger("pyvips").setLevel(logging.WARNING)
logging.getLogger("pyvips.voperation").setLevel(logging.WARNING)


async def _initialize_scraper_staging(app: FastAPI) -> bool:
    try:
        app.state.staging = await ensure_staging_spool(app.state.db, service_name="scraper-api")
    except Exception as exc:
        app.state.staging = {"service": "scraper-api", "status": "unavailable", "error_type": type(exc).__name__}
        log.error("scraper staging initialization unavailable type=%s", type(exc).__name__)
        return False
    log.info("validated shared staging spool status=%s", app.state.staging)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(
        settings.database_url,
        init=configure_connection,
        min_size=1,
        max_size=max(2, settings.scraper_api_db_max_connections),
        command_timeout=10,
    )

    staging_ready = await _initialize_scraper_staging(app)
    app.state.staging_ready = staging_ready

    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=max(8, settings.scraper_redis_max_connections),
    )
    app.state.queue = RabbitQueueBroker()

    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.scraper_timeout_seconds,
            connect=settings.scraper_connect_timeout_seconds,
        ),
        limits=httpx.Limits(
            max_connections=max(8, settings.scraper_api_http_max_connections),
            max_keepalive_connections=max(4, settings.scraper_api_http_keepalive_connections),
        ),
        transport=httpx.AsyncHTTPTransport(retries=1),
    )

    if staging_ready:
        removed_parts = await cleanup_incomplete_staging_files()
        if removed_parts:
            log.info("removed stale local staging partials count=%s", removed_parts)

    yield

    await app.state.http.aclose()
    await app.state.queue.close()
    await app.state.redis.aclose()
    await app.state.db.close()


app = FastAPI(
    title="MReader Scraper Service",
    version="1.3.0-rc4.84",
    lifespan=lifespan,
)

app.include_router(existing_series_publication_router)
app.include_router(database_facade_router)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        log.exception(
            "request_failed method=%s path=%s request_id=%s",
            request.method,
            request.url.path,
            request_id,
        )
        raise

    elapsed = round((time.perf_counter() - start) * 1000, 2)

    log.info(
        "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
        request_id,
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "scraper",
        "staging": {
            "mode": "docker-volume",
            **staging_runtime_status(),
            "production_store": "seaweedfs",
        },
    }


@app.get("/health/ready")
async def ready(request: Request):
    try:
        async with request.app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")

        if not request.app.state.staging_ready:
            raise RuntimeError("scraper staging spool is unavailable")

        await request.app.state.redis.ping()
        await request.app.state.queue.ping()

        sw = await request.app.state.http.get(
            f"{settings.seaweedfs_filer_url.rstrip('/')}/"
        )
        sw.raise_for_status()

        return {
            "status": "ok",
            "service": "scraper",
            "dependencies": {
                "postgres": {"ok": True},
                "valkey": {"ok": True},
                "rabbitmq": {"ok": True},
                "seaweedfs": {"ok": True},
                "staging_spool": {"ok": True, **staging_runtime_status()},
            },
        }
    except Exception as exc:
        raise HTTPException(
            503,
            f"Scraper dependency unavailable: {type(exc).__name__}",
        )



@app.post("/api/scraper/diagnose")
async def scraper_diagnose_source(
    payload: NewSeriesDiscoverRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    normalized, addresses = await resolve_public_addresses(str(payload.url))

    fetched = await fetch_html(
        request.app.state.http,
        url=normalized,
        max_bytes=min(settings.scraper_max_response_bytes, 2 * 1024 * 1024),
    )

    naver_api_probe = None
    if is_naver_url(normalized):
        try:
            api_manifest = await discover_naver_manifest(request.app.state.http, normalized)
            naver_api_probe = {
                "strategy": "public-json-api",
                "title": api_manifest.series.title,
                "chapter_count": len(api_manifest.chapters),
                "first_chapter": api_manifest.chapters[0].chapter_number if api_manifest.chapters else None,
            }
        except Exception as exc:
            naver_api_probe = {"strategy": "public-json-api", "error": f"{type(exc).__name__}: {exc}"}

    def run_probes(current_fetch):
        adapter = manga_registry.resolve(current_fetch.final_url)
        html = current_fetch.content.decode("utf-8", errors="replace")

        try:
            manifest = adapter.extract_series_manifest(current_fetch.final_url, html)
            series_probe = {
                "title": manifest.series.title,
                "status": manifest.series.status,
                "cover_url": manifest.series.cover_url,
                "genre_count": len(manifest.genres),
                "tag_count": len(manifest.tags),
                "chapter_count": len(manifest.chapters),
                "first_chapter": (
                    {
                        "number": manifest.chapters[0].chapter_number,
                        "slug": manifest.chapters[0].slug,
                        "url": manifest.chapters[0].url,
                    }
                    if manifest.chapters
                    else None
                ),
            }
        except Exception as exc:
            series_probe = {"error": str(exc)}

        try:
            chapter = adapter.extract_chapter_pages(current_fetch.final_url, html)
            chapter_probe = {
                "chapter_number": chapter.chapter.chapter_number,
                "chapter_slug": chapter.chapter.slug,
                "page_count": len(chapter.page_urls),
            }
        except Exception as exc:
            chapter_probe = {"error": str(exc)}

        return adapter, series_probe, chapter_probe

    adapter, series_probe, chapter_probe = run_probes(fetched)
    browser_retry = False
    browser_retry_error = None

    # If neither series nor chapter parsing can make sense of an otherwise
    # successful static response, diagnose the rendered DOM as well. This is
    # deliberately one bounded attempt, not an unbounded browser crawl.
    if (
        browser_fallback_available()
        and fetched.engine != "scrapling-browser"
        and "error" in series_probe
        and "error" in chapter_probe
    ):
        browser_retry = True
        try:
            rendered = await fetch_html(
                request.app.state.http,
                url=fetched.final_url,
                max_bytes=min(settings.scraper_max_response_bytes, 2 * 1024 * 1024),
                force_browser=True,
                browser_scroll=True,
            )
            fetched = rendered
            adapter, series_probe, chapter_probe = run_probes(fetched)
        except Exception as exc:
            browser_retry_error = f"{type(exc).__name__}: {exc}"

    return {
        "normalized_url": normalized,
        "resolved_addresses": addresses,
        "source_api_probe": naver_api_probe,
        "fetch": {
            "engine": fetched.engine,
            "status": fetched.status_code,
            "final_url": fetched.final_url,
            "content_type": fetched.content_type,
            "bytes": len(fetched.content),
            "redirects": fetched.redirects,
            "duration_ms": fetched.elapsed_ms,
            "browser_retry": browser_retry,
            "browser_retry_error": browser_retry_error,
        },
        "adapter": adapter.name,
        "available_adapters": manga_registry.names(),
        "series_probe": series_probe,
        "chapter_probe": chapter_probe,
    }


@app.post("/api/scraper/scrape", response_model=ScrapeResponse)
async def scrape(
    payload: ScrapeRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    final_url, adapter_name, extracted, raw = await scrape_url(
        request.app.state.http,
        url=str(payload.url),
        mode=payload.mode,
    )

    snapshot_path = None

    if payload.store_raw_snapshot:
        snapshot_path = await store_raw_snapshot(
            request.app.state.http,
            url=final_url,
            html=raw,
        )

    history_id = None

    if payload.save:
        history_id = await save_history(
            request.app.state.db,
            url=final_url,
            mode=payload.mode,
            adapter=adapter_name,
            title=extracted.title,
            summary=extracted.summary,
            status="success",
            result=extracted.result,
            snapshot_path=snapshot_path,
            created_by=admin["user_id"],
        )

    return ScrapeResponse(
        id=history_id,
        adapter=adapter_name,
        url=final_url,
        mode=payload.mode,
        title=extracted.title,
        summary=extracted.summary,
        result=extracted.result,
        snapshot_path=snapshot_path,
    )


@app.get("/api/scraper/history")
async def history(
    request: Request,
    _admin: dict = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return {
        "items": await list_history(
            request.app.state.db,
            limit,
            offset,
        ),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/scraper/history/{history_id}")
async def history_item(
    history_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    row = await get_history(
        request.app.state.db,
        str(history_id),
    )

    if row is None:
        raise HTTPException(404, "Scrape record not found.")

    return row


@app.post("/api/scraper/discover/chapter")
async def discover_manga_chapter(
    payload: IngestChapterRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    adapter, manifest = await discover_chapter(
        request.app.state.http,
        str(payload.manifest.chapter_url),
    )

    return {
        "adapter": adapter,
        "series": {
            "title": manifest.series.title,
            "slug": manifest.series.slug,
            "description": manifest.series.description,
            "cover_url": manifest.series.cover_url,
        },
        "chapter": {
            "title": manifest.chapter.title,
            "slug": manifest.chapter.slug,
            "chapter_number": manifest.chapter.chapter_number,
            "url": manifest.chapter.url,
        },
        "page_count": len(manifest.page_urls),
        "page_urls": manifest.page_urls,
    }


@app.post("/api/scraper/ingest/chapter")
async def ingest_manga_chapter(
    payload: IngestChapterRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    adapter, discovered = await discover_chapter(
        request.app.state.http,
        str(payload.manifest.chapter_url),
    )

    # Explicit request values win over heuristic discovery.
    series_slug = payload.manifest.series_slug
    chapter_slug = payload.manifest.chapter_slug
    chapter_number = payload.manifest.chapter_number
    title = payload.manifest.title or discovered.chapter.title

    archive = await build_chapter_archive(
        request.app.state.http,
        discovered.page_urls,
    )

    media_job = await submit_to_media(
        request,
        MediaSubmission(
            series_slug=series_slug,
            chapter_slug=chapter_slug,
            chapter_number=chapter_number,
            title=title,
            archive=archive,
        ),
    )

    return {
        "status": "queued",
        "adapter": adapter,
        "series_slug": series_slug,
        "chapter_slug": chapter_slug,
        "page_count": len(discovered.page_urls),
        "media_job": media_job,
    }


@app.get("/api/scraper/admin/staging-health")
async def scraper_staging_health(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    runtime = staging_runtime_status()
    runtime.update(await staging_reference_status(request.app.state.db))
    async with request.app.state.db.acquire() as conn:
        registry = await conn.fetchrow(
            "SELECT spool_id::text,logical_root,last_service,last_seen_at FROM scraper_staging_spool_registry WHERE id=1"
        )
    canonical = dict(registry) if registry else None
    runtime["canonical"] = canonical
    runtime["identity_matches"] = bool(
        canonical and runtime.get("spool_id") == str(canonical.get("spool_id"))
    )
    runtime["healthy"] = bool(
        runtime.get("writable")
        and runtime.get("mount_visible")
        and runtime["identity_matches"]
        and int(runtime.get("reference_missing") or 0) == 0
    )
    return runtime


@app.get("/api/scraper/admin/series")
async def scraper_series_search(
    request: Request,
    _admin: dict = Depends(require_admin),
    search: str = Query("", max_length=255),
    limit: int = Query(50, ge=1, le=100),
):
    return await search_series(
        request.app.state.db,
        search=search,
        limit=limit,
    )


@app.get("/api/scraper/admin/series/{series_id}")
async def scraper_series_detail(
    series_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await get_series_detail(
        request.app.state.db,
        str(series_id),
    )


@app.post("/api/scraper/drafts/chapter")
async def create_scraper_chapter_draft(
    payload: ExistingSeriesDraftCreate,
    request: Request,
    admin: dict = Depends(require_admin),
):
    try:
        series_id = str(
            uuid.UUID(payload.series_id)
        )
    except ValueError:
        raise HTTPException(
            400,
            "Invalid series_id.",
        )

    return await create_existing_series_draft(
        request.app.state.db,
        request.app.state.http,
        series_id=series_id,
        chapter_url=str(payload.chapter_url),
        created_by=admin["user_id"],
    )


@app.patch("/api/scraper/drafts/{draft_id}/chapter")
async def scraper_draft_update_chapter(
    draft_id: uuid.UUID,
    payload: DraftChapterUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await update_draft_chapter(
        request.app.state.db,
        draft_id=str(draft_id),
        chapter_number=payload.chapter_number,
        chapter_slug=payload.chapter_slug,
        chapter_title=payload.chapter_title,
    )


@app.delete("/api/scraper/drafts/{draft_id}/pages/{page_id}")
async def scraper_draft_remove_page(
    draft_id: uuid.UUID,
    page_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await remove_draft_page(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        page_id=str(page_id),
    )


@app.post("/api/scraper/drafts/{draft_id}/pages/reorder")
async def scraper_draft_reorder_pages(
    draft_id: uuid.UUID,
    payload: DraftPageReorder,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await reorder_draft_pages(
        request.app.state.db,
        draft_id=str(draft_id),
        page_ids=payload.page_ids,
    )


@app.post("/api/scraper/drafts/{draft_id}/pages/from-url")
async def scraper_draft_add_page_url(
    draft_id: uuid.UUID,
    payload: DraftPageFromUrl,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await add_draft_page_from_url(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        url=str(payload.url),
        position=payload.position,
    )


@app.post("/api/scraper/drafts/{draft_id}/pages/upload")
async def scraper_draft_add_page_upload(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
    file: UploadFile = File(...),
    position: int | None = Form(default=None),
):
    return await add_draft_page_upload(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        file=file,
        position=position,
    )


@app.put("/api/scraper/drafts/{draft_id}/pages/{page_id}/from-url")
async def scraper_draft_replace_page_url(
    draft_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: DraftPageReplaceUrl,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await replace_draft_page_from_url(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        page_id=str(page_id),
        url=str(payload.url),
    )



@app.post("/api/scraper/drafts/{draft_id}/pages/retry-failed")
async def scraper_draft_retry_failed_pages(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await retry_failed_draft_pages(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
    )

@app.get("/api/scraper/drafts/{draft_id}/pages/{page_id}/preview")
async def scraper_draft_page_preview(
    draft_id: uuid.UUID,
    page_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    data, content_type = await preview_draft_page(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        page_id=str(page_id),
    )

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/scraper/batches")
async def scraper_create_batch(
    request: Request,
    admin: dict = Depends(require_admin),
    series_id: str = Form(...),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(...),
):
    try:
        parsed_series_id = str(uuid.UUID(series_id))
    except ValueError:
        raise HTTPException(400, "Invalid series_id.")

    return await create_batch(
        request.app.state.db,
        request.app.state.queue,
        request.app.state.http,
        series_id=parsed_series_id,
        created_by=admin["user_id"],
        files=files,
        relative_paths=relative_paths,
    )


@app.get("/api/scraper/batches")
async def scraper_list_batches(
    request: Request,
    _admin: dict = Depends(require_admin),
    series_id: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=100),
):
    parsed_series_id = None

    if series_id:
        try:
            parsed_series_id = str(uuid.UUID(series_id))
        except ValueError:
            raise HTTPException(400, "Invalid series_id.")

    return await list_batches(
        request.app.state.db,
        series_id=parsed_series_id,
        limit=limit,
    )


@app.get("/api/scraper/batches/failed")
async def scraper_failed_batch_items(
    request: Request,
    _admin: dict = Depends(require_admin),
    series_id: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=200),
):
    parsed_series_id = None

    if series_id:
        try:
            parsed_series_id = str(uuid.UUID(series_id))
        except ValueError:
            raise HTTPException(400, "Invalid series_id.")

    return await list_failed_items(
        request.app.state.db,
        series_id=parsed_series_id,
        limit=limit,
    )


@app.get("/api/scraper/batches/{batch_id}")
async def scraper_batch_detail(
    batch_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await get_batch(
        request.app.state.db,
        str(batch_id),
    )


@app.post("/api/scraper/batches/items/{item_id}/resolve")
async def scraper_batch_resolve_item(
    item_id: uuid.UUID,
    payload: BatchConflictAction,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await resolve_conflict(
        request.app.state.db,
        request.app.state.queue,
        request.app.state.http,
        item_id=str(item_id),
        action=payload.action,
    )


@app.post("/api/scraper/batches/items/{item_id}/retry")
async def scraper_batch_retry_item(
    item_id: uuid.UUID,
    _payload: BatchRetryAction,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await retry_failed_item(
        request.app.state.db,
        request.app.state.queue,
        item_id=str(item_id),
    )


@app.post("/api/scraper/series-drafts/discover")
async def scraper_discover_new_series(
    payload: NewSeriesDiscoverRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    return await queue_series_discovery(
        request.app.state.db,
        request.app.state.queue,
        url=str(payload.url),
        created_by=admin["user_id"],
        recursive=payload.recursive,
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
        request_id=request.state.request_id,
    )


@app.get("/api/scraper/operations")
async def scraper_operations_dashboard(
    request: Request,
    _admin: dict = Depends(require_admin),
    state: str = Query("unacknowledged"),
    limit: int = Query(200, ge=1, le=500),
):
    return await list_scraper_operations(
        request.app.state.db,
        request.app.state.queue,
        state=state,
        limit=limit,
    )


@app.delete("/api/scraper/operations/{draft_id}")
async def scraper_cancel_operation(
    draft_id: uuid.UUID,
    request: Request,
    admin: dict = Depends(require_admin),
):
    return await cancel_scraper_operation(
        request.app.state.db,
        request.app.state.queue,
        request.app.state.http,
        draft_id=str(draft_id),
        admin_id=admin["user_id"],
        request_id=request.state.request_id,
    )


@app.post("/api/scraper/operations/{draft_id}/acknowledge")
async def scraper_acknowledge_operation(
    draft_id: uuid.UUID,
    request: Request,
    admin: dict = Depends(require_admin),
):
    return await acknowledge_scraper_operation(
        request.app.state.db,
        request.app.state.queue,
        request.app.state.http,
        draft_id=str(draft_id),
        admin_id=admin["user_id"],
        request_id=request.state.request_id,
    )


@app.post("/api/scraper/operations/{draft_id}/unacknowledge")
async def scraper_unacknowledge_operation(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await unacknowledge_scraper_operation(
        request.app.state.db,
        draft_id=str(draft_id),
    )


@app.post("/api/scraper/operations/{draft_id}/retry-discovery")
async def scraper_retry_discovery_operation(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await retry_series_discovery(
        request.app.state.db,
        request.app.state.queue,
        draft_id=str(draft_id),
    )


@app.get("/api/scraper/series-drafts")
async def scraper_list_series_drafts(
    request: Request,
    _admin: dict = Depends(require_admin),
    limit: int = Query(50, ge=1, le=100),
):
    return await list_series_drafts(
        request.app.state.db,
        limit=limit,
    )


@app.get("/api/scraper/series-drafts/{draft_id}")
async def scraper_get_series_draft(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await get_series_draft(
        request.app.state.db,
        str(draft_id),
    )


@app.get("/api/scraper/series-drafts/{draft_id}/chapters/{chapter_id}/pages")
async def scraper_get_series_draft_chapter_pages(
    draft_id: uuid.UUID,
    chapter_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await get_series_draft_chapter_pages(
        request.app.state.db,
        draft_id=str(draft_id),
        chapter_id=str(chapter_id),
    )


@app.get("/api/scraper/series-drafts/{draft_id}/workflow-status")
async def scraper_get_series_publish_status(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await get_series_workflow_status(
        request.app.state.db,
        str(draft_id),
    )


@app.get("/api/scraper/series-drafts/{draft_id}/events")
async def scraper_get_series_operation_events(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
    limit: int = Query(250, ge=1, le=500),
    before_id: uuid.UUID | None = Query(None),
):
    try:
        page = await list_operation_events(
            request.app.state.db,
            operation_id=str(draft_id),
            limit=limit,
            before_id=str(before_id) if before_id else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"operation_id": str(draft_id), **page}


@app.patch("/api/scraper/series-drafts/{draft_id}")
async def scraper_update_series_draft(
    draft_id: uuid.UUID,
    payload: SeriesDraftUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await update_series_metadata(
        request.app.state.db,
        draft_id=str(draft_id),
        title=payload.title,
        slug=payload.slug,
        description=payload.description,
        series_status=payload.series_status,
        genres=payload.genres,
        tags=payload.tags,
    )


@app.put("/api/scraper/series-drafts/{draft_id}/cover/from-url")
async def scraper_series_cover_url(
    draft_id: uuid.UUID,
    payload: SeriesDraftCoverUrl,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_replace_cover_from_url(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        url=str(payload.url),
    )


@app.post("/api/scraper/series-drafts/{draft_id}/cover/upload")
async def scraper_series_cover_upload(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
    file: UploadFile = File(...),
):
    return await series_upload_cover(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
        file=file,
    )


@app.delete("/api/scraper/series-drafts/{draft_id}/cover")
async def scraper_series_cover_remove(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_remove_cover(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
    )


@app.get("/api/scraper/series-drafts/{draft_id}/cover/preview")
async def scraper_series_cover_preview(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    data, content_type = await series_preview_cover(
        request.app.state.db,
        request.app.state.http,
        draft_id=str(draft_id),
    )

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/scraper/series-drafts/{draft_id}/chapters/clear-titles")
async def scraper_clear_series_draft_chapter_titles(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_clear_chapter_titles(
        request.app.state.db,
        draft_id=str(draft_id),
    )


@app.patch("/api/scraper/series-drafts/chapters/{chapter_id}")
async def scraper_update_series_draft_chapter(
    chapter_id: uuid.UUID,
    payload: SeriesDraftChapterUpdate,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_update_chapter(
        request.app.state.db,
        chapter_id=str(chapter_id),
        chapter_number=payload.chapter_number,
        chapter_slug=payload.chapter_slug,
        chapter_title=payload.chapter_title,
        selected=payload.selected,
    )


@app.post("/api/scraper/series-drafts/{draft_id}/stage")
async def scraper_stage_series_draft_chapters(
    draft_id: uuid.UUID,
    payload: SeriesDraftStageRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await queue_stage_chapters(
        request.app.state.db,
        request.app.state.queue,
        draft_id=str(draft_id),
        chapter_ids=payload.chapter_ids,
        request_id=request.state.request_id,
    )


@app.delete("/api/scraper/series-drafts/chapters/{chapter_id}/pages/{page_id}")
async def scraper_series_draft_remove_page(
    chapter_id: uuid.UUID,
    page_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_remove_page(
        request.app.state.db,
        request.app.state.http,
        chapter_id=str(chapter_id),
        page_id=str(page_id),
    )


@app.post("/api/scraper/series-drafts/chapters/{chapter_id}/pages/reorder")
async def scraper_series_draft_reorder_pages(
    chapter_id: uuid.UUID,
    payload: SeriesDraftPageReorder,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_reorder_pages(
        request.app.state.db,
        chapter_id=str(chapter_id),
        page_ids=payload.page_ids,
    )


@app.post("/api/scraper/series-drafts/chapters/{chapter_id}/pages/from-url")
async def scraper_series_draft_add_page_url(
    chapter_id: uuid.UUID,
    payload: SeriesDraftPageUrl,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_add_page_url(
        request.app.state.db,
        request.app.state.http,
        chapter_id=str(chapter_id),
        url=str(payload.url),
        position=payload.position,
    )


@app.post("/api/scraper/series-drafts/chapters/{chapter_id}/pages/upload")
async def scraper_series_draft_add_page_upload(
    chapter_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
    file: UploadFile = File(...),
    position: int | None = Form(default=None),
):
    return await series_add_page_upload(
        request.app.state.db,
        request.app.state.http,
        chapter_id=str(chapter_id),
        file=file,
        position=position,
    )


@app.get("/api/scraper/series-drafts/chapters/{chapter_id}/pages/{page_id}/preview")
async def scraper_series_draft_page_preview(
    chapter_id: uuid.UUID,
    page_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    data, content_type = await series_preview_page(
        request.app.state.db,
        request.app.state.http,
        chapter_id=str(chapter_id),
        page_id=str(page_id),
    )

    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/scraper/series-drafts/{draft_id}/chapters/{chapter_id}/publish")
async def scraper_publish_one_series_draft_chapter(
    draft_id: uuid.UUID,
    chapter_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_queue_publish_chapter(
        request.app.state.db,
        request.app.state.queue,
        draft_id=str(draft_id),
        chapter_id=str(chapter_id),
        request_id=request.state.request_id,
    )


@app.post("/api/scraper/series-drafts/{draft_id}/publish")
async def scraper_publish_series_draft(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_queue_publish(
        request.app.state.db,
        request.app.state.queue,
        draft_id=str(draft_id),
        request_id=request.state.request_id,
    )


@app.post("/api/scraper/series-drafts/{draft_id}/publish/cancel")
async def scraper_cancel_series_publish(
    draft_id: uuid.UUID,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    return await series_request_publish_cancel(
        request.app.state.db,
        draft_id=str(draft_id),
    )
