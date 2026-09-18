import asyncio
import io
import mimetypes
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

import httpx
from fastapi import HTTPException, Request

from app.adapters.manga_registry import manga_registry
from app.config import settings
from app.fetcher import browser_fallback_available, fetch_html, fetch_image


MAX_PAGES = 1000
MAX_PAGE_BYTES = 50 * 1024 * 1024
MAX_CHAPTER_BYTES = 500 * 1024 * 1024
DOWNLOAD_CONCURRENCY = max(1, settings.scraper_image_download_concurrency)


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


async def discover_chapter(
    client: httpx.AsyncClient,
    url: str,
):
    final_url, raw = await _fetch_html(client, url)

    adapter = manga_registry.resolve(final_url)

    try:
        manifest = adapter.extract_chapter_pages(
            final_url,
            raw.decode(
                "utf-8",
                errors="replace",
            ),
        )
    except ValueError as exc:
        if not browser_fallback_available():
            raise HTTPException(422, str(exc))
        try:
            final_url, raw = await _fetch_html(
                client,
                url,
                force_browser=True,
                browser_scroll=True,
            )
            adapter = manga_registry.resolve(final_url)
            manifest = adapter.extract_chapter_pages(
                final_url,
                raw.decode("utf-8", errors="replace"),
            )
        except Exception:
            raise HTTPException(422, str(exc))

    if len(manifest.page_urls) > MAX_PAGES:
        raise HTTPException(
            413,
            f"Chapter has too many pages ({len(manifest.page_urls)}).",
        )

    return adapter.name, manifest


async def _download_page(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    index: int,
    url: str,
    referer: str | None = None,
) -> tuple[int, bytes, str]:
    async with sem:
        fetched = await fetch_image(
            client,
            url=url,
            referer=referer,
            max_bytes=MAX_PAGE_BYTES,
        )

    return index, fetched.content, fetched.content_type


async def build_chapter_archive(
    client: httpx.AsyncClient,
    page_urls: list[str],
    *,
    referer: str | None = None,
) -> bytes:
    sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    downloaded = await asyncio.gather(
        *[
            _download_page(
                client,
                sem,
                index,
                url,
                referer,
            )
            for index, url in enumerate(page_urls, start=1)
        ]
    )

    total_bytes = sum(
        len(data)
        for _, data, _ in downloaded
    )

    if total_bytes > MAX_CHAPTER_BYTES:
        raise HTTPException(
            413,
            "Downloaded chapter exceeds 500 MiB.",
        )

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_STORED,
    ) as zf:
        for index, data, content_type in downloaded:
            ext = (
                mimetypes.guess_extension(content_type)
                or ".img"
            )

            if ext == ".jpe":
                ext = ".jpg"

            zf.writestr(
                f"{index:04d}{ext}",
                data,
            )

    return buffer.getvalue()


@dataclass(frozen=True)
class MediaSubmission:
    series_slug: str
    chapter_slug: str
    chapter_number: str
    title: str | None
    archive: bytes | BinaryIO
    source_kind: str | None = None
    ingestion_operation_id: str | None = None
    media_operation_id: str | None = None
    source_revision: int = 1
    ingestion_generation: int = 1
    chapter_id: str | None = None
    expected_revision: int = 0


PUBLICATION_CONFLICT_CODES = (
    "idempotency_conflict",
    "stale_catalog_revision",
    "publication_conflict",
    "publication_target_not_found",
)


def _raise_catalog_publication_conflict(status_value: str, error: object) -> None:
    """Map terminal Catalog publication conflicts to an admin-actionable 409."""
    if status_value != "completed":
        return
    text = str(error or "").lower()
    if any(code in text for code in PUBLICATION_CONFLICT_CODES):
        raise HTTPException(409, f"Catalog publication conflict: {error}")


def _media_transport(
    *,
    session_id: str | None,
    requesting_actor_id: str | None,
    path: str,
) -> tuple[str, dict[str, str]]:
    if session_id:
        return (
            f"{settings.image_internal_url.rstrip('/')}/api/upload/jobs/{path.lstrip('/')}",
            {"Cookie": f"{settings.SESSION_COOKIE_NAME}={session_id}"},
        )
    if requesting_actor_id:
        token = settings.media_internal_token.strip()
        if not token:
            raise HTTPException(503, "Media internal transport is not configured.")
        return (
            f"{settings.image_internal_url.rstrip('/')}/internal/v1/media/jobs/{path.lstrip('/')}",
            {
                "X-MReader-Requesting-Actor-ID": requesting_actor_id,
                "X-MReader-Internal-Token": token,
            },
        )
    raise HTTPException(401, "Not authenticated.")


