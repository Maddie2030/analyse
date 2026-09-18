import asyncio
import hashlib
import logging
import os
import tempfile
from contextlib import asynccontextmanager

import httpx
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from shared import (
    AsyncSessionLocal,
    Series,
    close_seaweedfs_client,
    get_seaweedfs,
    init_seaweedfs_client,
)

from app.rabbitmq import CHAPTER_QUEUE, THUMBNAIL_QUEUE, JobDeferred, RabbitJobBroker
from app.media_config import LIMITS
from app.catalog_series import set_catalog_series_cover
from app.lifecycle_cleanup import enqueue_production_output_cleanup
from app.media_operations import (
    MediaOperationLeaseLost,
    complete_media_operation,
    fail_media_operation,
    heartbeat_media_operation,
    get_media_operation,
    mark_media_retry,
    record_queue_error,
    recoverable_media_operations,
    start_media_operation,
)
from app.services.chapter_ingestion import (
    ingest_chapter_file,
    reconcile_completed_chapter_publication,
)
from app.services.image_processor import convert_image_to_webp


log = logging.getLogger(__name__)


async def _convert_thumbnail_bytes(source_bytes: bytes) -> tuple[bytes, int, int]:
    """Use the optional scale-to-zero transformer, with local libvips fallback.

    This is intentionally limited to thumbnails/covers. Reader page/tile encoding remains
    local because cross-cloud transfer would overwhelm the serverless free egress grants.
    """
    remote_url = os.getenv("REMOTE_THUMBNAIL_TRANSFORM_URL", "").strip().rstrip("/")
    remote_token = os.getenv("REMOTE_THUMBNAIL_TRANSFORM_TOKEN", "")
    if remote_url and remote_token:
        timeout = float(os.getenv("REMOTE_THUMBNAIL_TRANSFORM_TIMEOUT_SECONDS", "20"))
        max_width = int(os.getenv("REMOTE_THUMBNAIL_TRANSFORM_WIDTH", "0") or 0)
        url = f"{remote_url}/v1/thumbnail"
        params = {"width": str(max_width)} if max_width > 0 else None
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    params=params,
                    content=source_bytes,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-MReader-Transform-Token": remote_token,
                    },
                )
            response.raise_for_status()
            width = int(response.headers["X-Image-Width"])
            height = int(response.headers["X-Image-Height"])
            if not response.content or width <= 0 or height <= 0:
                raise ValueError("remote transformer returned an invalid image")
            return response.content, width, height
        except Exception:
            if os.getenv("REMOTE_THUMBNAIL_TRANSFORM_FALLBACK_LOCAL", "true").lower() not in {"1", "true", "yes", "on"}:
                raise
            log.warning("remote thumbnail transform failed; falling back to local libvips", exc_info=True)
    return convert_image_to_webp(source_bytes)


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


MEDIA_WORKER_MAX_TRIES = _bounded_int_env("MEDIA_WORKER_MAX_TRIES", 3, 1, 10)
MEDIA_RECOVERY_INTERVAL_SECONDS = _bounded_int_env("MEDIA_RECOVERY_INTERVAL_SECONDS", 30, 5, 300)
MEDIA_PROCESSING_LEASE_SECONDS = _bounded_int_env("MEDIA_PROCESSING_LEASE_SECONDS", 120, 60, 3600)
MEDIA_HEARTBEAT_INTERVAL_SECONDS = _bounded_int_env("MEDIA_HEARTBEAT_INTERVAL_SECONDS", 30, 10, 300)


