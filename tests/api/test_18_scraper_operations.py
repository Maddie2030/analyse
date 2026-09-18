import pytest

from helpers import assert_status, wait_until


def test_scraper_operations_admin_only(admin_anonymous):
    response = admin_anonymous.get("/api/scraper/operations?state=all&limit=10", timeout=10)
    assert_status(response, 401)


@pytest.mark.write
def test_seeded_series_draft_visible_in_operations(admin_user, seeded_series_draft):
    response = admin_user.session.get(
        "/api/scraper/operations?state=all&limit=100",
        timeout=10,
    )
    assert_status(response, 200)
    body = response.json()
    assert "items" in body
    assert "summary" in body
    assert "queue_depths" in body

    draft_id = seeded_series_draft["draft_id"]
    item = next((row for row in body["items"] if row["id"] == draft_id), None)
    assert item is not None
    assert item["operation_group"] in {
        "running", "awaiting_admin", "completed", "attention", "acknowledged"
    }
    assert isinstance(item.get("progress"), dict)

    invalid = admin_user.session.get(
        "/api/scraper/operations?state=not-a-state",
        timeout=10,
    )
    assert_status(invalid, 400)


@pytest.mark.write
def test_cancel_operation_archives_nonrunning_task(admin_user, seeded_series_draft, db):
    draft_id = seeded_series_draft["draft_id"]

    cancelled = admin_user.session.delete(
        f"/api/scraper/operations/{draft_id}",
        timeout=20,
    )
    assert_status(cancelled, 200)
    body = cancelled.json()
    assert body["removed_from_dashboard"] is True
    assert body["status"] == "cancelled"

    # Default dashboard hides acknowledged/archived operations immediately.
    operations = admin_user.session.get(
        "/api/scraper/operations?limit=100",
        timeout=10,
    )
    assert_status(operations, 200)
    assert all(item["id"] != draft_id for item in operations.json()["items"])

    # state=all is intentionally an audit/history view, so the operation remains.
    history = admin_user.session.get(
        "/api/scraper/operations?state=all&limit=100",
        timeout=10,
    )
    assert_status(history, 200)
    item = next((row for row in history.json()["items"] if row["id"] == draft_id), None)
    assert item is not None
    assert item["operation_group"] == "acknowledged"
    assert item["workflow_status"] == "cancelled"

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT workflow_status, acknowledged_at IS NOT NULL,
                   operation_cancel_requested_at IS NOT NULL
            FROM scraper_series_drafts WHERE id = %s::uuid
            """,
            (draft_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row == ("cancelled", True, True)


def test_cancel_operation_admin_only(admin_anonymous, seeded_series_draft):
    response = admin_anonymous.delete(
        f"/api/scraper/operations/{seeded_series_draft['draft_id']}",
        timeout=10,
    )
    assert_status(response, 401)


@pytest.mark.write
def test_cancel_active_operation_signals_worker_and_is_eventually_archived(
    admin_user, seeded_series_draft, db
):
    draft_id = seeded_series_draft["draft_id"]

    # Simulate an operation that has already been claimed by a worker. DELETE
    # archives it from the dashboard immediately and leaves a durable stop flag
    # that the recovery/finalizer consumes. History is deliberately retained.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET workflow_status = 'discovering',
                discovery_worker_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE id = %s::uuid
            """,
            (draft_id,),
        )

    cancelled = admin_user.session.delete(
        f"/api/scraper/operations/{draft_id}",
        timeout=20,
    )
    assert_status(cancelled, 200)
    body = cancelled.json()
    assert body["removed_from_dashboard"] is True
    assert body["status"] == "cancel_requested"

    operations = admin_user.session.get(
        "/api/scraper/operations?limit=100",
        timeout=10,
    )
    assert_status(operations, 200)
    assert all(item["id"] != draft_id for item in operations.json()["items"])

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT operation_cancel_requested_at IS NOT NULL, acknowledged_at IS NOT NULL
            FROM scraper_series_drafts
            WHERE id = %s::uuid
            """,
            (draft_id,),
        )
        marker = cur.fetchone()
    assert marker == (True, True)

    def finalized_by_backend_worker():
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT workflow_status, acknowledged_at IS NOT NULL,
                       discovery_worker_heartbeat_at IS NULL
                FROM scraper_series_drafts WHERE id = %s::uuid
                """,
                (draft_id,),
            )
            row = cur.fetchone()
            return bool(row and row[0] == "cancelled" and row[1] and row[2])

    assert wait_until(
        finalized_by_backend_worker,
        timeout=45,
        interval=1,
        description="active scraper cancellation finalization",
    )



