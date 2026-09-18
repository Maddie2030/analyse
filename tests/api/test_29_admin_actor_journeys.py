from __future__ import annotations

import uuid

import pytest

from helpers import assert_status, wait_media_job, wait_series_draft_terminal, zip_image_chapter



def _expect_status(journey, action, response, expected, intended):
    allowed = {expected} if isinstance(expected, int) else set(expected)
    journey.assert_true(action, response.status_code in allowed, intended=intended, observed={"status": response.status_code, "body": response.text[:300]})


@pytest.mark.journey
@pytest.mark.write
def test_admin_catalog_metadata_status_tags_journey(admin_user, anonymous, journey):
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-admin-{suffix}"
    series_id = None
    try:
        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor Admin {suffix}", "slug": slug, "description": "Admin actor journey", "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR", "DIAGNOSTICS"]},
            timeout=15,
        )
        _expect_status(journey, "admin-create-series", created, 201, "admin can create a new series")
        series_id = created.json()["id"]

        public = anonymous.get(f"/api/catalog/series/{slug}", timeout=10)
        _expect_status(journey, "public-sees-created-series", public, 200, "new admin-created series is visible on the user plane")
        journey.assert_equal("created-series-id", public.json().get("id"), series_id, intended="public catalog resolves the newly created series")

        updated = admin_user.session.put(
            f"/api/catalog/series/{series_id}",
            json={"title": f"Actor Admin Updated {suffix}", "status": "hiatus", "genre_ids": [], "tag_names": ["ACTOR", "UPDATED"]},
            timeout=15,
        )
        _expect_status(journey, "admin-update-series", updated, 200, "admin can edit title, status and tags")
        journey.assert_equal("admin-status-change", updated.json().get("status"), "hiatus", intended="series status changes to hiatus")

        visible = anonymous.get(f"/api/catalog/series/{slug}", timeout=10)
        _expect_status(journey, "public-sees-updated-series", visible, 200, "catalog cache invalidates after admin edit")
        body = visible.json()
        journey.assert_equal("public-status-updated", body.get("status"), "hiatus", intended="updated series status is visible publicly")
        journey.assert_true(
            "public-tags-updated",
            {str(tag.get("name", "")).upper() for tag in body.get("tags", [])} >= {"ACTOR", "UPDATED"},
            intended="updated series tags are visible publicly",
            observed=body.get("tags"),
        )
    finally:
        if series_id:
            deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
            if deleted.status_code not in {204, 404}:
                assert_status(deleted, 204)


@pytest.mark.journey
@pytest.mark.worker
@pytest.mark.write
def test_admin_media_publish_reader_delete_journey(admin_user, anonymous, image_bytes, journey):
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-media-{suffix}"
    series_id = None
    chapter_id = None
    try:
        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor Media {suffix}", "slug": slug, "description": "Media actor journey", "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR"]},
            timeout=15,
        )
        _expect_status(journey, "admin-create-media-series", created, 201, "admin can create a series for media publication")
        series_id = created.json()["id"]

        archive = zip_image_chapter(image_bytes)
        queued = admin_user.session.post(
            f"/api/upload/jobs/chapter/{slug}/ch-1",
            files={"file": ("chapter.zip", archive, "application/zip")},
            data={"chapter_number": "1", "title": "Actor Chapter"},
            timeout=30,
        )
        _expect_status(journey, "admin-upload-chapter", queued, 202, "admin can submit a chapter archive for processing")
        terminal = wait_media_job(admin_user.session, queued.json()["job_id"], timeout=180)
        journey.assert_equal("chapter-processing-completes", terminal.get("status"), "completed", intended="chapter media job completes")
        chapter_id = (terminal.get("result") or {}).get("chapter_id")
        journey.assert_true("published-chapter-id", bool(chapter_id), intended="completed media job returns the published chapter id", observed=terminal.get("result"))

        manifest = anonymous.get(f"/api/reader/{slug}/ch-1", timeout=20)
        _expect_status(journey, "published-chapter-readable", manifest, 200, "newly published chapter is readable on the user plane")
        mbody = manifest.json()
        journey.assert_true("published-pages-readable", len(mbody.get("pages", [])) >= 2, intended="published chapter exposes processed pages", observed={"page_count": mbody.get("page_count")})
        first = mbody["pages"][0]
        image = anonymous.get(f"/images/{first['image_path']}", params={"token": mbody["chapter_token"]}, timeout=20)
        _expect_status(journey, "published-page-streams", image, 200, "reader token streams a page from the newly published chapter")

        deleted_chapter = admin_user.session.delete(f"/api/catalog/series/{series_id}/chapters/{chapter_id}", timeout=20)
        _expect_status(journey, "admin-delete-chapter", deleted_chapter, 204, "admin can delete the published chapter through lifecycle ownership")
        chapter_id = None
        missing = anonymous.get(f"/api/reader/{slug}/ch-1", timeout=10)
        _expect_status(journey, "deleted-chapter-disappears", missing, 404, "deleted chapter is no longer readable")
    finally:
        if chapter_id and series_id:
            admin_user.session.delete(f"/api/catalog/series/{series_id}/chapters/{chapter_id}", timeout=20)
        if series_id:
            deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
            if deleted.status_code not in {204, 404}:
                assert_status(deleted, 204)


