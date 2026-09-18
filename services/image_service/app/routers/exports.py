from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

import pyvips
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import Chapter, Page, Series, get_db, get_seaweedfs, require_admin
from shared.tilepack_codec import decode_tilepack

router = APIRouter(tags=["admin-storage"])
log = logging.getLogger(__name__)


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid chapter id.") from exc


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value.strip())
    return cleaned.strip("-.") or "chapter"


@router.get("/chapters/{chapter_id}/download")
async def download_chapter_export(
    chapter_id: str,
    background_tasks: BackgroundTasks,
    mode: str = Query("stored", pattern="^(stored|decoded)$"),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Download an admin-only ZIP export of one chapter.

    stored: exact v4 tile-pack bytes as persisted in SeaweedFS.
    decoded: reconstruct v4 tile-packs into readable WebPs for admin recovery.
             This is intentionally more CPU intensive and is not reader delivery.
    """
    chapter_uuid = _parse_uuid(chapter_id)
    result = await db.execute(
        select(Chapter, Series)
        .join(Series, Series.id == Chapter.series_id)
        .where(Chapter.id == chapter_uuid)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chapter not found.")
    chapter, series = row

    pages_result = await db.execute(
        select(Page)
        .where(Page.chapter_id == chapter_uuid)
        .order_by(Page.page_number.asc())
    )
    pages = list(pages_result.scalars().all())
    if not pages:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chapter has no stored pages.")

    sw = get_seaweedfs()
    temp = tempfile.NamedTemporaryFile(
        prefix="mreader-chapter-export-", suffix=".zip", delete=False
    )
    temp_path = temp.name
    temp.close()

    manifest_pages: list[dict] = []
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for page in pages:
                try:
                    content, content_type = await sw.fetch_via_filer(page.image_path)
                except FileNotFoundError as exc:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Stored page {page.page_number} is missing from SeaweedFS.",
                    ) from exc

                export_content = content
                if int(page.encoding_version) != 4:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Page {page.page_number} is not current v4 content.",
                    )
                if mode == "decoded":
                    if not page.encoding_rows or not page.encoding_columns or not page.encoding_seed:
                        raise HTTPException(
                            status.HTTP_409_CONFLICT,
                            f"Page {page.page_number} has incomplete v4 encoding metadata.",
                        )
                    try:
                        export_content = decode_tilepack(
                            content,
                            seed=page.encoding_seed,
                            page_number=int(page.page_number),
                        )
                    except (pyvips.Error, ValueError) as exc:
                        log.warning("Could not decode admin export page %s", page.id, exc_info=True)
                        raise HTTPException(
                            status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Could not decode page {page.page_number}.",
                        ) from exc

                stored_suffix = ".mrt"
                member_suffix = ".webp" if mode == "decoded" else stored_suffix
                member_name = f"pages/{int(page.page_number):04d}{member_suffix}"
                archive.writestr(member_name, export_content)

                responsive_manifest = None
                if page.responsive_image_path:
                    try:
                        responsive_content, responsive_content_type = await sw.fetch_via_filer(
                            page.responsive_image_path
                        )
                    except FileNotFoundError as exc:
                        raise HTTPException(
                            status.HTTP_409_CONFLICT,
                            f"Responsive stored page {page.page_number} is missing from SeaweedFS.",
                        ) from exc

                    responsive_export = responsive_content
                    if mode == "decoded":
                        if not page.encoding_seed:
                            raise HTTPException(
                                status.HTTP_409_CONFLICT,
                                f"Responsive page {page.page_number} has unsupported/incomplete codec metadata.",
                            )
                        try:
                            responsive_export = decode_tilepack(
                                responsive_content,
                                seed=page.encoding_seed,
                                page_number=int(page.page_number),
                            )
                        except (pyvips.Error, ValueError) as exc:
                            log.warning(
                                "Could not decode responsive admin export page %s",
                                page.id,
                                exc_info=True,
                            )
                            raise HTTPException(
                                status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Could not decode responsive page {page.page_number}.",
                            ) from exc

                    responsive_suffix = ".webp" if mode == "decoded" else ".mrt"
                    responsive_member = (
                        f"responsive/{int(page.page_number):04d}{responsive_suffix}"
                    )
                    archive.writestr(responsive_member, responsive_export)
                    responsive_manifest = {
                        "archive_path": responsive_member,
                        "storage_path": page.responsive_image_path,
                        "stored_content_type": responsive_content_type,
                        "stored_size_bytes": len(responsive_content),
                        "export_size_bytes": len(responsive_export),
                        "width": page.responsive_width,
                        "height": page.responsive_height,
                    }

                manifest_pages.append(
                    {
                        "page_number": int(page.page_number),
                        "archive_path": member_name,
                        "storage_path": page.image_path,
                        "stored_content_type": content_type,
                        "stored_size_bytes": len(content),
                        "export_size_bytes": len(export_content),
                        "width": page.width,
                        "height": page.height,
                        "responsive": responsive_manifest,
                        "encoding_version": int(page.encoding_version),
                        "encoding_rows": page.encoding_rows,
                        "encoding_columns": page.encoding_columns,
                        # Admin backup portability requires the chapter/page seed. This
                        # endpoint is role-protected and it is never stored in the CDN.
                        "encoding_seed": page.encoding_seed,
                    }
                )

            manifest = {
                "format": "mreader-chapter-export-v1",
                "export_mode": mode,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "series": {"id": str(series.id), "slug": series.slug, "title": series.title},
                "chapter": {
                    "id": str(chapter.id),
                    "slug": chapter.slug,
                    "number": str(chapter.chapter_number),
                    "title": chapter.title,
                    "status": chapter.status,
                    "page_count": len(pages),
                },
                "codec": {
                    "note": "Fresh baseline supports v4 overlap tile-packs only.",
                    "stored_exports_preserve_encoded_bytes": mode == "stored",
                    "decoded_exports_are_readable_webp": mode == "decoded",
                },
                "pages": manifest_pages,
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            )
            archive.writestr(
                "README.txt",
                (
                    "MReader admin chapter export\n"
                    f"Mode: {mode}\n\n"
                    "stored = exact SeaweedFS page bytes, including responsive derivatives when present. Encoding metadata is in manifest.json.\n"
                    "decoded = readable WebP reconstruction for primary pages and responsive v4 derivatives.\n"
                    "Keep stored exports and their manifest private because the manifest contains decode seeds.\n"
                ).encode("utf-8"),
            )
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise

    background_tasks.add_task(os.unlink, temp_path)
    filename = (
        f"{_safe_filename(series.slug)}--{_safe_filename(chapter.slug)}--{mode}.zip"
    )
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename,
        background=background_tasks,
        headers={"Cache-Control": "private, no-store"},
    )