async def submit_to_media(
    request: Request | None,
    submission: MediaSubmission,
    *,
    client: httpx.AsyncClient | None = None,
    session_id: str | None = None,
    requesting_actor_id: str | None = None,
) -> dict:
    if request is not None:
        client = request.app.state.http
        session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if client is None:
        raise RuntimeError("Media submission requires an HTTP client.")

    archive = submission.archive
    if hasattr(archive, "seek"):
        archive.seek(0)
    files = {
        "file": (
            f"{submission.chapter_slug}.zip",
            archive,
            "application/zip",
        )
    }
    data: dict[str, str] = {
        "chapter_number": submission.chapter_number,
        "source_revision": str(submission.source_revision),
        "ingestion_generation": str(submission.ingestion_generation),
        "expected_revision": str(submission.expected_revision),
    }
    optional = {
        "title": submission.title,
        "source_kind": submission.source_kind,
        "ingestion_operation_id": submission.ingestion_operation_id,
        "media_operation_id": submission.media_operation_id,
        "chapter_id": submission.chapter_id,
    }
    data.update({key: str(value) for key, value in optional.items() if value})
    url, headers = _media_transport(
        session_id=session_id,
        requesting_actor_id=requesting_actor_id,
        path=f"chapter/{submission.series_slug}/{submission.chapter_slug}",
    )
    response = await client.post(url, files=files, data=data, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"Media ingestion rejected chapter: {response.text[:1000]}",
        )
    return response.json()



async def _media_request_json(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    requesting_actor_id: str | None,
    session_id: str | None = None,
    files: dict | None = None,
    missing_job_id: str | None = None,
    error_prefix: str,
) -> dict:
    url, headers = _media_transport(
        session_id=session_id,
        requesting_actor_id=requesting_actor_id,
        path=path,
    )
    response = await client.request(method, url, headers=headers, files=files)
    if missing_job_id is not None and response.status_code == 404:
        return {"job_id": missing_job_id, "status": "missing"}
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"{error_prefix}: {response.text[:1000]}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(502, f"{error_prefix}: invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, f"{error_prefix}: invalid JSON response")
    return payload

async def media_job_status(
    client: httpx.AsyncClient,
    *,
    job_id: str,
    session_id: str | None = None,
    requesting_actor_id: str | None = None,
) -> dict:
    return await _media_request_json(
        client,
        method="GET",
        path=job_id,
        session_id=session_id,
        requesting_actor_id=requesting_actor_id,
        missing_job_id=job_id,
        error_prefix="Media job status failed",
    )


async def wait_for_media_publication(
    client: httpx.AsyncClient,
    *,
    job_id: str,
    session_id: str | None = None,
    requesting_actor_id: str | None = None,
    timeout_seconds: float = 180.0,
) -> dict:
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
    while True:
        operation = await media_job_status(
            client,
            session_id=session_id,
            requesting_actor_id=requesting_actor_id,
            job_id=job_id,
        )
        status_value = str(operation.get("status") or "")
        result = dict(operation.get("result") or {})
        _raise_catalog_publication_conflict(status_value, operation.get("error"))
        if status_value == "completed" and result.get("published") and isinstance(result.get("catalog_receipt"), dict):
            return operation
        if status_value == "failed":
            raise HTTPException(502, f"Media publication failed: {operation.get('error') or 'unknown error'}")
        if status_value == "missing":
            raise HTTPException(503, "Media publication acceptance is not yet visible.")
        if asyncio.get_running_loop().time() >= deadline:
            return operation
        await asyncio.sleep(0.5)


async def submit_series_cover_to_media(
    client: httpx.AsyncClient,
    *,
    series_slug: str,
    image_data: bytes,
    content_type: str,
    filename: str,
    requesting_actor_id: str,
) -> dict:
    return await _media_request_json(
        client,
        method="POST",
        path=f"thumbnail/{series_slug}",
        requesting_actor_id=requesting_actor_id,
        files={"file": (filename, image_data, content_type)},
        error_prefix="Media cover ingestion rejected series",
    )


async def wait_for_media_job_completion(
    client: httpx.AsyncClient,
    *,
    job_id: str,
    requesting_actor_id: str,
    timeout_seconds: float = 180.0,
) -> dict:
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
    while True:
        operation = await media_job_status(
            client,
            job_id=job_id,
            requesting_actor_id=requesting_actor_id,
        )
        status_value = str(operation.get("status") or "")
        if status_value == "completed":
            return operation
        if status_value == "failed":
            raise HTTPException(502, f"Media cover processing failed: {operation.get('error') or 'unknown error'}")
        if status_value == "missing":
            raise HTTPException(503, "Media cover acceptance is not yet visible.")
        if asyncio.get_running_loop().time() >= deadline:
            return operation
        await asyncio.sleep(0.5)