@pytest.mark.journey
@pytest.mark.worker
@pytest.mark.write
def test_admin_scraper_stage_publish_journey(admin_user, seeded_series_draft, image_bytes, journey):
    draft_id = seeded_series_draft["draft_id"]
    chapter_id = seeded_series_draft["chapter_id"]
    slug = seeded_series_draft["slug"]

    opened = admin_user.session.get(f"/api/scraper/series-drafts/{draft_id}", timeout=10)
    _expect_status(journey, "admin-open-scraper-draft", opened, 200, "admin can open a staged series draft")

    for number in (1, 2):
        uploaded = admin_user.session.post(
            f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/upload",
            files={"file": (f"{number:03d}.png", image_bytes, "image/png")},
            timeout=30,
        )
        _expect_status(journey, f"admin-upload-draft-page-{number}", uploaded, 200, "admin can add pages to a staged chapter")

    publish = admin_user.session.post(f"/api/scraper/series-drafts/{draft_id}/publish", timeout=20)
    _expect_status(journey, "admin-publish-scraper-draft", publish, 200, "admin can publish the prepared series draft")

    result = wait_series_draft_terminal(admin_user.session, draft_id, timeout=120)
    journey.assert_equal("scraper-publication-completes", result.get("workflow_status"), "published", intended="scraper draft reaches the published state")

    catalog = admin_user.session.get(f"/api/catalog/series/{slug}", timeout=20)
    _expect_status(journey, "published-draft-enters-catalog", catalog, 200, "published draft appears in Catalog")
    reader = admin_user.session.get(f"/api/reader/{slug}/ch-1", timeout=20)
    _expect_status(journey, "published-draft-readable", reader, 200, "published scraper chapter is immediately readable")
    journey.assert_true("published-draft-pages", reader.json().get("page_count", 0) >= 2, intended="published scraper chapter retains its pages", observed={"page_count": reader.json().get("page_count")})


@pytest.mark.journey
@pytest.mark.write
def test_admin_curation_stats_and_safe_database_status_journey(admin_user, anonymous, journey):
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-curation-{suffix}"
    series_id = None
    pick_id = None
    announcement_id = None
    try:
        auth_stats = admin_user.session.get("/api/auth/admin/stats", timeout=10)
        _expect_status(journey, "admin-auth-stats", auth_stats, 200, "admin can inspect authentication/user statistics")
        journey.assert_true("admin-auth-user-count", auth_stats.json().get("user_count", 0) >= 1, intended="admin auth statistics expose a non-zero user count", observed=auth_stats.json())

        catalog_stats = admin_user.session.get("/api/catalog/admin/stats", timeout=10)
        _expect_status(journey, "admin-catalog-stats", catalog_stats, 200, "admin can inspect catalog statistics")
        journey.assert_true("admin-catalog-stats-shape", isinstance(catalog_stats.json(), dict), intended="catalog statistics return a structured object", observed=catalog_stats.json())

        notification_stats = admin_user.session.get("/api/notifications/admin/stats", timeout=10)
        _expect_status(journey, "admin-notification-stats", notification_stats, 200, "admin can inspect notification statistics")

        database_status = admin_user.session.get("/api/admin/database", timeout=15)
        _expect_status(journey, "admin-database-status", database_status, 200, "admin can inspect database-protection status without mutating recovery state")
        db_body = database_status.json()
        journey.assert_true(
            "admin-database-status-safe-shape",
            set(("storage", "runtime", "policy", "operations", "backups")).issubset(db_body),
            intended="database status exposes browser-safe recovery state",
            observed={"keys": sorted(db_body.keys())},
        )

        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor Curation {suffix}", "slug": slug, "description": "Curation actor journey", "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR"]},
            timeout=15,
        )
        _expect_status(journey, "curation-create-series", created, 201, "admin can create a disposable series for curation")
        series_id = created.json()["id"]

        pick = admin_user.session.post(
            "/api/catalog/admin/editor-picks",
            json={"series_id": series_id, "label": "Actor pick", "note": "diagnostic curation", "position": 0, "is_active": True, "starts_at": None, "ends_at": None},
            timeout=10,
        )
        _expect_status(journey, "admin-create-editor-pick", pick, 201, "admin can add a series to editor picks")
        pick_id = pick.json()["id"]

        public_curation = anonymous.get("/api/catalog/curation", timeout=10)
        _expect_status(journey, "public-curation-after-pick", public_curation, 200, "user-plane curation is readable after an admin change")
        journey.assert_true("editor-pick-visible", any(row.get("id") == pick_id for row in public_curation.json().get("editor_picks", [])), intended="new editor pick becomes visible publicly", observed=public_curation.json())

        disabled = admin_user.session.put(
            f"/api/catalog/admin/editor-picks/{pick_id}",
            json={"series_id": series_id, "label": "Actor pick", "note": "disabled", "position": 0, "is_active": False, "starts_at": None, "ends_at": None},
            timeout=10,
        )
        _expect_status(journey, "admin-disable-editor-pick", disabled, 200, "admin can disable an editor pick")
        hidden = anonymous.get("/api/catalog/curation", timeout=10)
        _expect_status(journey, "public-curation-after-disable", hidden, 200, "curation cache refreshes after disabling a pick")
        journey.assert_true("disabled-pick-hidden", all(row.get("id") != pick_id for row in hidden.json().get("editor_picks", [])), intended="disabled editor pick disappears from public curation", observed=hidden.json())

        announcement = admin_user.session.post(
            "/api/catalog/admin/announcements",
            json={"title": f"Actor announcement {suffix}", "body": "diagnostic announcement", "link_url": None, "link_label": None, "tone": "info", "dismissible": True, "position": 0, "is_active": True, "starts_at": None, "ends_at": None},
            timeout=10,
        )
        _expect_status(journey, "admin-create-announcement", announcement, 201, "admin can publish a catalog announcement")
        announcement_id = announcement.json()["id"]

        public_announcement = anonymous.get("/api/catalog/curation", timeout=10)
        _expect_status(journey, "public-curation-announcement", public_announcement, 200, "active announcement becomes visible publicly")
        journey.assert_true("announcement-visible", any(row.get("id") == announcement_id for row in public_announcement.json().get("announcements", [])), intended="new announcement appears in public curation", observed=public_announcement.json())

        changed = admin_user.session.put(
            f"/api/catalog/admin/announcements/{announcement_id}",
            json={"title": f"Actor announcement {suffix}", "body": "updated diagnostic announcement", "link_url": None, "link_label": None, "tone": "warning", "dismissible": False, "position": 0, "is_active": True, "starts_at": None, "ends_at": None},
            timeout=10,
        )
        _expect_status(journey, "admin-update-announcement", changed, 200, "admin can edit an announcement")
        journey.assert_true("announcement-update-persisted", changed.json().get("dismissible") is False and changed.json().get("body") == "updated diagnostic announcement", intended="announcement edits persist", observed=changed.json())
    finally:
        if announcement_id:
            response = admin_user.session.delete(f"/api/catalog/admin/announcements/{announcement_id}", timeout=10)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)
        if pick_id:
            response = admin_user.session.delete(f"/api/catalog/admin/editor-picks/{pick_id}", timeout=10)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)
        if series_id:
            response = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)


