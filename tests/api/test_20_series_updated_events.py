import uuid

import pytest

from helpers import assert_status


def _series_events(db, series_id: str):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT event_id::text, topic, event_type, event_version,
                   aggregate_type, aggregate_id, partition_key, producer,
                   payload, headers, published_at
            FROM event_outbox
            WHERE aggregate_type = 'series'
              AND aggregate_id = %s
              AND event_type = 'series.updated'
            ORDER BY created_at, event_id
            """,
            (series_id,),
        )
        return cur.fetchall()


def _cleanup_series_event_rows(db, series_id: str):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM event_outbox WHERE aggregate_type='series' AND aggregate_id=%s",
            (series_id,),
        )


@pytest.mark.write
def test_catalog_series_updated_is_atomic_noop_aware_and_broker_independent(
    admin_user,
    db,
):
    slug = f"pytest-series-event-{uuid.uuid4().hex[:10]}"
    create = admin_user.session.post(
        "/api/catalog/series",
        json={
            "title": "Series Event Baseline",
            "slug": slug,
            "description": "before",
            "status": "ongoing",
            "genre_ids": [],
            "tag_names": ["SERIES-EVENT"],
        },
        timeout=15,
    )
    assert_status(create, 201)
    series_id = create.json()["id"]

    try:
        # v1.1.5b defines series.updated for an existing aggregate mutation;
        # series creation itself is intentionally not re-labelled as an update.
        assert _series_events(db, series_id) == []

        update = admin_user.session.put(
            f"/api/catalog/series/{series_id}",
            json={
                "title": "Series Event Updated",
                "description": "after",
                "status": "completed",
                "genre_ids": [],
                "tag_ids": [],
            },
            timeout=15,
        )
        assert_status(update, 200)
        updated = update.json()

        rows = _series_events(db, series_id)
        assert len(rows) == 1
        event = rows[0]
        assert event[1] == "series.updated"
        assert event[2] == "series.updated"
        assert event[3] == 1
        assert event[4] == "series"
        assert event[5] == series_id
        assert event[6] == series_id
        assert event[7] in {"catalog-go", "catalog-service"}
        assert event[8]["series_id"] == series_id
        assert event[8]["series_slug"] == slug
        assert set(event[8]["changed_fields"]) == {
            "title",
            "description",
            "status",
            "tags",
        }
        assert event[8]["updated_at"]
        assert event[9]["payload_schema"] == "v1/series.updated.schema.json"
        # Do not race the active RabbitMQ relay by asserting published_at here.
        # This API regression owns event content/idempotency; broker-outage
        # independence is covered deterministically by validate-outbox-rabbitmq-v120.sh.

        # Sending the exact same aggregate state must not create a second
        # semantic event or advance updated_at merely because PUT was retried.
        noop = admin_user.session.put(
            f"/api/catalog/series/{series_id}",
            json={
                "title": "Series Event Updated",
                "description": "after",
                "status": "completed",
                "genre_ids": [],
                "tag_ids": [],
            },
            timeout=15,
        )
        assert_status(noop, 200)
        assert noop.json()["updated_at"] == updated["updated_at"]
        assert len(_series_events(db, series_id)) == 1

        # Force a later statement in the same transaction to fail. The earlier
        # series row mutation and any outbox work must roll back together.
        rejected = admin_user.session.put(
            f"/api/catalog/series/{series_id}",
            json={
                "title": "THIS MUST ROLLBACK",
                "genre_ids": [2147483647],
            },
            timeout=15,
        )
        assert_status(rejected, 422)
        assert len(_series_events(db, series_id)) == 1
        with db.cursor() as cur:
            cur.execute("SELECT title FROM series WHERE id=%s::uuid", (series_id,))
            assert cur.fetchone()[0] == "Series Event Updated"
    finally:
        admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=15)
        _cleanup_series_event_rows(db, series_id)
