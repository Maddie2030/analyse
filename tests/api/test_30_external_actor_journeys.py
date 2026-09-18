from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path

import pytest
import requests

from helpers import assert_status, wait_media_job


pytestmark = pytest.mark.external


def _required_input(name: str, description: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not set; provide {description} to ./diagnose-mreader.sh")
    return value


def _expect_status(journey, action, response, expected, intended):
    allowed = {expected} if isinstance(expected, int) else set(expected)
    journey.assert_true(action, response.status_code in allowed, intended=intended, observed={"status": response.status_code, "body": response.text[:300]})


def _cleanup_series_draft(db, draft_id: str) -> None:
    with db.cursor() as cur:
        cur.execute("DELETE FROM scraper_series_draft_chapters WHERE draft_id=%s::uuid", (draft_id,))
        cur.execute("DELETE FROM scraper_series_drafts WHERE id=%s::uuid", (draft_id,))


def _cleanup_existing_draft(db, draft_id: str) -> None:
    filer = os.getenv("TEST_SEAWEEDFS_FILER_URL", "").rstrip("/")
    if filer:
        try:
            requests.delete(f"{filer}/_scraper/staging/{draft_id}", params={"recursive": "true"}, timeout=15)
        except Exception:
            pass
    with db.cursor() as cur:
        cur.execute("DELETE FROM scraper_drafts WHERE id=%s::uuid", (draft_id,))


@pytest.mark.journey
@pytest.mark.write
def test_supplied_scraper_series_url_discovers_real_series(admin_user, db, journey):
    source_url = _required_input("MREADER_DIAGNOSTICS_SERIES_URL", "--scraper-series-url URL")
    draft_id = None
    try:
        response = admin_user.session.post("/api/scraper/series-drafts/discover", json={"url": source_url}, timeout=180)
        _expect_status(journey, "scraper-discover-real-series", response, 200, "admin can discover a real external series URL")
        body = response.json()
        draft_id = body.get("id")
        journey.assert_true("scraper-real-series-title", bool(body.get("title")), intended="real scraper discovery returns a series title", observed={"title": body.get("title"), "source_url": source_url})
        journey.assert_true("scraper-real-series-chapters", bool(body.get("chapters")), intended="real scraper discovery returns chapter candidates", observed={"chapter_count": len(body.get("chapters") or [])})
    finally:
        if draft_id:
            _cleanup_series_draft(db, draft_id)


@pytest.mark.journey
@pytest.mark.write
def test_supplied_scraper_chapter_url_stages_real_pages(admin_user, seed_content, db, journey):
    source_url = _required_input("MREADER_DIAGNOSTICS_CHAPTER_URL", "--scraper-chapter-url URL")
    draft_id = None
    try:
        response = admin_user.session.post(
            "/api/scraper/drafts/chapter",
            json={"series_id": seed_content["series_id"], "chapter_url": source_url},
            timeout=180,
        )
        _expect_status(journey, "scraper-stage-real-chapter", response, 200, "admin can scrape and stage a real external chapter URL")
        body = response.json()
        draft_id = body.get("id")
        journey.assert_true("scraper-real-chapter-pages", bool(body.get("pages")), intended="real chapter scrape downloads at least one editable page", observed={"page_count": len(body.get("pages") or []), "source_url": source_url})
        summary=(body.get("chapter_data") or {}).get("scrape_summary") or {}
        journey.assert_true("scraper-real-chapter-stage-count", int(summary.get("staged_count") or len(body.get("pages") or [])) > 0, intended="at least one discovered page is staged successfully", observed=summary)
    finally:
        if draft_id:
            _cleanup_existing_draft(db, draft_id)


@pytest.mark.journey
@pytest.mark.worker
@pytest.mark.write
def test_supplied_chapter_file_publishes_and_reads(admin_user, anonymous, journey):
    fixture_path = Path(_required_input("MREADER_DIAGNOSTICS_CHAPTER_FILE", "--chapter-file PATH_TO_ZIP_CBZ_OR_PDF"))
    filename = os.getenv("MREADER_DIAGNOSTICS_CHAPTER_FILENAME") or fixture_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-file-{suffix}"
    series_id = None
    try:
        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor File {suffix}", "slug": slug, "description": "User-supplied chapter fixture", "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR-FIXTURE"]},
            timeout=15,
        )
        _expect_status(journey, "fixture-create-series", created, 201, "admin can create a disposable series for the supplied chapter file")
        series_id = created.json()["id"]
        with fixture_path.open("rb") as handle:
            queued = admin_user.session.post(
                f"/api/upload/jobs/chapter/{slug}/ch-1",
                files={"file": (filename, handle, content_type)},
                data={"chapter_number": "1", "title": "Supplied fixture chapter"},
                timeout=90,
            )
        _expect_status(journey, "fixture-upload-chapter", queued, 202, "supplied ZIP/CBZ/PDF is accepted for chapter processing")
        terminal = wait_media_job(admin_user.session, queued.json()["job_id"], timeout=300)
        journey.assert_equal("fixture-processing-completes", terminal.get("status"), "completed", intended="supplied chapter file is decoded, processed and published")

        manifest = anonymous.get(f"/api/reader/{slug}/ch-1", timeout=30)
        _expect_status(journey, "fixture-chapter-readable", manifest, 200, "chapter created from the supplied file is readable")
        body = manifest.json()
        journey.assert_true("fixture-pages-present", body.get("page_count", 0) > 0, intended="processed fixture exposes at least one reader page", observed={"page_count": body.get("page_count")})
        page = body["pages"][0]
        image = anonymous.get(f"/images/{page['image_path']}", params={"token": body["chapter_token"]}, timeout=30)
        _expect_status(journey, "fixture-page-streams", image, 200, "first processed page streams through the protected image path")
    finally:
        if series_id:
            deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=30)
            if deleted.status_code not in {204, 404}:
                assert_status(deleted, 204)


