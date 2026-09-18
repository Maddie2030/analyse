from dataclasses import dataclass
import os
import re
from secrets import compare_digest
import uuid

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import or_, select

from shared import AsyncSessionLocal, Chapter, Series, User, get_seaweedfs, require_admin

from app.jobs import enqueue_chapter_job, enqueue_thumbnail_job, new_job_id
from app.media_config import LIMITS
from app.observability import request_id_ctx
from app.media_operations import (
    IngestionAuthorityRequest,
    IngestionOperationAuthorityError,
    authorize_ingestion_operation,
    create_media_operation,
    get_media_operation,
    operation_api_payload,
    record_queue_error,
)
from app.media_validation import ARCHIVE_MIME_TYPES, IMAGE_MIME_TYPES, SAFE_SLUG


router = APIRouter(tags=["media-jobs"])
internal_router = APIRouter(tags=["media-jobs-internal"])


async def _record_queue_result(job_id: str, error: str | None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await record_queue_error(db, job_id, error)
            await db.commit()
    except Exception:
        # Queue diagnostics must not turn a durable accepted upload into an HTTP
        # failure. Recovery still scans the PostgreSQL queued/retry states.
        pass


async def _delete_staged_inputs(sw, *paths: str | None) -> None:
    """Best-effort exact-path cleanup for UUID-scoped, not-yet-canonical inputs."""
    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            await sw.delete_via_filer(path)
        except Exception:
            # Cleanup failure must not hide the original acceptance/staging error.
            pass


async def _submit_thumbnail_job(
    series_slug: str,
    file: UploadFile,
    *,
    actor_id: str,
) -> dict:
    if not SAFE_SLUG.fullmatch(series_slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid series slug.")

    if (
        file.content_type not in IMAGE_MIME_TYPES
        and not (file.content_type or "").startswith("image/")
    ):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Unsupported image format.",
        )

    image_data = await file.read()
    if not image_data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded thumbnail is empty.")
    if len(image_data) > LIMITS.max_thumbnail_size_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Thumbnail file is too large.",
        )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Series.id).where(Series.slug == series_slug))
        series_id = result.scalar_one_or_none()
        if series_id is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Series '{series_slug}' not found.",
            )

    job_id = new_job_id()
    source_path = f"_jobs/media/{job_id}/source"
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "thumbnail"
    payload = {
        "series_slug": series_slug,
        "source_path": source_path,
        "filename": filename,
        "content_type": content_type,
        "actor_id": actor_id,
        "request_id": request_id_ctx.get(),
        "operation_id": job_id,
    }
    sw = get_seaweedfs()

    try:
        await sw.upload_via_filer(source_path, image_data, content_type)
    except Exception as exc:
        try:
            await sw.delete_via_filer(source_path)
        except Exception:
            pass
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to stage thumbnail.",
        ) from exc

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Series.id).where(Series.slug == series_slug))
            current_series_id = result.scalar_one_or_none()
            if current_series_id is None:
                raise ValueError(f"Series '{series_slug}' no longer exists.")
            await create_media_operation(
                db,
                operation_id=job_id,
                job_type="thumbnail-generation",
                series_id=str(current_series_id),
                series_slug=series_slug,
                chapter_slug=None,
                staged_object_path=source_path,
                input_filename=filename,
                input_content_type=content_type,
                metadata=payload,
            )
            await db.commit()
    except Exception as exc:
        try:
            async with AsyncSessionLocal() as verify_db:
                canonical = await get_media_operation(verify_db, job_id)
        except Exception as verify_exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Thumbnail acceptance outcome is temporarily uncertain; staged source was preserved for recovery.",
            ) from verify_exc
        if canonical is None:
            await _delete_staged_inputs(sw, source_path)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to accept staged thumbnail.",
            ) from exc

    queue_deferred = False
    try:
        await enqueue_thumbnail_job(
            job_id=job_id,
            series_slug=series_slug,
            source_path=source_path,
        )
        await _record_queue_result(job_id, None)
    except Exception as exc:
        queue_deferred = True
        await _record_queue_result(job_id, f"{type(exc).__name__}: {exc}")

    return {
        "job_id": job_id,
        "status": "queued",
        "job_type": "thumbnail-generation",
        "durable": True,
        "queue_deferred": queue_deferred,
    }


@router.post(
    "/thumbnail/{series_slug}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_thumbnail_job(
    series_slug: str,
    file: UploadFile = File(...),
    _admin: dict = Depends(require_admin),
) -> dict:
    return await _submit_thumbnail_job(
        series_slug,
        file,
        actor_id=str(_admin["user_id"]),
    )


