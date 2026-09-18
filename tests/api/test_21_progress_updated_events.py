import uuid

import pytest

from helpers import assert_status
from reading_helpers import open_chapter, checkpoint_payload


@pytest.mark.write
def test_progress_commit_response_has_one_committed_reading_state(
    temp_user_factory, seed_content, db
):
    """The successful API response must follow the same DB transaction for both facts."""
    user = temp_user_factory(f"progress_atomic_{uuid.uuid4().hex[:8]}")
    try:
        opened = open_chapter(user.session, f"/api/progress/{seed_content['series_slug']}/ch-1", 0)
        response = user.session.post(
            f"/api/progress/{seed_content['series_slug']}/ch-1/commit",
            json=checkpoint_payload(opened, 1, 0.375),
            timeout=15,
        )
        assert_status(response, 200)

        with db.cursor() as cur:
            cur.execute(
                """
                SELECT chapter_id::text, last_page, scroll_position
                FROM reading_progress
                WHERE user_id=%s::uuid AND series_id=%s::uuid
                """,
                (user.user_id, seed_content["series_id"]),
            )
            progress = cur.fetchone()
            cur.execute(
                """
                SELECT chapter_id::text, last_page, completed
                FROM chapter_reads
                WHERE user_id=%s::uuid AND series_id=%s::uuid
                """,
                (user.user_id, seed_content["series_id"]),
            )
            ledger = cur.fetchone()

        assert progress == (seed_content["chapter_ids"]["ch-1"], 1, 0.375)
        assert ledger == (seed_content["chapter_ids"]["ch-1"], 1, False)
    finally:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM reading_progress WHERE user_id=%s::uuid AND series_id=%s::uuid",
                (user.user_id, seed_content["series_id"]),
            )
            cur.execute(
                "DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
                (user.user_id, seed_content["series_id"]),
            )


def _progress_events(db, aggregate_id: str):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT event_id::text, topic, event_type, event_version,
                   aggregate_type, aggregate_id, partition_key, producer,
                   payload, headers, published_at, occurred_at
            FROM event_outbox
            WHERE aggregate_type = 'reading_progress'
              AND aggregate_id = %s
              AND event_type = 'progress.updated'
            ORDER BY created_at, event_id
            """,
            (aggregate_id,),
        )
        return cur.fetchall()


def _cleanup_progress_event_rows(db, aggregate_id: str):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM event_outbox WHERE aggregate_type='reading_progress' AND aggregate_id=%s",
            (aggregate_id,),
        )


@pytest.mark.write
def test_progress_updated_is_persisted_transactionally_with_outbox_event(
    temp_user_factory,
    seed_content,
    db,
):
    user = temp_user_factory(f"progress_event_{uuid.uuid4().hex[:8]}")
    aggregate_id = f"{user.user_id}:{seed_content['series_id']}"
    path = f"/api/progress/{seed_content['series_slug']}/ch-1"

    try:
        opened = open_chapter(user.session, path, 0)
        save = user.session.post(
            f"{path}/commit",
            json=checkpoint_payload(opened, 2, 0.375),
            timeout=15,
        )
        assert_status(save, 200)
        saved = save.json()
        assert saved["chapter_id"] == seed_content["chapter_ids"]["ch-1"]
        assert saved["last_page"] == 2
        assert abs(float(saved["scroll_position"]) - 0.375) < 1e-9

        rows = _progress_events(db, aggregate_id)
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT chapter_id::text, last_page, scroll_position, updated_at
                FROM reading_progress
                WHERE user_id=%s::uuid AND series_id=%s::uuid
                """,
                (user.user_id, seed_content["series_id"]),
            )
            progress = cur.fetchone()

        assert progress is not None
        assert progress[0] == seed_content["chapter_ids"]["ch-1"]
        assert progress[1] == 2
        assert abs(float(progress[2]) - 0.375) < 1e-9

        assert len(rows) == 2  # one accepted open and one accepted checkpoint
        event = next(row for row in rows if row[8]["revision"] == saved["revision"])
        assert event[1] == "progress.updated"
        assert event[2] == "progress.updated"
        assert event[3] == 2
        assert event[4] == "reading_progress"
        assert event[5] == aggregate_id
        assert event[6] == aggregate_id
        assert event[7] == "progress-go"
        assert event[8]["user_id"] == user.user_id
        assert event[8]["series_id"] == seed_content["series_id"]
        assert event[8]["chapter_id"] == seed_content["chapter_ids"]["ch-1"]
        assert event[8]["last_page"] == 2
        assert abs(float(event[8]["scroll_position"]) - 0.375) < 1e-9
        assert event[8]["updated_at"]
        assert event[8]["revision"] == 2
        assert event[9]["payload_schema"] == "v2/progress.updated.schema.json"
        assert event[9]["source"] == "progress-api"
        assert "source_message_id" not in event[9]
        # Delivery timing is deliberately outside this API test. The active
        # RabbitMQ relay may publish before this query; deterministic broker
        # independence is covered by the dedicated RabbitMQ outage/recovery gate.
        assert event[11] == progress[3]
    finally:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM reading_progress WHERE user_id=%s::uuid AND series_id=%s::uuid",
                (user.user_id, seed_content["series_id"]),
            )
            cur.execute(
                "DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
                (user.user_id, seed_content["series_id"]),
            )
        _cleanup_progress_event_rows(db, aggregate_id)