async def _record_queue_error(operation_id: str, error: str | None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await record_queue_error(db, operation_id, error)
            await db.commit()
    except Exception:
        log.warning("failed to persist media queue diagnostic operation=%s", operation_id, exc_info=True)


async def _reconcile_recoverable_publication(operation: dict) -> bool:
    if operation["job_type"] != "chapter-ingestion" or operation.get("status") != "completed":
        return False
    operation_id = str(operation["operation_id"])
    await reconcile_completed_chapter_publication(operation_id)
    await _record_queue_error(operation_id, None)
    return True


async def _republish_recoverable_operation(broker: RabbitJobBroker, operation: dict) -> bool:
    operation_id = str(operation["operation_id"])
    if operation["job_type"] == "thumbnail-generation":
        await broker.publish(
            THUMBNAIL_QUEUE,
            operation_id,
            {
                "series_slug": operation["series_slug"],
                "source_path": operation["staged_object_path"],
            },
        )
        return True
    if operation["job_type"] != "chapter-ingestion":
        return False
    metadata = dict(operation.get("metadata") or {})
    await broker.publish(
        CHAPTER_QUEUE,
        operation_id,
        {
            "series_slug": operation["series_slug"],
            "chapter_slug": operation.get("chapter_slug") or metadata.get("chapter_slug"),
            "source_path": operation["staged_object_path"],
            "filename": operation.get("input_filename") or metadata.get("filename") or "upload.bin",
            "content_type": operation.get("input_content_type") or metadata.get("content_type") or "application/octet-stream",
            "chapter_number": str(metadata.get("chapter_number") or "1.0"),
            "title": metadata.get("title"),
            "first_image_path": metadata.get("first_image_path"),
            "last_image_path": metadata.get("last_image_path"),
        },
    )
    return True


async def _recover_durable_operations(broker: RabbitJobBroker) -> None:
    """Republish transform work or reconcile sealed publication receipts."""
    try:
        async with AsyncSessionLocal() as db:
            operations = await recoverable_media_operations(db, stale_after_seconds=MEDIA_PROCESSING_LEASE_SECONDS)
            await db.commit()
    except Exception:
        log.exception("failed to scan durable media operations during startup")
        return

    recovered = 0
    for operation in operations:
        operation_id = str(operation["operation_id"])
        try:
            if await _reconcile_recoverable_publication(operation):
                recovered += 1
                continue
            if not await _republish_recoverable_operation(broker, operation):
                continue
            await _record_queue_error(operation_id, None)
            recovered += 1
        except Exception as exc:
            await _record_queue_error(operation_id, f"{type(exc).__name__}: {exc}")
            log.warning("failed to republish durable media operation=%s", operation_id, exc_info=True)

    if recovered:
        log.info("republished %d durable media operation(s) to RabbitMQ", recovered)


async def _media_recovery_loop(broker: RabbitJobBroker) -> None:
    while True:
        try:
            await asyncio.sleep(MEDIA_RECOVERY_INTERVAL_SECONDS)
            await _recover_durable_operations(broker)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("periodic durable media recovery failed")


async def _start_operation(operation_id: str):
    async with AsyncSessionLocal() as db:
        operation = await start_media_operation(db, operation_id, stale_after_seconds=MEDIA_PROCESSING_LEASE_SECONDS)
        await db.commit()
        return operation


@asynccontextmanager
async def _media_operation_session():
    async with AsyncSessionLocal() as db:
        yield db
        await db.commit()


async def _persist_worker_failure_state(
    operation_id: str,
    error: str,
    expected_generation: int,
    *,
    source: str | None = None,
) -> bool | None:
    try:
        async with _media_operation_session() as db:
            if source is None:
                await mark_media_retry(
                    db,
                    operation_id,
                    error,
                    expected_generation=expected_generation,
                )
                return None
            await fail_media_operation(
                db,
                operation_id=operation_id,
                error=error,
                source=source,
                expected_generation=expected_generation,
            )
            return True
    except MediaOperationLeaseLost:
        raise
    except Exception:
        if source is None:
            log.warning("failed to mark media retry operation=%s", operation_id, exc_info=True)
            return None
        log.exception("failed to commit terminal media failure operation=%s", operation_id)
        return False


async def _mark_retry(operation_id: str, error: str, expected_generation: int) -> None:
    await _persist_worker_failure_state(operation_id, error, expected_generation)


async def _media_operation_heartbeat(
    operation_id: str,
    expected_generation: int,
    stop: asyncio.Event,
) -> None:
    """Renew a processing lease while an expensive Media transform is alive."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=MEDIA_HEARTBEAT_INTERVAL_SECONDS)
            break
        except asyncio.TimeoutError:
            pass
        try:
            async with AsyncSessionLocal() as db:
                alive = await heartbeat_media_operation(
                    db,
                    operation_id,
                    expected_generation=expected_generation,
                )
                await db.commit()
            if not alive:
                return
        except Exception:
            log.warning("media processing heartbeat failed operation=%s", operation_id, exc_info=True)


async def _stop_heartbeat(stop: asyncio.Event, task: asyncio.Task | None) -> None:
    stop.set()
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _thumbnail_commit_outcome(
    job_id: str,
    series_slug: str,
    image_path: str,
    expected_generation: int,
) -> bool | None:
    """Resolve a COMMIT acknowledgement failure from canonical PostgreSQL state.

    True means the cover is definitely canonical, False means PostgreSQL proves
    it is not canonical, and None means the DB could not be reached so deletion
    would be unsafe.
    """
    try:
        async with AsyncSessionLocal() as db:
            series = (await db.execute(select(Series).where(Series.slug == series_slug))).scalar_one_or_none()
            operation = await get_media_operation(db, job_id)
        if (
            series is not None
            and str(series.cover_image_path or "") == image_path
            and int(series.cover_media_generation or 0) == int(expected_generation)
        ):
            return True
        if (
            operation
            and operation.get("status") == "completed"
            and int(operation.get("media_generation") or 0) == int(expected_generation)
        ):
            outputs = {str(value) for value in (operation.get("output_paths") or [])}
            if image_path in outputs:
                return True
        return False
    except Exception:
        log.warning(
            "could not resolve thumbnail commit outcome; preserving uploaded object job=%s path=%s",
            job_id, image_path, exc_info=True,
        )
        return None


async def _mark_final_failure(
    operation_id: str,
    error: str,
    source: str,
    expected_generation: int,
) -> bool:
    result = await _persist_worker_failure_state(
        operation_id,
        error,
        expected_generation,
        source=source,
    )
    return bool(result)


async def generate_thumbnail(ctx, job_id: str, series_slug: str, source_path: str):
    payload = {"series_slug": series_slug, "source_path": source_path}
    operation = await _start_operation(job_id)
    if operation is None:
        raise RuntimeError(f"media operation {job_id} does not exist; refusing orphan queue delivery")
    if operation.get("defer_before_start"):
        raise JobDeferred(f"media operation {job_id} still has a live processing lease")
    if operation.get("skip_before_start"):
        return operation.get("result") or {
            "success": operation.get("status") == "completed",
            "skipped": True,
            "status": operation.get("status"),
        }
    claimed_generation = int(operation.get('media_generation') or 0)
    if claimed_generation <= 0:
        raise RuntimeError(f"media operation {job_id} has no claimed generation")

    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _media_operation_heartbeat(job_id, claimed_generation, heartbeat_stop),
        name=f"media-heartbeat-{job_id}",
    )


    sw = get_seaweedfs()
    terminal_cleanup = False
    try:
        source_bytes, _content_type = await sw.fetch_via_filer(source_path)
        webp_data, width, height = await _convert_thumbnail_bytes(source_bytes)

        thumbnail_name = f"thumbnail-{hashlib.sha256(webp_data).hexdigest()[:24]}.webp"
        image_path = f"{series_slug}/{thumbnail_name}"
        uploaded = False

        series_id = str(operation.get("series_id") or "").strip()
        metadata = dict(operation.get("metadata") or {})
        actor_id = str(metadata.get("actor_id") or "").strip() or None
        if not series_id:
            raise RuntimeError(f"media operation {job_id} has no canonical series ID")

        await sw.upload_via_filer(image_path, webp_data, "image/webp")
        uploaded = True
        try:
            await set_catalog_series_cover(
                series_id=series_id,
                actor_id=actor_id,
                cover_image_path=image_path,
                media_generation=claimed_generation,
            )

            result = {
                "success": True,
                "image_path": image_path,
                "width": width,
                "height": height,
                "file_size": len(webp_data),
            }
            async with AsyncSessionLocal() as db:
                await complete_media_operation(
                    db,
                    operation_id=job_id,
                    series_id=series_id,
                    chapter_id=None,
                    output_paths=[image_path],
                    result=result,
                    source="thumbnail-generation",
                    expected_generation=claimed_generation,
                )
                await db.commit()
        except MediaOperationLeaseLost:
            # A replacement generation may now own the deterministic output.
            # Never delete or terminally mutate work after losing the lease.
            raise
        except Exception:
            outcome = (
                await _thumbnail_commit_outcome(
                    job_id,
                    series_slug,
                    image_path,
                    claimed_generation,
                )
                if uploaded else False
            )
            if outcome is True:
                # Catalog owns the cover even if the acknowledgement or Media
                # completion write was lost. Preserve the deterministic object
                # so recovery can reconcile the durable Media operation.
                log.warning(
                    "thumbnail Catalog acknowledgement was lost but canonical cover confirms success job=%s",
                    job_id,
                )
            else:
                if outcome is False and uploaded:
                    try:
                        await enqueue_production_output_cleanup(
                            media_operation_id=job_id,
                            media_generation=claimed_generation,
                            paths=[image_path],
                            kind="cover",
                            reason="media-uncommitted-thumbnail-output",
                            series_id=series_id,
                        )
                    except Exception:
                        log.warning(
                            "failed to enqueue confirmed-uncommitted thumbnail cleanup %s",
                            image_path,
                            exc_info=True,
                        )
                raise

        terminal_cleanup = True
        return result

    except MediaOperationLeaseLost:
        log.warning(
            "thumbnail media lease lost; preserving deterministic output/input for reconciliation job=%s generation=%s",
            job_id,
            claimed_generation,
        )
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        job_try = int(ctx.get("job_try") or 1)
        final_attempt = job_try >= MEDIA_WORKER_MAX_TRIES
        log.exception(
            "thumbnail job failed job_id=%s series_slug=%s try=%s/%s",
            job_id,
            series_slug,
            job_try,
            MEDIA_WORKER_MAX_TRIES,
        )
        if final_attempt:
            terminal_cleanup = await _mark_final_failure(
                job_id,
                error,
                "thumbnail-generation",
                claimed_generation,
            )
        else:
            await _mark_retry(job_id, error, claimed_generation)
        raise

    finally:
        await _stop_heartbeat(heartbeat_stop, heartbeat_task)
        if terminal_cleanup:
            try:
                await sw.delete_via_filer(source_path)
            except Exception:
                log.warning("failed to delete staged media source %s", source_path, exc_info=True)


async def ingest_chapter(
    ctx,
    job_id: str,
    series_slug: str,
    chapter_slug: str,
    source_path: str,
    filename: str,
    content_type: str,
    chapter_number: str,
    title: str | None,
    first_image_path: str | None = None,
    last_image_path: str | None = None,
):
    payload = {
        "series_slug": series_slug,
        "chapter_slug": chapter_slug,
        "source_path": source_path,
        "filename": filename,
        "content_type": content_type,
        "chapter_number": chapter_number,
        "title": title,
        "first_image_path": first_image_path,
        "last_image_path": last_image_path,
    }
    operation = await _start_operation(job_id)
    if operation is None:
        raise RuntimeError(f"media operation {job_id} does not exist; refusing orphan queue delivery")
    if operation.get("defer_before_start"):
        raise JobDeferred(f"media operation {job_id} still has a live processing lease")
    if operation.get("skip_before_start"):
        return operation.get("result") or {
            "success": operation.get("status") == "completed",
            "skipped": True,
            "status": operation.get("status"),
        }
    claimed_generation = int(operation.get('media_generation') or 0)
    if claimed_generation <= 0:
        raise RuntimeError(f"media operation {job_id} has no claimed generation")

    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _media_operation_heartbeat(job_id, claimed_generation, heartbeat_stop),
        name=f"media-heartbeat-{job_id}",
    )


    sw = get_seaweedfs()
    terminal_cleanup = False
    try:
        try:
            parsed_number = Decimal(chapter_number)
        except InvalidOperation as exc:
            raise ValueError("Invalid chapter_number format.") from exc
        if (
            not parsed_number.is_finite()
            or parsed_number <= 0
            or parsed_number > Decimal("999999.99")
        ):
            raise ValueError("chapter_number must be finite, greater than 0 and at most 999999.99.")

        suffix = os.path.splitext(filename or "")[1][:12]
        with tempfile.TemporaryDirectory(prefix="mreader-media-") as temp_dir:
            local_path = os.path.join(temp_dir, f"chapter{suffix}")
            staged_content_type, _staged_size = await sw.download_via_filer_to_path(
                source_path,
                local_path,
                max_bytes=LIMITS.max_upload_size_bytes,
            )
            first_image_data = None
            last_image_data = None
            if first_image_path:
                first_image_data, _ = await sw.fetch_via_filer(first_image_path)
                if len(first_image_data) > LIMITS.max_thumbnail_size_bytes:
                    raise ValueError("First boundary image exceeds configured size limit.")
            if last_image_path:
                last_image_data, _ = await sw.fetch_via_filer(last_image_path)
                if len(last_image_data) > LIMITS.max_thumbnail_size_bytes:
                    raise ValueError("Last boundary image exceeds configured size limit.")
            result = await ingest_chapter_file(
                archive_path=local_path,
                filename=filename,
                content_type=(content_type or staged_content_type or "application/octet-stream"),
                series_slug=series_slug,
                chapter_slug=chapter_slug,
                chapter_number=parsed_number,
                title=title,
                first_image_data=first_image_data,
                last_image_data=last_image_data,
                idempotent_existing=True,
                media_operation_id=job_id,
            )

        terminal_cleanup = True
        return result

    except MediaOperationLeaseLost:
        log.warning(
            "chapter media lease lost; preserving staged inputs and deterministic outputs for reconciliation job=%s generation=%s",
            job_id,
            claimed_generation,
        )
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        job_try = int(ctx.get("job_try") or 1)
        final_attempt = job_try >= MEDIA_WORKER_MAX_TRIES
        log.exception(
            "chapter ingestion job failed job_id=%s series=%s chapter=%s try=%s/%s",
            job_id,
            series_slug,
            chapter_slug,
            job_try,
            MEDIA_WORKER_MAX_TRIES,
        )
        if final_attempt:
            terminal_cleanup = await _mark_final_failure(
                job_id,
                error,
                "chapter-ingestion",
                claimed_generation,
            )
        else:
            await _mark_retry(job_id, error, claimed_generation)
        raise

    finally:
        await _stop_heartbeat(heartbeat_stop, heartbeat_task)
        if terminal_cleanup:
            for staged_path in (last_image_path, first_image_path, source_path):
                if not staged_path:
                    continue
                try:
                    await sw.delete_via_filer(staged_path)
                except Exception:
                    log.warning("failed to delete staged media input %s", staged_path, exc_info=True)


async def main() -> None:
    queue_mode = os.getenv("MEDIA_WORKER_QUEUE", "chapter").strip().lower()
    if queue_mode not in {"chapter", "thumbnail", "all"}:
        raise RuntimeError("MEDIA_WORKER_QUEUE must be chapter, thumbnail or all")

    concurrency = _bounded_int_env("MEDIA_WORKER_MAX_JOBS", 2, 1, 8)
    init_seaweedfs_client()
    broker = RabbitJobBroker(connection_name=f"mreader-media-{queue_mode}")
    await broker.connect()
    await _recover_durable_operations(broker)
    recovery_task = asyncio.create_task(
        _media_recovery_loop(broker),
        name="media-durable-recovery",
    )

    async def handle_thumbnail(payload: dict, attempt: int) -> None:
        await generate_thumbnail(
            {"job_try": attempt},
            str(payload["job_id"]),
            str(payload["series_slug"]),
            str(payload["source_path"]),
        )

    async def handle_chapter(payload: dict, attempt: int) -> None:
        await ingest_chapter(
            {"job_try": attempt},
            str(payload["job_id"]),
            str(payload["series_slug"]),
            str(payload["chapter_slug"]),
            str(payload["source_path"]),
            str(payload.get("filename") or "upload.bin"),
            str(payload.get("content_type") or "application/octet-stream"),
            str(payload.get("chapter_number") or "1.0"),
            payload.get("title"),
            str(payload.get("first_image_path") or "") or None,
            str(payload.get("last_image_path") or "") or None,
        )

    specs = []
    if queue_mode in {"thumbnail", "all"}:
        specs.append((THUMBNAIL_QUEUE, handle_thumbnail, "thumbnail"))
    if queue_mode in {"chapter", "all"}:
        specs.append((CHAPTER_QUEUE, handle_chapter, "chapter"))

    # For dedicated workers all concurrency goes to one operation class. In
    # compatibility 'all' mode each queue receives at least one consumer.
    tasks: list[asyncio.Task] = []
    for queue_name, handler, label in specs:
        count = concurrency if len(specs) == 1 else max(1, concurrency // len(specs))
        for index in range(count):
            tasks.append(asyncio.create_task(
                broker.consume_forever(
                    queue_name,
                    handler,
                    worker_name=f"media-{label}-{index + 1}",
                ),
                name=f"media-{label}-consumer-{index + 1}",
            ))

    log.info("media worker started broker=rabbitmq mode=%s concurrency=%s", queue_mode, concurrency)
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
        await broker.close()
        await close_seaweedfs_client()
        log.info("media worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
