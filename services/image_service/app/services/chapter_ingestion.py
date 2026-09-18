from __future__ import annotations

import asyncio
import hashlib
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from shared import AsyncSessionLocal, Series, get_seaweedfs
from shared.catalog_publication_contract import manifest_digest
from shared.tilepack_codec import new_seed

from app.catalog_publication import (
    build_manifest,
    build_publication_command,
    publish_catalog_command,
)
from app.media_operations import (
    MediaOperationLeaseLost,
    complete_media_operation,
    get_media_operation,
    record_catalog_publication_receipt,
    record_publication_completion_evidence,
)
from app.lifecycle_cleanup import enqueue_production_output_cleanup
from app.services.image_processor import (
    iter_archive_bytes,
    iter_archive_file,
    iter_pdf_bytes,
    iter_pdf_file,
    process_single_image,
)


log = logging.getLogger(__name__)
_PAGE_ITER_END = object()


async def _drain_sync_pages(page_iter, store_page) -> None:
    """Drain a synchronous converter while keeping Media memory bounded."""
    iterator = iter(page_iter)
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)

    async def _produce() -> None:
        while True:
            try:
                page = await asyncio.to_thread(next, iterator, _PAGE_ITER_END)
            except Exception as exc:
                await queue.put((_PAGE_ITER_END, exc))
                return
            await queue.put((page, None))
            if page is _PAGE_ITER_END:
                return

    producer = asyncio.create_task(_produce(), name="chapter-page-converter")
    try:
        while True:
            page, error = await queue.get()
            if error is not None:
                raise error
            if page is _PAGE_ITER_END:
                break
            await store_page(page)
        await producer
    finally:
        if not producer.done():
            producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


async def _series_by_slug(db, slug: str) -> Series | None:
    result = await db.execute(select(Series).where(Series.slug == slug))
    return result.scalar_one_or_none()