@internal_router.post("/thumbnail/{series_slug}", status_code=status.HTTP_202_ACCEPTED)
async def internal_submit_thumbnail_job(
    series_slug: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    return await _submit_thumbnail_job(
        series_slug,
        file,
        actor_id=await _require_internal_actor(request),
    )


async def _require_internal_actor(request: Request) -> str:
    expected = os.getenv("MEDIA_INTERNAL_TOKEN", "").strip()
    provided = (request.headers.get("X-MReader-Internal-Token") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Media internal transport is not configured.")
    if not provided or not compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal workload credential.")
    raw = (request.headers.get("X-MReader-Requesting-Actor-ID") or "").strip()
    try:
        actor_id = uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid requesting actor.") from exc
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.id).where(
                User.id == actor_id,
                User.is_active.is_(True),
                User.role == "admin",
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Requesting actor is not an active admin.")
    return str(actor_id)


async def _media_job_status(job_id: str, *, actor_id: str | None = None) -> dict:
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        job_id,
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid job ID.")

    async with AsyncSessionLocal() as db:
        operation = await get_media_operation(db, job_id)
    if operation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media job not found.")
    if actor_id is not None:
        metadata = dict(operation.get("metadata") or {})
        if str(metadata.get("actor_id") or "") != actor_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Media job not found.")
    return operation_api_payload(operation)


@router.get("/{job_id}")
async def media_job_status(
    job_id: str,
    _admin: dict = Depends(require_admin),
) -> dict:
    return await _media_job_status(job_id)


@internal_router.get("/{job_id}")
async def internal_media_job_status(job_id: str, request: Request) -> dict:
    return await _media_job_status(job_id, actor_id=await _require_internal_actor(request))


@dataclass(frozen=True)
class ChapterAcceptanceAuthority:
    actor_id: str
    expected_source_kind: str | None
    create_ingestion_header: bool


@dataclass(frozen=True)
class ChapterJobInput:
    file: UploadFile
    chapter_number: str
    title: str | None
    source_kind: str | None
    ingestion_operation_id: str | None
    media_operation_id: str | None
    source_revision: int
    ingestion_generation: int
    chapter_id: str | None
    expected_revision: int
    first_image: UploadFile | None
    last_image: UploadFile | None


async def _chapter_job_input(request: Request) -> ChapterJobInput:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "file"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chapter archive is required.")

    def text_value(name: str, default: str | None = None) -> str | None:
        value = form.get(name)
        if value is None:
            return default
        return str(value)

    def int_value(name: str, default: int) -> int:
        try:
            return int(text_value(name, str(default)) or default)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid {name}.") from exc

    first_image = form.get("first_image")
    last_image = form.get("last_image")
    return ChapterJobInput(
        file=upload,  # type: ignore[arg-type]
        chapter_number=text_value("chapter_number", "1.0") or "1.0",
        title=text_value("title"),
        source_kind=text_value("source_kind"),
        ingestion_operation_id=text_value("ingestion_operation_id"),
        media_operation_id=text_value("media_operation_id"),
        source_revision=int_value("source_revision", 1),
        ingestion_generation=int_value("ingestion_generation", 1),
        chapter_id=text_value("chapter_id"),
        expected_revision=int_value("expected_revision", 0),
        first_image=first_image if hasattr(first_image, "file") else None,  # type: ignore[arg-type]
        last_image=last_image if hasattr(last_image, "file") else None,  # type: ignore[arg-type]
    )


async def _submit_chapter_job(
    series_slug: str,
    chapter_slug: str,
    request: Request,
    *,
    authority: ChapterAcceptanceAuthority,
) -> dict:
    job_input = await _chapter_job_input(request)
    file = job_input.file
    chapter_number = job_input.chapter_number
    title = job_input.title
    actor_id = authority.actor_id
    source_kind = authority.expected_source_kind or job_input.source_kind
    ingestion_operation_id = job_input.ingestion_operation_id
    media_operation_id = job_input.media_operation_id
    source_revision = job_input.source_revision
    ingestion_generation = job_input.ingestion_generation
    chapter_id = job_input.chapter_id
    expected_revision = job_input.expected_revision
    first_image = job_input.first_image
    last_image = job_input.last_image
    if not SAFE_SLUG.fullmatch(series_slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid series slug.")
    if not SAFE_SLUG.fullmatch(chapter_slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid chapter slug.")

    def _uuid_form(value: str | None, label: str) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return str(uuid.UUID(value.strip()))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {label}.") from exc

    ingestion_operation_id = _uuid_form(ingestion_operation_id, "ingestion_operation_id")
    media_operation_id = _uuid_form(media_operation_id, "media_operation_id")
    chapter_id = _uuid_form(chapter_id, "chapter_id")
    if source_revision < 1 or ingestion_generation < 1 or expected_revision < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid publication revision/fence values.")
    if not source_kind:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Internal chapter ingestion requires source_kind.")
    if not authority.create_ingestion_header and ingestion_operation_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Internal chapter ingestion requires ingestion_operation_id.")

    filename = file.filename or "upload.bin"
    file_ext = Path(filename).suffix.lower()
    if (
        file.content_type not in ARCHIVE_MIME_TYPES
        and file_ext not in {".zip", ".cbz", ".pdf"}
    ):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only ZIP, CBZ archives, or PDF files are accepted.",
        )

    try:
        parsed_number = Decimal(chapter_number)
    except InvalidOperation:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid chapter_number format.")
    if (
        not parsed_number.is_finite()
        or parsed_number <= 0
        or parsed_number > Decimal("999999.99")
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "chapter_number must be finite, greater than 0 and at most 999999.99.",
        )

    async with AsyncSessionLocal() as db:
        series_result = await db.execute(select(Series).where(Series.slug == series_slug))
        series = series_result.scalar_one_or_none()
        if series is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Series '{series_slug}' not found.",
            )
        series_id = str(series.id)
        existing_result = await db.execute(
            select(Chapter).where(
                Chapter.series_id == series.id,
                or_(
                    Chapter.slug == chapter_slug,
                    Chapter.chapter_number == parsed_number,
                ),
            )
        )
        existing = existing_result.scalars().first()
        if existing is not None and str(existing.id) != str(chapter_id or ""):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This chapter already exists. Choose a new chapter number and slug.",
            )

    # Starlette spools large UploadFile bodies to disk. Do not materialize a
    # second full archive in Python RAM.
    try:
        await file.seek(0)
        file.file.seek(0, 2)
        upload_size = int(file.file.tell())
        file.file.seek(0)
    except (AttributeError, OSError, ValueError):
        upload_size = int(file.size or 0)
        await file.seek(0)

    if upload_size <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if upload_size > LIMITS.max_upload_size_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large.")

    async def _read_boundary(upload: UploadFile | None, label: str) -> tuple[bytes | None, str | None]:
        if upload is None:
            return None, None
        if upload.content_type not in IMAGE_MIME_TYPES and not (upload.content_type or "").startswith("image/"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported {label} image format.")
        data = await upload.read()
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label.capitalize()} image is empty.")
        if len(data) > LIMITS.max_thumbnail_size_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{label.capitalize()} image is too large.")
        return data, upload.content_type or "application/octet-stream"

    first_image_data, first_image_type = await _read_boundary(first_image, "first")
    last_image_data, last_image_type = await _read_boundary(last_image, "last")

    job_id = media_operation_id or new_job_id()
    publication_operation_id = ingestion_operation_id or job_id
    source_path = f"_jobs/media/{job_id}/archive"
    first_image_path = f"_jobs/media/{job_id}/first-image" if first_image_data else None
    last_image_path = f"_jobs/media/{job_id}/last-image" if last_image_data else None
    content_type = file.content_type or "application/octet-stream"
    payload = {
        "series_slug": series_slug,
        "chapter_slug": chapter_slug,
        "actor_id": actor_id,
        "source_kind": source_kind,
        "operation_id": publication_operation_id,
        "idempotency_key": publication_operation_id,
        "source_revision": int(source_revision),
        "ingestion_generation": int(ingestion_generation),
        "chapter_id": chapter_id,
        "expected_revision": int(expected_revision),
        "request_id": request_id_ctx.get(),
        "source_path": source_path,
        "filename": filename,
        "content_type": content_type,
        "chapter_number": str(parsed_number),
        "title": title,
        "first_image_path": first_image_path,
        "first_image_content_type": first_image_type,
        "last_image_path": last_image_path,
        "last_image_content_type": last_image_type,
    }
    sw = get_seaweedfs()

    try:
        await sw.upload_file_via_filer(
            source_path,
            file.file,
            content_type,
            filename=filename,
        )
        if first_image_path and first_image_data:
            await sw.upload_via_filer(first_image_path, first_image_data, first_image_type or "application/octet-stream")
        if last_image_path and last_image_data:
            await sw.upload_via_filer(last_image_path, last_image_data, last_image_type or "application/octet-stream")
    except Exception as exc:
        # As above, this UUID-scoped source path is not canonical until the
        # media_operations transaction commits. Clean only this exact object
        # to cover the "PUT succeeded, acknowledgement was lost" case.
        await _delete_staged_inputs(sw, last_image_path, first_image_path, source_path)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to stage chapter archive.",
        ) from exc

    try:
        async with AsyncSessionLocal() as db:
            current_series = await db.execute(select(Series.id).where(Series.slug == series_slug))
            current_series_id = current_series.scalar_one_or_none()
            if current_series_id is None:
                raise ValueError(f"Series '{series_slug}' no longer exists.")

            existing_result = await db.execute(
                select(Chapter.id).where(
                    Chapter.series_id == current_series_id,
                    or_(
                        Chapter.slug == chapter_slug,
                        Chapter.chapter_number == parsed_number,
                    ),
                )
            )
            existing_id = existing_result.scalar_one_or_none()
            if existing_id is not None and str(existing_id) != str(chapter_id or ""):
                raise FileExistsError("This chapter already exists.")

            await authorize_ingestion_operation(
                db,
                IngestionAuthorityRequest(
                    operation_id=publication_operation_id,
                    source_kind=source_kind,
                    actor_id=actor_id,
                    source_revision=source_revision,
                    lease_generation=ingestion_generation,
                ),
                create_ingestion_header=authority.create_ingestion_header,
            )
            await create_media_operation(
                db,
                operation_id=job_id,
                job_type="chapter-ingestion",
                series_id=str(current_series_id),
                series_slug=series_slug,
                chapter_slug=chapter_slug,
                staged_object_path=source_path,
                staged_object_paths=[
                    path for path in (source_path, first_image_path, last_image_path) if path
                ],
                input_filename=filename,
                input_content_type=content_type,
                metadata=payload,
            )
            await db.commit()
    except IngestionOperationAuthorityError as exc:
        await _delete_staged_inputs(sw, last_image_path, first_image_path, source_path)
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except FileExistsError as exc:
        # This conflict is known to have occurred before media_operations was
        # committed, so the staged archive is not canonical and may be removed.
        await _delete_staged_inputs(sw, last_image_path, first_image_path, source_path)
        raise HTTPException(status.HTTP_409_CONFLICT, "This chapter already exists.") from exc
    except Exception as exc:
        # A network error while PostgreSQL reports COMMIT is ambiguous. Never
        # delete the only durable source archive until canonical DB state proves
        # the acceptance transaction did not commit. This mirrors the thumbnail
        # acceptance path and prevents a successful-but-unacknowledged commit
        # from becoming an unrecoverable media job.
        try:
            async with AsyncSessionLocal() as verify_db:
                canonical = await get_media_operation(verify_db, job_id)
        except Exception as verify_exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Chapter upload acceptance outcome is temporarily uncertain; staged archive was preserved for recovery.",
            ) from verify_exc
        if canonical is None:
            await _delete_staged_inputs(sw, last_image_path, first_image_path, source_path)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to accept staged chapter archive.",
            ) from exc
        # Canonical media_operations row exists: COMMIT succeeded even if its
        # acknowledgement was lost. Continue to cache/queue dispatch.

    queue_deferred = False
    try:
        await enqueue_chapter_job(
            job_id=job_id,
            series_slug=series_slug,
            chapter_slug=chapter_slug,
            source_path=source_path,
            filename=filename,
            content_type=content_type,
            chapter_number=str(parsed_number),
            title=title,
            first_image_path=first_image_path,
            last_image_path=last_image_path,
        )
        await _record_queue_result(job_id, None)
    except Exception as exc:
        queue_deferred = True
        await _record_queue_result(job_id, f"{type(exc).__name__}: {exc}")

    return {
        "job_id": job_id,
        "status": "queued",
        "job_type": "chapter-ingestion",
        "durable": True,
        "queue_deferred": queue_deferred,
    }


@router.post(
    "/chapter/{series_slug}/{chapter_slug}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_chapter_job(
    series_slug: str,
    chapter_slug: str,
    request: Request,
    _admin: dict = Depends(require_admin),
) -> dict:
    return await _submit_chapter_job(
        series_slug,
        chapter_slug,
        request,
        authority=ChapterAcceptanceAuthority(
            actor_id=str(_admin["user_id"]),
            expected_source_kind="manual-upload",
            create_ingestion_header=True,
        ),
    )


@internal_router.post(
    "/chapter/{series_slug}/{chapter_slug}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def internal_submit_chapter_job(
    series_slug: str,
    chapter_slug: str,
    request: Request,
) -> dict:
    return await _submit_chapter_job(
        series_slug,
        chapter_slug,
        request,
        authority=ChapterAcceptanceAuthority(
            actor_id=await _require_internal_actor(request),
            expected_source_kind=None,
            create_ingestion_header=False,
        ),
    )