@pytest.mark.journey
@pytest.mark.worker
@pytest.mark.write
def test_supplied_cover_image_is_processed_and_visible(admin_user, anonymous, journey):
    fixture_path = Path(_required_input("MREADER_DIAGNOSTICS_COVER_IMAGE", "--cover-image PATH_TO_IMAGE"))
    filename = os.getenv("MREADER_DIAGNOSTICS_COVER_FILENAME") or fixture_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-cover-{suffix}"
    series_id = None
    try:
        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor Cover {suffix}", "slug": slug, "description": "User-supplied cover fixture", "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR-FIXTURE"]},
            timeout=15,
        )
        _expect_status(journey, "cover-create-series", created, 201, "admin can create a disposable series for the supplied cover image")
        series_id = created.json()["id"]
        with fixture_path.open("rb") as handle:
            queued = admin_user.session.post(
                f"/api/upload/jobs/thumbnail/{slug}",
                files={"file": (filename, handle, content_type)},
                timeout=60,
            )
        _expect_status(journey, "cover-upload", queued, 202, "supplied cover image is accepted for thumbnail processing")
        terminal = wait_media_job(admin_user.session, queued.json()["job_id"], timeout=180)
        journey.assert_equal("cover-processing-completes", terminal.get("status"), "completed", intended="cover image processing completes")

        detail = anonymous.get(f"/api/catalog/series/{slug}", timeout=20)
        _expect_status(journey, "cover-visible-series", detail, 200, "series with processed cover remains public")
        journey.assert_true("cover-path-persisted", bool(detail.json().get("cover_image_path")), intended="processed cover path is persisted on the public series", observed={"cover_image_path": detail.json().get("cover_image_path")})
    finally:
        if series_id:
            deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=30)
            if deleted.status_code not in {204, 404}:
                assert_status(deleted, 204)
