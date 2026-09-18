import os
import time

import pytest

from helpers import assert_status, wait_until


def test_series_draft_admin_only(admin_anonymous):
    response = admin_anonymous.get("/api/scraper/series-drafts", timeout=10)
    assert_status(response, 401)




@pytest.mark.write
def test_clear_all_series_draft_chapter_titles(
    admin_user,
    seeded_series_draft,
):
    draft_id = seeded_series_draft["draft_id"]

    before = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}",
        timeout=10,
    )
    assert_status(before, 200)
    assert any(
        chapter.get("chapter_title")
        for chapter in before.json()["chapters"]
    )

    cleared = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/chapters/clear-titles",
        timeout=10,
    )
    assert_status(cleared, 200)

    body = cleared.json()
    assert body["chapters"]
    assert all(
        chapter.get("chapter_title") is None
        for chapter in body["chapters"]
    )
    assert body.get("chapter_titles_suppressed") is True
    assert body.get("discovery_options", {}).get("suppress_chapter_titles") is True


@pytest.mark.write
def test_clear_titles_remains_available_during_existing_series_update(
    admin_user,
    seeded_series_draft,
    seed_content,
    db,
):
    draft_id = seeded_series_draft["draft_id"]

    # Existing-series update drafts point at a real production series before
    # their newly discovered chapters are published. That target reference
    # must not make Clear all read-only.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET published_series_id=%s::uuid, workflow_status='discovering'
            WHERE id=%s::uuid
            """,
            (seed_content["series_id"], draft_id),
        )

    cleared = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/chapters/clear-titles",
        timeout=10,
    )
    assert_status(cleared, 200)
    body = cleared.json()
    assert body["workflow_status"] == "discovering"
    assert body["published_series_id"] == seed_content["series_id"]
    assert body.get("chapter_titles_suppressed") is True
    assert all(chapter.get("chapter_title") is None for chapter in body["chapters"])


@pytest.mark.write
def test_series_draft_chapter_slug_is_canonical_from_number(
    admin_user,
    seeded_series_draft,
):
    chapter_id = seeded_series_draft["chapter_id"]

    updated = admin_user.session.patch(
        f"/api/scraper/series-drafts/chapters/{chapter_id}",
        json={
            "chapter_number": "13.50",
            "chapter_slug": "this-title-must-not-control-the-slug",
            "chapter_title": "A Completely Different Chapter Title",
            "selected": True,
        },
        timeout=10,
    )
    assert_status(updated, 200)
    chapter = next(
        row for row in updated.json()["chapters"] if row["id"] == chapter_id
    )
    assert str(chapter["chapter_number"]).rstrip("0").rstrip(".") == "13.5"
    assert chapter["chapter_slug"] == "ch-13-5"
    assert chapter["chapter_title"] == "A Completely Different Chapter Title"

@pytest.mark.external
def test_optional_real_series_discovery(admin_user):
    source_url = os.getenv("SCRAPER_TEST_SERIES_URL")
    if not source_url:
        pytest.skip("Set SCRAPER_TEST_SERIES_URL to test live full-series discovery.")

    response = admin_user.session.post(
        "/api/scraper/series-drafts/discover",
        json={"url": source_url},
        timeout=120,
    )
    assert_status(response, 200)
    body = response.json()
    assert body["title"]
    assert body["chapters"]


@pytest.mark.write
def test_edit_local_series_draft_and_cover(
    admin_user,
    seeded_series_draft,
    image_bytes,
):
    draft_id = seeded_series_draft["draft_id"]

    get = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}",
        timeout=10,
    )
    assert_status(get, 200)

    updated = admin_user.session.patch(
        f"/api/scraper/series-drafts/{draft_id}",
        json={
            "title": "Edited Pytest Series",
            "slug": seeded_series_draft["slug"],
            "description": "Edited before publish",
            "series_status": "completed",
            "genres": ["Action", "Testing"],
            "tags": ["PYTEST", "INTEGRATION"],
        },
        timeout=10,
    )
    assert_status(updated, 200)
    assert updated.json()["title"] == "Edited Pytest Series"

    cover = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/cover/upload",
        files={"file": ("cover.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(cover, 200)

    preview = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}/cover/preview",
        timeout=20,
    )
    assert_status(preview, 200)
    assert preview.content


@pytest.mark.worker
@pytest.mark.write
def test_local_series_draft_page_edit_and_publish(
    admin_user,
    seeded_series_draft,
    image_bytes,
    db,
):
    draft_id = seeded_series_draft["draft_id"]
    chapter_id = seeded_series_draft["chapter_id"]

    metadata = admin_user.session.patch(
        f"/api/scraper/series-drafts/{draft_id}",
        json={
            "title": "Edited Pytest Series",
            "slug": seeded_series_draft["slug"],
            "description": "Edited before publish",
            "series_status": "completed",
            "genres": ["Action", "Testing"],
            "tags": ["PYTEST", "INTEGRATION"],
        },
        timeout=10,
    )
    assert_status(metadata, 200)

    first = admin_user.session.post(
        f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/upload",
        files={"file": ("001.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(first, 200)

    second = admin_user.session.post(
        f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/upload",
        files={"file": ("002.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(second, 200)

    chapter = next(
        x for x in second.json()["chapters"]
        if x["id"] == chapter_id
    )
    assert len(chapter["pages"]) == 2

    preview = admin_user.session.get(
        f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/"
        f"{chapter['pages'][0]['id']}/preview",
        timeout=20,
    )
    assert_status(preview, 200)
    assert preview.content

    reordered = admin_user.session.post(
        f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/reorder",
        json={
            "page_ids": [
                chapter["pages"][1]["id"],
                chapter["pages"][0]["id"],
            ]
        },
        timeout=20,
    )
    assert_status(reordered, 200)

    publish = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/publish",
        timeout=20,
    )
    assert_status(publish, 200)

    def published():
        current = admin_user.session.get(
            f"/api/scraper/series-drafts/{draft_id}",
            timeout=10,
        )
        assert_status(current, 200)
        body = current.json()
        if body["workflow_status"] in {"published", "failed"}:
            return body
        return None

    result = wait_until(
        published,
        timeout=120,
        interval=1,
        description="new-series publication",
    )
    assert result["workflow_status"] == "published", result

    published_chapter_id = next(
        chapter["published_chapter_id"]
        for chapter in result["chapters"]
        if chapter["id"] == chapter_id
    )
    assert published_chapter_id
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT topic, event_type, correlation_id::text, payload
            FROM event_outbox
            WHERE aggregate_type = 'chapter'
              AND aggregate_id = %s
              AND event_type = 'chapter.published'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (published_chapter_id,),
        )
        event = cur.fetchone()
    assert event is not None
    assert event[0] == "chapter.published"
    assert event[1] == "chapter.published"
    assert event[2] == draft_id
    assert event[3]["chapter_id"] == published_chapter_id
    assert event[3]["series_slug"] == seeded_series_draft["slug"]

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT producer, partition_key, payload
            FROM event_outbox
            WHERE correlation_id = %s::uuid
              AND event_type = 'series.updated'
              AND payload->>'series_slug' = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (draft_id, seeded_series_draft["slug"]),
        )
        series_event = cur.fetchone()
    assert series_event is not None
    assert series_event[0] == "scraper-service"
    assert series_event[1] == series_event[2]["series_id"]
    assert series_event[2]["series_slug"] == seeded_series_draft["slug"]
    assert series_event[2]["changed_fields"] == ["updated_at"]
    # Delivery timing is intentionally not asserted here. The active RabbitMQ
    # outbox relay may publish this row before or after this query; broker-outage
    # independence is validated by the dedicated outbox recovery gate.

    catalog = admin_user.session.get(
        f"/api/catalog/series/{seeded_series_draft['slug']}",
        timeout=20,
    )
    assert_status(catalog, 200)
    assert catalog.json()["title"] == "Edited Pytest Series"

    reader = admin_user.session.get(
        f"/api/reader/{seeded_series_draft['slug']}/ch-1",
        timeout=20,
    )
    assert_status(reader, 200)
    assert reader.json()["page_count"] >= 2


@pytest.mark.write
def test_stage_guard_stops_exact_existing_title(
    admin_user, seeded_series_draft, seed_content
):
    draft_id = seeded_series_draft["draft_id"]
    existing = admin_user.session.get(
        f"/api/catalog/series/{seed_content['series_slug']}", timeout=10
    )
    assert_status(existing, 200)
    existing_body = existing.json()

    updated = admin_user.session.patch(
        f"/api/scraper/series-drafts/{draft_id}",
        json={
            "title": existing_body["title"],
            "slug": seeded_series_draft["slug"],
            "description": "duplicate guard test",
            "series_status": "ongoing",
            "genres": [],
            "tags": [],
        },
        timeout=10,
    )
    assert_status(updated, 200)

    staged = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/stage",
        json={"chapter_ids": [seeded_series_draft["chapter_id"]]},
        timeout=20,
    )
    assert_status(staged, 200)
    body = staged.json()
    assert body["workflow_status"] == "duplicate"
    assert body["duplicate_series_id"] == seed_content["series_id"]
    assert body["duplicate_series_slug"] == seed_content["series_slug"]
    # Wording is UI text; the durable duplicate identity/state is the contract.
    assert "already exists" in body["error_message"].lower()


@pytest.mark.write
def test_stage_guard_recognizes_kebab_cased_existing_title(
    admin_user, seeded_series_draft, seed_content
):
    draft_id = seeded_series_draft["draft_id"]

    updated = admin_user.session.patch(
        f"/api/scraper/series-drafts/{draft_id}",
        json={
            "title": seed_content["series_slug"],
            # The duplicate guard explicitly supports a canonical slug match in
            # addition to an exact title match. Exercise that contract directly
            # instead of assuming a kebab-cased title is equal to a human title.
            "slug": seed_content["series_slug"],
            "description": "canonical slug duplicate guard test",
            "series_status": "ongoing",
            "genres": [],
            "tags": [],
        },
        timeout=10,
    )
    assert_status(updated, 200)

    staged = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/stage",
        json={"chapter_ids": [seeded_series_draft["chapter_id"]]},
        timeout=20,
    )
    assert_status(staged, 200)
    body = staged.json()
    assert body["workflow_status"] == "duplicate"
    assert body["duplicate_series_slug"] == seed_content["series_slug"]


@pytest.mark.worker
@pytest.mark.write
def test_new_series_chapters_publish_independently_while_one_stage_fails(
    admin_user,
    seeded_series_draft,
    image_bytes,
    db,
):
    """A failed staged chapter must not block good chapters from going live.

    This exercises the admin's row-level Publish/Retry workflow rather than the
    batch coordinator. Published chapters stay committed while the failed one
    is repaired and published later.
    """
    draft_id = seeded_series_draft["draft_id"]
    chapter_1_id = seeded_series_draft["chapter_id"]
    chapter_2_id = None
    chapter_3_id = None

    import uuid

    chapter_2_id = str(uuid.uuid4())
    chapter_3_id = str(uuid.uuid4())

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scraper_series_draft_chapters(
                id, draft_id, chapter_number, chapter_slug, chapter_title,
                source_url, selected, stage_status, error_message, pages
            )
            VALUES
                (%s::uuid, %s::uuid, 2, 'ch-2', 'Draft Chapter 2',
                 'https://example.invalid/pytest-series/ch-2', TRUE, 'error',
                 'Simulated staging failure for flexible publish test.', '[]'::jsonb),
                (%s::uuid, %s::uuid, 3, 'ch-3', 'Draft Chapter 3',
                 'https://example.invalid/pytest-series/ch-3', TRUE, 'ready',
                 NULL, '[]'::jsonb)
            """,
            (chapter_2_id, draft_id, chapter_3_id, draft_id),
        )

    # Both healthy chapters have real staged page bytes. The failed chapter is
    # intentionally left broken so it cannot be published yet.
    for chapter_id, name in (
        (chapter_1_id, "ch1.png"),
        (chapter_3_id, "ch3.png"),
    ):
        uploaded = admin_user.session.post(
            f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/upload",
            files={"file": (name, image_bytes, "image/png")},
            timeout=30,
        )
        assert_status(uploaded, 200)

    # Publish chapter 1 while chapter 2 is failed and chapter 3 is merely ready.
    queued_one = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/chapters/{chapter_1_id}/publish",
        timeout=20,
    )
    assert_status(queued_one, 200)

    def chapter_1_published():
        current = admin_user.session.get(
            f"/api/scraper/series-drafts/{draft_id}", timeout=10
        )
        assert_status(current, 200)
        body = current.json()
        chapter = next(row for row in body["chapters"] if row["id"] == chapter_1_id)
        if chapter.get("published_chapter_id"):
            return body
        if chapter.get("publish_status") == "failed":
            raise AssertionError(chapter)
        return None

    after_one = wait_until(
        chapter_1_published,
        timeout=120,
        interval=1,
        description="independent chapter 1 publication",
    )
    row_2 = next(row for row in after_one["chapters"] if row["id"] == chapter_2_id)
    row_3 = next(row for row in after_one["chapters"] if row["id"] == chapter_3_id)
    assert row_2["stage_status"] == "error"
    assert row_2.get("published_chapter_id") is None
    assert row_3["stage_status"] == "ready"
    assert row_3.get("published_chapter_id") is None

    # Publish chapter 3 independently without repairing chapter 2 first.
    queued_three = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/chapters/{chapter_3_id}/publish",
        timeout=20,
    )
    assert_status(queued_three, 200)

    def chapter_3_published():
        current = admin_user.session.get(
            f"/api/scraper/series-drafts/{draft_id}", timeout=10
        )
        assert_status(current, 200)
        body = current.json()
        chapter = next(row for row in body["chapters"] if row["id"] == chapter_3_id)
        if chapter.get("published_chapter_id"):
            return body
        if chapter.get("publish_status") == "failed":
            raise AssertionError(chapter)
        return None

    after_three = wait_until(
        chapter_3_published,
        timeout=120,
        interval=1,
        description="independent chapter 3 publication",
    )
    assert after_three["workflow_status"] == "published_partial"
    assert next(
        row for row in after_three["chapters"] if row["id"] == chapter_2_id
    )["stage_status"] == "error"

    # Simulate the admin successfully repairing/re-staging only chapter 2, then
    # upload its replacement page and publish it without touching 1 or 3.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET stage_status = 'ready', error_message = NULL, updated_at = NOW()
            WHERE id = %s::uuid
            """,
            (chapter_2_id,),
        )

    repaired_page = admin_user.session.post(
        f"/api/scraper/series-drafts/chapters/{chapter_2_id}/pages/upload",
        files={"file": ("ch2-repaired.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(repaired_page, 200)

    queued_two = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/chapters/{chapter_2_id}/publish",
        timeout=20,
    )
    assert_status(queued_two, 200)

    def all_published():
        current = admin_user.session.get(
            f"/api/scraper/series-drafts/{draft_id}", timeout=10
        )
        assert_status(current, 200)
        body = current.json()
        if all(row.get("published_chapter_id") for row in body["chapters"]):
            return body
        failures = [
            row for row in body["chapters"]
            if row.get("publish_status") == "failed"
        ]
        if failures:
            raise AssertionError(failures)
        return None

    final = wait_until(
        all_published,
        timeout=120,
        interval=1,
        description="repaired chapter 2 independent publication",
    )
    assert final["workflow_status"] == "published"

    published_ids = {
        row["published_chapter_id"] for row in final["chapters"]
        if row.get("published_chapter_id")
    }
    assert len(published_ids) == 3

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM event_outbox
            WHERE correlation_id = %s::uuid
              AND event_type = 'chapter.published'
              AND aggregate_id = ANY(%s)
            """,
            (draft_id, list(published_ids)),
        )
        assert cur.fetchone()[0] == 3
        cur.execute(
            """
            SELECT COUNT(*), MIN(producer), MIN(partition_key)
            FROM event_outbox
            WHERE correlation_id = %s::uuid
              AND event_type = 'series.updated'
              AND payload->>'series_slug' = %s
            """,
            (draft_id, seeded_series_draft["slug"]),
        )
        series_events = cur.fetchone()
        assert series_events[0] == 3
        assert series_events[1] == "scraper-service"
        assert series_events[2]

    # Already committed chapters are present once each; repairing the failed
    # chapter does not republish good chapters.
    catalog = admin_user.session.get(
        f"/api/catalog/series/{seeded_series_draft['slug']}", timeout=20
    )
    assert_status(catalog, 200)
    numbers = sorted(float(ch["chapter_number"]) for ch in catalog.json()["chapters"])
    assert numbers == [1.0, 2.0, 3.0]