@pytest.mark.write
def test_cancel_operation_detects_active_single_chapter_publisher(
    admin_user, seeded_series_draft, db
):
    draft_id = seeded_series_draft["draft_id"]
    chapter_id = seeded_series_draft["chapter_id"]

    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_draft_chapters
            SET publish_status = 'publishing',
                publish_progress = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s::uuid
            """,
            (
                '{"mode":"single","phase":"processing","percent":42}',
                chapter_id,
            ),
        )

    cancelled = admin_user.session.delete(
        f"/api/scraper/operations/{draft_id}", timeout=20
    )
    assert_status(cancelled, 200)
    body = cancelled.json()
    assert body["removed_from_dashboard"] is True
    assert body["status"] == "cancel_requested"

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT operation_cancel_requested_at IS NOT NULL, acknowledged_at IS NOT NULL
            FROM scraper_series_drafts
            WHERE id = %s::uuid
            """,
            (draft_id,),
        )
        marker = cur.fetchone()
    assert marker == (True, True)

    def finalized_by_recovery():
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT d.workflow_status, d.acknowledged_at IS NOT NULL,
                       c.publish_status, c.published_chapter_id IS NOT NULL
                FROM scraper_series_drafts d
                JOIN scraper_series_draft_chapters c ON c.draft_id=d.id
                WHERE d.id=%s::uuid AND c.id=%s::uuid
                """,
                (draft_id, chapter_id),
            )
            row = cur.fetchone()
            if not row:
                return False
            workflow_status, acknowledged, publish_status, published = row
            terminal_chapter = published or publish_status in {"cancelled", "published", "failed"}
            return workflow_status == "cancelled" and acknowledged and terminal_chapter

    assert wait_until(
        finalized_by_recovery,
        timeout=60,
        interval=1,
        description="single-chapter publish cancellation finalization",
    )


@pytest.mark.write
def test_workflow_status_is_lightweight_and_acknowledge_archives_operation(
    admin_user, seeded_series_draft, db
):
    draft_id = seeded_series_draft["draft_id"]

    status = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}/workflow-status",
        timeout=10,
    )
    assert_status(status, 200)
    body = status.json()
    assert body["id"] == draft_id
    assert isinstance(body.get("chapters"), list)
    assert body["chapters"]
    # Polling payload must expose counts/state, not potentially huge staged page arrays.
    assert "pages" not in body["chapters"][0]
    assert "page_count" in body["chapters"][0]

    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET workflow_status='failed',
                error_message='test terminal operation',
                updated_at=NOW()
            WHERE id=%s::uuid
            """,
            (draft_id,),
        )

    acknowledged = admin_user.session.post(
        f"/api/scraper/operations/{draft_id}/acknowledge",
        timeout=20,
    )
    assert_status(acknowledged, 200)
    ack = acknowledged.json()
    assert ack["removed_from_dashboard"] is True
    assert ack["status"] == "acknowledged"
    assert ack["history_retained"] is True
    assert ack.get("cleanup_job_id")

    default_view = admin_user.session.get(
        "/api/scraper/operations?limit=100", timeout=10
    )
    assert_status(default_view, 200)
    assert all(item["id"] != draft_id for item in default_view.json()["items"])

    history = admin_user.session.get(
        "/api/scraper/operations?state=acknowledged&limit=100", timeout=10
    )
    assert_status(history, 200)
    item = next((row for row in history.json()["items"] if row["id"] == draft_id), None)
    assert item is not None
    assert item["workflow_status"] == "failed"
    assert item["operation_group"] == "acknowledged"

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT d.acknowledged_at IS NOT NULL, d.cover_staging_path IS NULL,
                   COALESCE(bool_and(c.pages = '[]'::jsonb), TRUE)
            FROM scraper_series_drafts d
            LEFT JOIN scraper_series_draft_chapters c ON c.draft_id=d.id
            WHERE d.id=%s::uuid
            GROUP BY d.id
            """,
            (draft_id,),
        )
        row = cur.fetchone()
    assert row == (True, True, True)

