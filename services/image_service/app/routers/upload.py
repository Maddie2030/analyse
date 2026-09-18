import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from shared import AsyncSessionLocal, Series, require_admin
from shared.lifecycle import enqueue_cleanup_job
from app.catalog_series import set_catalog_series_cover
from app.media_validation import ARCHIVE_MIME_TYPES, SAFE_SLUG, THUMBNAIL_NAME
from app.routers.jobs import _submit_thumbnail_job

router = APIRouter(tags=["upload"])
log = logging.getLogger(__name__)


def _validate_slug(value: str, field_name: str) -> None:
    if not SAFE_SLUG.fullmatch(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {field_name}.")


@router.delete("/{series_slug}/{chapter_slug}", status_code=status.HTTP_409_CONFLICT)
async def delete_chapter_files(
    series_slug: str,
    chapter_slug: str,
    _admin: dict = Depends(require_admin),
) -> None:
    _validate_slug(series_slug, "series slug")
    _validate_slug(chapter_slug, "chapter slug")
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Chapter storage is lifecycle-managed. Delete the chapter through the "
        "Catalog/admin chapter endpoint so database metadata, SeaweedFS, Redis "
        "and CDN/cache state are cleaned together.",
    )


@router.post("/series/{series_slug}/thumbnail", status_code=status.HTTP_202_ACCEPTED)
async def upload_series_thumbnail(
    series_slug: str,
    _admin: dict = Depends(require_admin),
    file: UploadFile = File(...),
) -> dict:
    """Compatibility alias for the one durable Media thumbnail command."""
    _validate_slug(series_slug, "series slug")
    return await _submit_thumbnail_job(
        series_slug,
        file,
        actor_id=str(_admin["user_id"]),
    )


@router.delete("/series/{series_slug}/thumbnail/{thumbnail_name}", status_code=status.HTTP_202_ACCEPTED)
async def delete_series_thumbnail(
    series_slug: str,
    thumbnail_name: str,
    _admin: dict = Depends(require_admin),
) -> dict:
    if not SAFE_SLUG.fullmatch(series_slug) or not THUMBNAIL_NAME.fullmatch(thumbnail_name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid thumbnail path.")

    image_path = f"{series_slug}/{thumbnail_name}"
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Series).where(Series.slug == series_slug))
        series = result.scalar_one_or_none()
    if series is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Series '{series_slug}' not found.")

    if str(series.cover_image_path or "") == image_path:
        await set_catalog_series_cover(
            series_id=str(series.id),
            actor_id=str(_admin["user_id"]),
            cover_image_path=None,
            media_generation=0,
        )
        return {"status": "queued", "cleanup_job_id": None}

    async with AsyncSessionLocal() as db:
        job_id = await enqueue_cleanup_job(
            db,
            entity_type="series_cover",
            entity_id=series.id,
            payload={
                "series_id": str(series.id),
                "series_slug": series.slug,
                "image_paths": [image_path],
            },
        )
        await db.commit()
    return {"status": "queued", "cleanup_job_id": job_id}


