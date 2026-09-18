import io
import os
import time
import uuid

import pytest

from helpers import assert_status, wait_until


def test_scraper_admin_existing_series_lookup(
    admin_anonymous,
    admin_regular_user,
    admin_user,
    seed_content,
):
    assert_status(
        admin_anonymous.get("/api/scraper/admin/series", timeout=10),
        401,
    )
    assert_status(
        admin_regular_user.session.get("/api/scraper/admin/series", timeout=10),
        403,
    )

    listing = admin_user.session.get(
        "/api/scraper/admin/series",
        params={"search": seed_content["series_slug"]},
        timeout=10,
    )
    assert_status(listing, 200)
    assert any(x["id"] == seed_content["series_id"] for x in listing.json())

    detail = admin_user.session.get(
        f"/api/scraper/admin/series/{seed_content['series_id']}",
        timeout=10,
    )
    assert_status(detail, 200)
    assert len(detail.json()["chapters"]) >= 2


def test_scraper_ssrf_protection(admin_user, seed_content):
    scrape = admin_user.session.post(
        "/api/scraper/scrape",
        json={
            "url": "http://127.0.0.1:8000",
            "mode": "full",
            "save": False,
            "store_raw_snapshot": False,
        },
        timeout=10,
    )
    assert_status(scrape, 400)

    draft = admin_user.session.post(
        "/api/scraper/drafts/chapter",
        json={
            "series_id": seed_content["series_id"],
            "chapter_url": "http://127.0.0.1/ch-99",
        },
        timeout=10,
    )
    assert_status(draft, 400)


@pytest.mark.external
def test_optional_real_existing_series_chapter_scrape(admin_user, seed_content):
    source_url = os.getenv("SCRAPER_TEST_CHAPTER_URL")
    if not source_url:
        pytest.skip("Set SCRAPER_TEST_CHAPTER_URL to exercise a real source adapter.")

    response = admin_user.session.post(
        "/api/scraper/drafts/chapter",
        json={
            "series_id": seed_content["series_id"],
            "chapter_url": source_url,
        },
        timeout=120,
    )
    assert_status(response, 200)
    assert response.json()["pages"]


@pytest.mark.worker
@pytest.mark.write
def test_scraper_batch_conflict_discard_and_overwrite(
    admin_user,
    seed_content,
    image_bytes,
    db,
):
    # Both ch-1 and ch-2 already exist in the isolated pytest series.
    files = [
        ("files", ("001.png", image_bytes, "image/png")),
        ("files", ("001.png", image_bytes, "image/png")),
    ]
    data = [
        ("series_id", seed_content["series_id"]),
        ("relative_paths", "ch-1/001.png"),
        ("relative_paths", "ch-2/001.png"),
    ]

    response = admin_user.session.post(
        "/api/scraper/batches",
        files=files,
        data=data,
        timeout=60,
    )
    assert_status(response, 200)

    batch = response.json()
    by_slug = {item["chapter_slug"]: item for item in batch["items"]}
    assert by_slug["ch-1"]["status"] == "failed_conflict"
    assert by_slug["ch-2"]["status"] == "failed_conflict"

    discard = admin_user.session.post(
        f"/api/scraper/batches/items/{by_slug['ch-1']['id']}/resolve",
        json={"action": "discard"},
        timeout=20,
    )
    assert_status(discard, 200)
    assert discard.json()["status"] == "discarded"

    original_ch2_id = by_slug["ch-2"]["existing_chapter_id"]
    assert original_ch2_id == seed_content["chapter_ids"]["ch-2"]

    overwrite = admin_user.session.post(
        f"/api/scraper/batches/items/{by_slug['ch-2']['id']}/resolve",
        json={"action": "overwrite"},
        timeout=30,
    )
    assert_status(overwrite, 200)
    assert overwrite.json()["status"] == "queued"

    def overwritten():
        current = admin_user.session.get(
            f"/api/scraper/batches/{batch['id']}",
            timeout=10,
        )
        assert_status(current, 200)
        item = next(
            x for x in current.json()["items"]
            if x["chapter_slug"] == "ch-2"
        )
        if item["status"] in {"completed", "failed_error", "failed_conflict"}:
            return item
        return None

    result = wait_until(
        overwritten,
        timeout=120,
        interval=1,
        description="batch overwrite processing",
    )
    assert result["status"] == "completed", result

    # Atomic overwrite preserves the chapter identity so bookmarks/progress links
    # do not break while the page set is replaced.
    with db.cursor() as cur:
        cur.execute(
            "SELECT id::text, page_count FROM chapters WHERE series_id=%s::uuid AND slug='ch-2'",
            (seed_content["series_id"],),
        )
        replaced = cur.fetchone()
        assert replaced is not None
        assert replaced[0] == original_ch2_id
        assert replaced[1] >= 1

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT producer, partition_key, payload
            FROM event_outbox
            WHERE event_type='series.updated'
              AND aggregate_type='series'
              AND aggregate_id=%s
              AND correlation_id=%s::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (seed_content["series_id"], batch["id"]),
        )
        event = cur.fetchone()
        assert event is not None
        assert event[0] == "scraper-service"
        assert event[1] == seed_content["series_id"]
        assert event[2]["changed_fields"] == ["updated_at"]
        cur.execute(
            "DELETE FROM event_outbox WHERE correlation_id=%s::uuid",
            (batch["id"],),
        )