def _page_output_paths(pages: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for page in pages:
        for path in (page.get("image_path"), (page.get("responsive") or {}).get("image_path")):
            if path and str(path) not in paths:
                paths.append(str(path))
    return paths


def _chapter_seed(media_operation_id: str | None) -> str:
    if not media_operation_id:
        return new_seed()
    return hashlib.sha256(
        f"mreader-media-chapter:{media_operation_id}".encode("utf-8")
    ).hexdigest()[:32]


async def _queue_created_paths_cleanup(
    media_operation_id: str,
    media_generation: int,
    series_id: str,
    paths: list[str],
) -> None:
    try:
        await enqueue_production_output_cleanup(
            media_operation_id=media_operation_id,
            media_generation=media_generation,
            paths=paths,
            kind="page-output",
            reason="media-uncommitted-chapter-output",
            series_id=series_id,
        )
    except Exception:
        # Never fall back to direct production deletion here. A cleanup-queue
        # outage may leak bytes temporarily; a stale direct delete can destroy
        # replacement output that reused the deterministic path.
        log.exception(
            "failed to enqueue chapter production cleanup operation=%s generation=%s",
            media_operation_id,
            media_generation,
        )


def _required_metadata(operation: dict[str, Any], name: str) -> Any:
    metadata = dict(operation.get("metadata") or {})
    value = metadata.get(name)
    if value is None or value == "":
        raise ValueError(f"media operation is missing publication metadata: {name}")
    return value


def _published_result(transform_result: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        **transform_result,
        "success": True,
        "published": True,
        "chapter_id": receipt["chapter_id"],
        "chapter_revision": receipt["chapter_revision"],
        "series_revision": receipt["series_revision"],
        "publication_event_id": receipt["publication_event_id"],
        "catalog_receipt": receipt,
    }


async def reconcile_completed_chapter_publication(media_operation_id: str) -> dict[str, Any]:
    """Replay one sealed Catalog command without repeating Media transformation."""
    async with AsyncSessionLocal() as db:
        operation = await get_media_operation(db, media_operation_id)
    if operation is None:
        raise ValueError("media operation not found")
    if operation.get("status") != "completed" or operation.get("completion_evidence") is None:
        raise ValueError("media transformation is not durably complete")

    result = dict(operation.get("result") or {})
    command = result.get("publication_command")
    if not isinstance(command, dict):
        raise ValueError("completed media operation is missing its sealed publication command")
    receipt = result.get("catalog_receipt")
    if isinstance(receipt, dict):
        return _published_result(result, receipt)

    receipt = await publish_catalog_command(command)
    async with AsyncSessionLocal() as db:
        await record_catalog_publication_receipt(
            db,
            operation_id=media_operation_id,
            receipt=receipt,
        )
        await db.commit()
    return _published_result(result, receipt)


async def _ingest_chapter_source(
    *,
    archive_data: bytes | None = None,
    archive_path: str | None = None,
    filename: str,
    content_type: str,
    series_slug: str,
    chapter_slug: str,
    chapter_number: Decimal,
    title: str | None,
    first_image_data: bytes | None = None,
    last_image_data: bytes | None = None,
    idempotent_existing: bool = False,
    media_operation_id: str | None = None,
) -> dict:
    """Transform one durable Media job, persist evidence, then ask Catalog to publish.

    Catalog publication is deliberately outside the Media transaction. Once the
    transform/evidence transaction commits, retries reconcile the sealed Catalog
    command and never re-encode or delete the immutable output merely because an
    HTTP response was lost.
    """
    del idempotent_existing  # Catalog receipt/idempotency is now the retry authority.
    if not media_operation_id:
        raise ValueError("chapter ingestion requires a durable media operation")
    if (archive_data is None) == (archive_path is None):
        raise ValueError("Exactly one of archive_data or archive_path is required.")

    sw = get_seaweedfs()
    created_paths: list[str] = []
    evidence_committed = False

    try:
        async with AsyncSessionLocal() as db:
            series = await _series_by_slug(db, series_slug)
            operation = await get_media_operation(db, media_operation_id, for_update=True)
        if series is None:
            raise ValueError(f"Series '{series_slug}' not found.")
        if operation is None:
            raise ValueError("media operation not found")
        media_generation = int(operation.get("media_generation") or 0)
        if media_generation < 1:
            raise ValueError("media operation has no active generation")

        lower_name = (filename or "").lower()
        is_pdf = content_type == "application/pdf" or lower_name.endswith(".pdf")
        chapter_seed = _chapter_seed(media_operation_id)
        core_start_page = 1
        prefix_pages: list[dict] = []
        if first_image_data:
            prefix_pages = await asyncio.to_thread(
                process_single_image,
                first_image_data,
                series_slug,
                chapter_slug,
                core_start_page,
                chapter_seed,
            )
            core_start_page += len(prefix_pages)

        if is_pdf:
            page_iter = (
                iter_pdf_file(
                    archive_path,
                    series_slug,
                    chapter_slug,
                    start_page_number=core_start_page,
                    chapter_seed=chapter_seed,
                )
                if archive_path is not None
                else iter_pdf_bytes(
                    archive_data or b"",
                    series_slug,
                    chapter_slug,
                    start_page_number=core_start_page,
                    chapter_seed=chapter_seed,
                )
            )
        else:
            page_iter = (
                iter_archive_file(
                    archive_path,
                    series_slug,
                    chapter_slug,
                    start_page_number=core_start_page,
                    chapter_seed=chapter_seed,
                )
                if archive_path is not None
                else iter_archive_bytes(
                    archive_data or b"",
                    series_slug,
                    chapter_slug,
                    start_page_number=core_start_page,
                    chapter_seed=chapter_seed,
                )
            )

        pages: list[dict[str, Any]] = []

        async def _store_page(page: dict[str, Any]) -> None:
            primary_data = page["data"]
            img_path = page["image_path"].removeprefix("images/").lstrip("/")
            await sw.upload_via_filer(
                img_path,
                primary_data,
                page.get("content_type", "application/vnd.mreader.tilepack"),
            )
            created_paths.append(img_path)

            responsive = page.get("responsive")
            responsive_meta = None
            if responsive:
                responsive_data = responsive["data"]
                responsive_path = responsive["image_path"].removeprefix("images/").lstrip("/")
                await sw.upload_via_filer(
                    responsive_path,
                    responsive_data,
                    responsive.get("content_type", "application/vnd.mreader.tilepack"),
                )
                created_paths.append(responsive_path)
                responsive_meta = {
                    "image_path": responsive_path,
                    "width": int(responsive["width"]),
                    "height": int(responsive["height"]),
                    "size_bytes": len(responsive_data),
                    "sha256": hashlib.sha256(responsive_data).hexdigest(),
                }

            pages.append(
                {
                    "page_number": int(page["page_number"]),
                    "image_path": img_path,
                    "width": int(page["width"]),
                    "height": int(page["height"]),
                    "size_bytes": len(primary_data),
                    "sha256": hashlib.sha256(primary_data).hexdigest(),
                    "encoding_version": int(page.get("encoding_version", 4)),
                    "encoding_rows": int(page["encoding_rows"]),
                    "encoding_columns": int(page["encoding_columns"]),
                    "encoding_seed": str(page["encoding_seed"]),
                    "responsive": responsive_meta,
                }
            )

        for page in prefix_pages:
            await _store_page(page)
        await _drain_sync_pages(page_iter, _store_page)

        if last_image_data:
            tail_pages = await asyncio.to_thread(
                process_single_image,
                last_image_data,
                series_slug,
                chapter_slug,
                len(pages) + 1,
                chapter_seed,
            )
            for page in tail_pages:
                await _store_page(page)
        if not pages:
            raise ValueError("chapter transformation produced no pages")

        manifest = build_manifest(
            series_id=str(series.id),
            series_slug=series_slug,
            chapter_slug=chapter_slug,
            pages=pages,
        )
        command = build_publication_command(
            idempotency_key=str(_required_metadata(operation, "idempotency_key")),
            operation_id=str(_required_metadata(operation, "operation_id")),
            actor_id=str(_required_metadata(operation, "actor_id")),
            source_revision=int(_required_metadata(operation, "source_revision")),
            ingestion_generation=int(_required_metadata(operation, "ingestion_generation")),
            media_operation_id=media_operation_id,
            media_generation=media_generation,
            chapter_id=(dict(operation.get("metadata") or {}).get("chapter_id") or None),
            expected_revision=int(dict(operation.get("metadata") or {}).get("expected_revision") or 0),
            chapter_number=chapter_number,
            title=title,
            manifest=manifest,
        )
        transform_result = {
            "success": True,
            "transformation_completed": True,
            "published": False,
            "series_id": str(series.id),
            "series_slug": series_slug,
            "chapter_slug": chapter_slug,
            "page_count": len(pages),
            "pages": pages,
            "total_size_bytes": sum(int(page["size_bytes"]) for page in pages),
            "publication_command": command,
        }

        async with AsyncSessionLocal() as db:
            await complete_media_operation(
                db,
                operation_id=media_operation_id,
                series_id=str(series.id),
                chapter_id=None,
                output_paths=_page_output_paths(pages),
                result=transform_result,
                source="chapter-ingestion",
                expected_generation=media_generation,
            )
            await record_publication_completion_evidence(
                db,
                media_operation_id=media_operation_id,
                operation_id=str(command["operation_id"]),
                actor_id=str(command["actor_id"]),
                source_revision=int(command["source_revision"]),
                manifest_sha256=manifest_digest(manifest),
                page_count=len(pages),
            )
            await db.commit()
        evidence_committed = True

        return await reconcile_completed_chapter_publication(media_operation_id)

    except MediaOperationLeaseLost:
        log.warning(
            "media lease lost; preserving deterministic chapter outputs for replacement generation operation=%s",
            media_operation_id,
        )
        raise
    except Exception:
        if not evidence_committed:
            if created_paths:
                await _queue_created_paths_cleanup(
                    media_operation_id,
                    media_generation,
                    str(series.id),
                    created_paths,
                )
        else:
            log.warning(
                "Catalog publication is pending; preserving durable Media outputs operation=%s",
                media_operation_id,
                exc_info=True,
            )
        raise


async def ingest_chapter_bytes(
    *,
    archive_data: bytes,
    filename: str,
    content_type: str,
    series_slug: str,
    chapter_slug: str,
    chapter_number: Decimal,
    title: str | None,
    first_image_data: bytes | None = None,
    last_image_data: bytes | None = None,
    idempotent_existing: bool = False,
    media_operation_id: str | None = None,
) -> dict:
    return await _ingest_chapter_source(
        archive_data=archive_data,
        filename=filename,
        content_type=content_type,
        series_slug=series_slug,
        chapter_slug=chapter_slug,
        chapter_number=chapter_number,
        title=title,
        first_image_data=first_image_data,
        last_image_data=last_image_data,
        idempotent_existing=idempotent_existing,
        media_operation_id=media_operation_id,
    )


async def ingest_chapter_file(
    *,
    archive_path: str,
    filename: str,
    content_type: str,
    series_slug: str,
    chapter_slug: str,
    chapter_number: Decimal,
    title: str | None,
    first_image_data: bytes | None = None,
    last_image_data: bytes | None = None,
    idempotent_existing: bool = False,
    media_operation_id: str | None = None,
) -> dict:
    return await _ingest_chapter_source(
        archive_path=archive_path,
        filename=filename,
        content_type=content_type,
        series_slug=series_slug,
        chapter_slug=chapter_slug,
        chapter_number=chapter_number,
        title=title,
        first_image_data=first_image_data,
        last_image_data=last_image_data,
        idempotent_existing=idempotent_existing,
        media_operation_id=media_operation_id,
    )
