import uuid

import pytest

from helpers import assert_status, wait_media_job, zip_image_chapter



def _event_rows(db, job_id: str):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, aggregate_type, aggregate_id, partition_key,
                   producer, payload, published_at
            FROM event_outbox
            WHERE aggregate_type = 'media_operation'
              AND aggregate_id = %s
            ORDER BY created_at, event_id
            """,
            (job_id,),
        )
        return cur.fetchall()


def _cleanup_operation(db, job_id: str):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM media_operations WHERE operation_id = %s::uuid",
            (job_id,),
        )
        cur.execute(
            "DELETE FROM event_outbox WHERE aggregate_type = 'media_operation' AND aggregate_id = %s",
            (job_id,),
        )
        cur.execute(
            "DELETE FROM event_outbox WHERE correlation_id = %s::uuid",
            (job_id,),
        )


@pytest.mark.worker
@pytest.mark.write
def test_thumbnail_media_events_are_transactional_and_broker_independent(
    admin_user,
    seed_content,
    image_bytes,
    db,
):
    queued = admin_user.session.post(
        f"/api/upload/jobs/thumbnail/{seed_content['series_slug']}",
        files={"file": ("cover.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(queued, 202)
    job_id = queued.json()["job_id"]
    assert queued.json()["durable"] is True

    try:
        # Normal test mode has no synchronous broker dependency. The accepted Media row and
        # media.uploaded outbox event must already exist before processing ends.
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT status, series_id::text, staged_object_path,
                       uploaded_event_id::text, processed_event_id::text
                FROM media_operations
                WHERE operation_id = %s::uuid
                """,
                (job_id,),
            )
            operation = cur.fetchone()
        assert operation is not None
        assert operation[0] in {"queued", "processing", "retry", "completed"}
        assert operation[1] == seed_content["series_id"]
        assert operation[2] == f"_jobs/media/{job_id}/source"
        assert operation[3]

        rows = _event_rows(db, job_id)
        uploaded = [row for row in rows if row[0] == "media.uploaded"]
        assert len(uploaded) == 1
        assert uploaded[0][1] == "media_operation"
        assert uploaded[0][2] == job_id
        assert uploaded[0][3] == seed_content["series_id"]
        assert uploaded[0][4] == "image-service"
        assert uploaded[0][5]["upload_id"] == job_id
        assert uploaded[0][5]["series_id"] == seed_content["series_id"]
        assert uploaded[0][5]["object_paths"] == [f"_jobs/media/{job_id}/source"]

        terminal = wait_media_job(admin_user.session, job_id, timeout=120)
        assert terminal["status"] == "completed", terminal
        image_path = terminal["result"]["image_path"]

        with db.cursor() as cur:
            cur.execute(
                """
                SELECT status, processed_event_id::text, result, output_paths
                FROM media_operations
                WHERE operation_id = %s::uuid
                """,
                (job_id,),
            )
            completed = cur.fetchone()
        assert completed[0] == "completed"
        assert completed[1]
        assert completed[2]["image_path"] == image_path
        assert completed[3] == [image_path]

        rows = _event_rows(db, job_id)
        assert [row[0] for row in rows].count("media.uploaded") == 1
        assert [row[0] for row in rows].count("media.processed") == 1
        processed = next(row for row in rows if row[0] == "media.processed")
        assert processed[5]["job_id"] == job_id
        assert processed[5]["series_id"] == seed_content["series_id"]
        assert processed[5]["status"] == "processed"
        assert processed[5]["output_paths"] == [image_path]

        with db.cursor() as cur:
            cur.execute(
                """
                SELECT producer, partition_key, payload, published_at
                FROM event_outbox
                WHERE aggregate_type = 'series'
                  AND aggregate_id = %s
                  AND event_type = 'series.updated'
                  AND producer = 'catalog-go'
                  AND payload->'changed_fields' @> '["cover_image_path"]'::jsonb
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (seed_content["series_id"],),
            )
            series_event = cur.fetchone()
        assert series_event is not None
        assert series_event[0] == "catalog-go"
        assert series_event[1] == seed_content["series_id"]
        assert series_event[2]["series_slug"] == seed_content["series_slug"]
        assert series_event[2]["changed_fields"] == ["cover_image_path"]
        # RabbitMQ relay may publish before this assertion. The transactional
        # invariant is that the outbox row exists with the canonical mutation.

        thumbnail_name = image_path.rsplit("/", 1)[-1]
        delete = admin_user.session.delete(
            f"/api/upload/series/{seed_content['series_slug']}/thumbnail/{thumbnail_name}",
            timeout=20,
        )
        assert_status(delete, {202, 204})
    finally:
        _cleanup_operation(db, job_id)


@pytest.mark.worker
@pytest.mark.write
def test_chapter_media_processed_commits_with_chapter_and_chapter_published(
    admin_user,
    seed_content,
    image_bytes,
    db,
):
    chapter_slug = f"media-event-{uuid.uuid4().hex[:8]}"
    chapter_number = 1800 + int(uuid.uuid4().hex[:2], 16)
    archive = zip_image_chapter(image_bytes)

    queued = admin_user.session.post(
        f"/api/upload/jobs/chapter/{seed_content['series_slug']}/{chapter_slug}",
        files={"file": ("chapter.zip", archive, "application/zip")},
        data={"chapter_number": str(chapter_number), "title": "Media Event Chapter"},
        timeout=30,
    )
    assert_status(queued, 202)
    job_id = queued.json()["job_id"]
    chapter_id = None

    try:
        rows = _event_rows(db, job_id)
        assert [row[0] for row in rows].count("media.uploaded") == 1

        terminal = wait_media_job(admin_user.session, job_id, timeout=180)
        assert terminal["status"] == "completed", terminal
        chapter_id = terminal["result"]["chapter_id"]

        with db.cursor() as cur:
            cur.execute(
                """
                SELECT status, chapter_id::text, processed_event_id::text
                FROM media_operations
                WHERE operation_id = %s::uuid
                """,
                (job_id,),
            )
            operation = cur.fetchone()
            assert operation is not None
            assert operation[0] == "completed"
            assert operation[1] == chapter_id
            assert operation[2]

            # Both events are durable PostgreSQL rows after the same canonical
            # chapter-ingestion transaction completes; RabbitMQ is not consulted synchronously.
            cur.execute(
                """
                SELECT COUNT(*)
                FROM event_outbox
                WHERE aggregate_type = 'chapter'
                  AND aggregate_id = %s
                  AND event_type = 'chapter.published'
                """,
                (chapter_id,),
            )
            assert cur.fetchone()[0] == 1

            cur.execute(
                """
                SELECT producer, partition_key, payload, published_at
                FROM event_outbox
                WHERE aggregate_type = 'series'
                  AND aggregate_id = %s
                  AND event_type = 'series.updated'
                  AND producer = 'catalog-go'
                  AND payload->'changed_fields' @> '["chapters", "updated_at"]'::jsonb
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (seed_content["series_id"],),
            )
            series_event = cur.fetchone()
            assert series_event is not None
            assert series_event[0] == "catalog-go"
            assert series_event[1] == seed_content["series_id"]
            assert series_event[2]["series_slug"] == seed_content["series_slug"]
            assert series_event[2]["changed_fields"] == ["chapters", "updated_at"]
            # published_at may already be populated by the RabbitMQ relay.

        rows = _event_rows(db, job_id)
        assert [row[0] for row in rows].count("media.uploaded") == 1
        assert [row[0] for row in rows].count("media.processed") == 1
        processed = next(row for row in rows if row[0] == "media.processed")
        assert processed[5]["job_id"] == job_id
        assert processed[5]["chapter_id"] == chapter_id
        assert processed[5]["status"] == "processed"
        assert processed[5]["output_paths"]
    finally:
        if chapter_id:
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
        _cleanup_operation(db, job_id)