@pytest.mark.worker
@pytest.mark.write
def test_scraper_failed_overwrite_keeps_existing_chapter_live(admin_user, seed_content, db):
    original_id = seed_content["chapter_ids"]["ch-1"]
    with db.cursor() as cur:
        cur.execute("SELECT page_count FROM chapters WHERE id=%s::uuid", (original_id,))
        original_page_count = cur.fetchone()[0]

    response = admin_user.session.post(
        "/api/scraper/batches",
        files=[("files", ("001.png", b"not-a-valid-png", "image/png"))],
        data=[("series_id", seed_content["series_id"]), ("relative_paths", "ch-1/001.png")],
        timeout=30,
    )
    assert_status(response, 200)
    item = response.json()["items"][0]
    assert item["status"] == "failed_conflict"
    assert item["existing_chapter_id"] == original_id

    queued = admin_user.session.post(
        f"/api/scraper/batches/items/{item['id']}/resolve",
        json={"action": "overwrite"},
        timeout=20,
    )
    assert_status(queued, 200)

    def failed():
        current = admin_user.session.get(f"/api/scraper/batches/{response.json()['id']}", timeout=10)
        assert_status(current, 200)
        row = current.json()["items"][0]
        return row if row["status"] in {"failed_error", "completed"} else None

    result = wait_until(failed, timeout=120, interval=1, description="failed atomic overwrite")
    assert result["status"] == "failed_error", result

    retry = admin_user.session.post(
        f"/api/scraper/batches/items/{item['id']}/retry",
        json={},
        timeout=20,
    )
    assert_status(retry, 200)
    assert retry.json()["status"] == "queued"

    def failed_again():
        current = admin_user.session.get(
            f"/api/scraper/batches/{response.json()['id']}", timeout=10
        )
        assert_status(current, 200)
        row = current.json()["items"][0]
        return row if row["status"] in {"failed_error", "completed"} else None

    retried_result = wait_until(
        failed_again,
        timeout=120,
        interval=1,
        description="retried failed atomic overwrite",
    )
    assert retried_result["status"] == "failed_error", retried_result

    with db.cursor() as cur:
        cur.execute("SELECT id::text, page_count FROM chapters WHERE id=%s::uuid", (original_id,))
        live = cur.fetchone()
        assert live == (original_id, original_page_count)
        cur.execute("SELECT COUNT(*) FROM pages WHERE chapter_id=%s::uuid", (original_id,))
        assert cur.fetchone()[0] == original_page_count
