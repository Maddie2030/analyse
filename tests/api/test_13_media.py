import time
import uuid

import pytest

from helpers import assert_status, wait_media_job, zip_image_chapter, wait_until, zip_image_chapter



def test_media_admin_protection(admin_anonymous, seed_content, image_bytes):
    response = admin_anonymous.post(
        f"/api/upload/series/{seed_content['series_slug']}/thumbnail",
        files={"file": ("cover.png", image_bytes, "image/png")},
        timeout=15,
    )
    assert_status(response, 401)


@pytest.mark.write
def test_media_thumbnail_upload_and_delete(admin_user, seed_content, image_bytes):
    response = admin_user.session.post(
        f"/api/upload/series/{seed_content['series_slug']}/thumbnail",
        files={"file": ("cover.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(response, 202)
    job_id = response.json()["job_id"]
    terminal = wait_media_job(admin_user.session, job_id, timeout=120)
    assert terminal["status"] == "completed", terminal
    path = terminal["result"]["image_path"]
    thumbnail_name = path.rsplit("/", 1)[-1]

    delete = admin_user.session.delete(
        f"/api/upload/series/{seed_content['series_slug']}/thumbnail/{thumbnail_name}",
        timeout=20,
    )
    assert_status(delete, {202, 204})


@pytest.mark.write
def test_media_compatibility_chapter_upload_duplicate_and_cleanup(
    admin_user,
    seed_content,
    image_bytes,
    db,
):
    chapter_slug = f"media-{uuid.uuid4().hex[:8]}"
    chapter_number = 900 + int(uuid.uuid4().hex[:2], 16)
    archive = zip_image_chapter(image_bytes)

    response = admin_user.session.post(
        f"/api/upload/upload/{seed_content['series_slug']}/{chapter_slug}",
        files={"file": ("chapter.zip", archive, "application/zip")},
        data={
            "chapter_number": str(chapter_number),
            "title": "Pytest Media Chapter",
        },
        timeout=60,
    )
    # RC4.45 intentionally made the legacy upload route a durable-job
    # compatibility adapter. Acceptance is 202; publication completes in the
    # Media worker and must be observed through the canonical job endpoint.
    assert_status(response, 202)
    job_id = response.json()["job_id"]

    def finished():
        status = admin_user.session.get(f"/api/upload/jobs/{job_id}", timeout=10)
        assert_status(status, 200)
        body = status.json()
        return body if body.get("status") in {"completed", "failed"} else None

    state = wait_until(finished, timeout=180, interval=1, description="compatibility chapter media job")
    assert state["status"] == "completed", state
    chapter_id = state["result"]["chapter_id"]

    duplicate = admin_user.session.post(
        f"/api/upload/upload/{seed_content['series_slug']}/{chapter_slug}",
        files={"file": ("chapter.zip", archive, "application/zip")},
        data={"chapter_number": str(chapter_number)},
        timeout=60,
    )
    assert_status(duplicate, 409)

    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM pages WHERE chapter_id = %s::uuid",
                (chapter_id,),
            )
            assert cur.fetchone()[0] >= 1
            cur.execute(
                """
                SELECT topic, event_type, partition_key, payload
                FROM event_outbox
                WHERE aggregate_type = 'chapter'
                  AND aggregate_id = %s
                  AND event_type = 'chapter.published'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (chapter_id,),
            )
            event = cur.fetchone()
            assert event is not None
            assert event[0] == "chapter.published"
            assert event[1] == "chapter.published"
            assert event[2] == seed_content["series_id"]
            assert event[3]["chapter_id"] == chapter_id
            assert event[3]["series_slug"] == seed_content["series_slug"]
    finally:
        delete = admin_user.session.delete(
            f"/api/catalog/series/{seed_content['series_id']}/chapters/{chapter_id}",
            timeout=20,
        )
        assert_status(delete, 204)
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM event_outbox WHERE aggregate_type = 'chapter' AND aggregate_id = %s",
                (chapter_id,),
            )


@pytest.mark.worker
def test_media_thumbnail_async_job(admin_user, seed_content, image_bytes):
    response = admin_user.session.post(
        f"/api/upload/jobs/thumbnail/{seed_content['series_slug']}",
        files={"file": ("cover.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(response, 202)
    result = wait_media_job(admin_user.session, response.json()["job_id"], timeout=90)
    assert result["status"] == "completed", result

@pytest.mark.write
def test_media_optional_first_last_images(admin_user, seed_content, image_bytes, db):
    chapter_slug = f"boundary-{uuid.uuid4().hex[:8]}"
    chapter_number = 1200 + int(uuid.uuid4().hex[:2], 16)
    archive = zip_image_chapter(image_bytes)
    response = admin_user.session.post(
        f"/api/upload/upload/{seed_content['series_slug']}/{chapter_slug}",
        files={
            "file": ("chapter.zip", archive, "application/zip"),
            "first_image": ("first.png", image_bytes, "image/png"),
            "last_image": ("last.png", image_bytes, "image/png"),
        },
        data={"chapter_number": str(chapter_number), "title": "Boundary Images"},
        timeout=60,
    )
    assert_status(response, 202)
    job_id = response.json()["job_id"]

    def finished():
        status = admin_user.session.get(f"/api/upload/jobs/{job_id}", timeout=10)
        assert_status(status, 200)
        body = status.json()
        return body if body.get("status") in {"completed", "failed"} else None

    state = wait_until(finished, timeout=180, interval=1, description="boundary-image chapter media job")
    assert state["status"] == "completed", state
    chapter_id = state["result"]["chapter_id"]

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT page_number, image_path
            FROM pages
            WHERE chapter_id=%s::uuid
            ORDER BY page_number
            """,
            (chapter_id,),
        )
        pages = cur.fetchall()
    assert len(pages) >= 4
    assert pages[0][1].endswith(("0001.mrt", "0001.webp"))
    final_stem = f"{pages[-1][0]:04d}"
    assert pages[-1][1].endswith((f"{final_stem}.mrt", f"{final_stem}.webp"))
    delete = admin_user.session.delete(
        f"/api/catalog/series/{seed_content['series_id']}/chapters/{chapter_id}",
        timeout=20,
    )
    assert_status(delete, 204)


@pytest.mark.worker
@pytest.mark.write
def test_media_async_chapter_job(admin_user, seed_content, image_bytes):
    chapter_slug = f"queued-media-{uuid.uuid4().hex[:8]}"
    chapter_number = 1500 + int(uuid.uuid4().hex[:2], 16)
    archive = zip_image_chapter(image_bytes)
    queued = admin_user.session.post(
        f"/api/upload/jobs/chapter/{seed_content['series_slug']}/{chapter_slug}",
        files={"file": ("chapter.zip", archive, "application/zip")},
        data={"chapter_number": str(chapter_number), "title": "Queued Chapter"},
        timeout=30,
    )
    assert_status(queued, 202)
    job_id = queued.json()["job_id"]

    def finished():
        response = admin_user.session.get(f"/api/upload/jobs/{job_id}", timeout=10)
        assert_status(response, 200)
        body = response.json()
        return body if body.get("status") in {"completed", "failed"} else None

    state = wait_until(finished, timeout=180, interval=1, description="chapter media job")
    assert state["status"] == "completed", state
    chapter_id = state["result"]["chapter_id"]
    delete = admin_user.session.delete(
        f"/api/catalog/series/{seed_content['series_id']}/chapters/{chapter_id}", timeout=20
    )
    assert_status(delete, 204)


@pytest.mark.write
def test_storage_delete_cannot_bypass_catalog_lifecycle(admin_user, seed_content):
    response = admin_user.session.delete(
        f"/api/upload/{seed_content['series_slug']}/ch-1", timeout=15
    )
    assert_status(response, 409)