@pytest.mark.worker
@pytest.mark.write
def test_terminal_media_failure_emits_one_failed_processed_event(
    admin_user,
    seed_content,
    db,
):
    queued = admin_user.session.post(
        f"/api/upload/jobs/thumbnail/{seed_content['series_slug']}",
        files={"file": ("broken.png", b"this-is-not-an-image", "image/png")},
        timeout=30,
    )
    assert_status(queued, 202)
    job_id = queued.json()["job_id"]

    try:
        terminal = wait_media_job(admin_user.session, job_id, timeout=120)
        assert terminal["status"] == "failed", terminal
        rows = _event_rows(db, job_id)
        assert [row[0] for row in rows].count("media.uploaded") == 1
        assert [row[0] for row in rows].count("media.processed") == 1
        processed = next(row for row in rows if row[0] == "media.processed")
        assert processed[5]["status"] == "failed"
        assert processed[5]["error"]
        with db.cursor() as cur:
            cur.execute(
                "SELECT status, attempt_count, processed_event_id IS NOT NULL FROM media_operations WHERE operation_id=%s::uuid",
                (job_id,),
            )
            state = cur.fetchone()
        assert state[0] == "failed"
        assert state[1] >= 1
        assert state[2] is True
    finally:
        _cleanup_operation(db, job_id)