@pytest.mark.journey
@pytest.mark.write
def test_admin_draft_chapter_metadata_journey(admin_user, journey):
    suffix = uuid.uuid4().hex[:8]
    slug = f"actor-draft-{suffix}"
    series_id = None
    chapter_id = None
    try:
        created = admin_user.session.post(
            "/api/catalog/series",
            json={"title": f"Actor Draft {suffix}", "slug": slug, "status": "ongoing", "genre_ids": [], "tag_names": ["ACTOR"]},
            timeout=15,
        )
        _expect_status(journey, "draft-create-series", created, 201, "admin can create a series for manual chapter administration")
        series_id = created.json()["id"]

        chapter = admin_user.session.post(
            f"/api/catalog/series/{series_id}/chapters",
            json={"chapter_number": 1, "title": "Draft chapter", "slug": "ch-1", "status": "draft"},
            timeout=15,
        )
        _expect_status(journey, "admin-create-draft-chapter", chapter, 201, "admin can create a draft chapter")
        chapter_id = chapter.json()["id"]

        updated = admin_user.session.put(
            f"/api/catalog/series/{series_id}/chapters/{chapter_id}",
            json={"chapter_number": 1, "title": "Updated draft chapter", "slug": "ch-1", "status": "draft"},
            timeout=15,
        )
        _expect_status(journey, "admin-update-draft-chapter", updated, 200, "admin can edit draft chapter metadata")
        journey.assert_equal("draft-chapter-title-persisted", updated.json().get("title"), "Updated draft chapter", intended="chapter metadata edit is persisted")

        publish = admin_user.session.post(f"/api/catalog/series/{series_id}/chapters/{chapter_id}/publish", timeout=15)
        _expect_status(journey, "empty-draft-publication-blocked", publish, 422, "admin cannot publish a chapter that has no pages")
        journey.assert_true("empty-draft-explains-page-requirement", "page" in publish.text.lower(), intended="publication validation explains that chapter pages are required", observed=publish.text[:300])

        deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}/chapters/{chapter_id}", timeout=15)
        _expect_status(journey, "admin-delete-draft-chapter", deleted, 204, "admin can delete a draft chapter")
        chapter_id = None
    finally:
        if chapter_id and series_id:
            admin_user.session.delete(f"/api/catalog/series/{series_id}/chapters/{chapter_id}", timeout=15)
        if series_id:
            response = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)
