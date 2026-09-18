import json
import uuid

import pytest

from helpers import assert_status


@pytest.mark.write
def test_existing_series_draft_manual_pages_and_publish(
    admin_user,
    seeded_existing_draft,
    image_bytes,
):
    draft_id = seeded_existing_draft["draft_id"]

    uploaded = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/pages/upload",
        files={"file": ("manual-001.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(uploaded, 200)
    pages = uploaded.json()["pages"]
    assert len(pages) == 1
    page_id = pages[0]["id"]

    preview = admin_user.session.get(
        f"/api/scraper/drafts/{draft_id}/pages/{page_id}/preview",
        timeout=20,
    )
    assert_status(preview, 200)
    assert preview.content

    reordered = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/pages/reorder",
        json={"page_ids": [page_id]},
        timeout=10,
    )
    assert_status(reordered, 200)
    assert reordered.json()["pages"][0]["id"] == page_id

    # A draft with no failed downloads is a successful no-op retry.
    retry_failed = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/pages/retry-failed",
        timeout=20,
    )
    assert_status(retry_failed, 200)
    assert retry_failed.json()["pages"][0]["id"] == page_id

    # Manual URL ingestion/replacement must apply the same SSRF protection as
    # discovery. These requests reach the concrete sub-routes without relying
    # on a third-party test site.
    add_private = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/pages/from-url",
        json={"url": "http://127.0.0.1:9/private.png", "position": 1},
        timeout=10,
    )
    assert_status(add_private, 400)

    replace_private = admin_user.session.put(
        f"/api/scraper/drafts/{draft_id}/pages/{page_id}/from-url",
        json={"url": "http://127.0.0.1:9/replacement.png"},
        timeout=10,
    )
    assert_status(replace_private, 400)

    removed = admin_user.session.delete(
        f"/api/scraper/drafts/{draft_id}/pages/{page_id}",
        timeout=15,
    )
    assert_status(removed, 200)
    assert removed.json()["pages"] == []

    # Re-add one valid page and exercise the complete existing-series publish
    # path. The fixture finalizer removes the produced chapter and storage.
    restored = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/pages/upload",
        files={"file": ("manual-publish.png", image_bytes, "image/png")},
        timeout=30,
    )
    assert_status(restored, 200)
    assert len(restored.json()["pages"]) == 1

    published = admin_user.session.post(
        f"/api/scraper/drafts/{draft_id}/publish",
        timeout=60,
    )
    assert_status(published, 200)
    body = published.json()
    assert body["status"] == "published"
    assert body["series"]["id"] == seeded_existing_draft["series_id"]
    assert body["chapter"]["slug"] == seeded_existing_draft["chapter_slug"]
    assert body["pages"]


@pytest.mark.write
def test_scraper_operation_unacknowledge_and_retry_discovery_contracts(
    admin_user,
    seeded_series_draft,
    db,
):
    draft_id = seeded_series_draft["draft_id"]

    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET acknowledged_at=NOW(), acknowledged_by=%s::uuid, updated_at=NOW()
            WHERE id=%s::uuid
            """,
            (admin_user.user_id, draft_id),
        )

    unacknowledged = admin_user.session.post(
        f"/api/scraper/operations/{draft_id}/unacknowledge",
        timeout=15,
    )
    assert_status(unacknowledged, 200)
    assert unacknowledged.json()["id"] == draft_id

    with db.cursor() as cur:
        cur.execute(
            "SELECT acknowledged_at IS NULL FROM scraper_series_drafts WHERE id=%s::uuid",
            (draft_id,),
        )
        assert cur.fetchone()[0] is True

    # A healthy draft is not eligible for discovery retry.
    guarded = admin_user.session.post(
        f"/api/scraper/operations/{draft_id}/retry-discovery",
        timeout=15,
    )
    assert_status(guarded, 409)

    # Exercise the positive retry transition as well. The source is deliberately
    # example.invalid; a worker may subsequently fail it, but accepting the retry
    # must durably leave the previous failed state and clear acknowledgement.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET workflow_status='failed',
                error_message='pytest discovery failure',
                discovery_progress=%s::jsonb,
                published_series_id=NULL,
                acknowledged_at=NOW(),
                acknowledged_by=%s::uuid,
                updated_at=NOW()
            WHERE id=%s::uuid
            """,
            (
                json.dumps({"phase": "failed", "percent": 0, "message": "pytest failure"}),
                admin_user.user_id,
                draft_id,
            ),
        )

    retried = admin_user.session.post(
        f"/api/scraper/operations/{draft_id}/retry-discovery",
        timeout=20,
    )
    assert_status(retried, 200)
    assert retried.json()["id"] == draft_id

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT workflow_status, acknowledged_at IS NULL
            FROM scraper_series_drafts WHERE id=%s::uuid
            """,
            (draft_id,),
        )
        workflow_status, ack_cleared = cur.fetchone()
    assert workflow_status in {"queued_discovery", "discovering", "failed"}
    assert ack_cleared is True


@pytest.mark.write
def test_series_draft_status_events_manual_url_guards_and_publish_cancel(
    admin_user,
    seeded_series_draft,
    db,
):
    draft_id = seeded_series_draft["draft_id"]
    chapter_id = seeded_series_draft["chapter_id"]

    workflow = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}/workflow-status",
        timeout=10,
    )
    assert_status(workflow, 200)
    assert workflow.json()["id"] == draft_id
    assert "pages" not in workflow.json()["chapters"][0]

    events = admin_user.session.get(
        f"/api/scraper/series-drafts/{draft_id}/events",
        params={"limit": 10},
        timeout=10,
    )
    assert_status(events, 200)
    event_body = events.json()
    assert event_body["operation_id"] == draft_id
    assert isinstance(event_body.get("items"), list)

    cover_private = admin_user.session.put(
        f"/api/scraper/series-drafts/{draft_id}/cover/from-url",
        json={"url": "http://127.0.0.1:9/private-cover.png"},
        timeout=10,
    )
    assert_status(cover_private, 400)

    page_private = admin_user.session.post(
        f"/api/scraper/series-drafts/chapters/{chapter_id}/pages/from-url",
        json={"url": "http://127.0.0.1:9/private-page.png", "position": 1},
        timeout=10,
    )
    assert_status(page_private, 400)

    # Model a publish that is queued but not yet claimed. Cancellation should be
    # immediate and must not delete any already committed production chapter.
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE scraper_series_drafts
            SET workflow_status='queued_publish',
                publish_cancel_requested_at=NULL,
                publish_finished_at=NULL,
                publish_progress='{}'::jsonb,
                updated_at=NOW()
            WHERE id=%s::uuid
            """,
            (draft_id,),
        )

    cancelled = admin_user.session.post(
        f"/api/scraper/series-drafts/{draft_id}/publish/cancel",
        timeout=20,
    )
    assert_status(cancelled, 200)
    assert cancelled.json()["workflow_status"] == "cancelled"

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT workflow_status, publish_cancel_requested_at IS NOT NULL
            FROM scraper_series_drafts WHERE id=%s::uuid
            """,
            (draft_id,),
        )
        assert cur.fetchone() == ("cancelled", True)


def test_social_viewer_state_matches_authenticated_series_state(
    anonymous,
    temp_user_factory,
    seed_content,
):
    series_id = seed_content["series_id"]
    viewer = temp_user_factory("viewer_state")

    public_state = anonymous.get(
        f"/api/social/series/{series_id}/viewer-state",
        timeout=10,
    )
    assert_status(public_state, 200)
    assert public_state.json()["series_id"] == series_id
    assert public_state.json()["bookmarked"] is False
    assert public_state.json()["subscribed"] is False

    assert_status(
        viewer.session.post(f"/api/social/bookmarks/{series_id}", timeout=10),
        {200, 201},
    )
    assert_status(
        viewer.session.post(f"/api/social/subscriptions/{series_id}", timeout=10),
        {200, 201},
    )
    assert_status(
        viewer.session.put(
            f"/api/social/series/{series_id}/rating",
            json={"rating": 4},
            timeout=10,
        ),
        200,
    )

    state = viewer.session.get(
        f"/api/social/series/{series_id}/viewer-state",
        timeout=10,
    )
    assert_status(state, 200)
    body = state.json()
    assert body["series_id"] == series_id
    assert body["bookmarked"] is True
    assert body["subscribed"] is True
    assert body.get("user_rating") == 4
