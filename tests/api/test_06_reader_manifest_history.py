from helpers import assert_status
from reading_helpers import open_chapter, checkpoint_payload


def test_reader_manifest_has_tokens(anonymous, seed_content):
    response = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/ch-1",
        timeout=15,
    )
    assert_status(response, 200)

    body = response.json()
    assert body["series_id"] == seed_content["series_id"]
    assert body["chapter_slug"] == "ch-1"
    assert body["page_count"] == 2
    assert len(body["pages"]) == 2
    assert body["chapter_token"]


def test_reader_missing_chapter_404(anonymous, seed_content):
    response = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/missing-chapter",
        timeout=10,
    )
    assert_status(response, 404)


def test_progress_owns_history_and_reader_manifest_is_read_only(
    anonymous, regular_user, seed_content, db
):
    unauth = anonymous.get("/api/progress/history", timeout=10)
    assert_status(unauth, 401)

    # Start from canonical DB state. A Reader manifest GET must never recreate
    # these rows: prefetch/retry/refresh is a read operation, not progress.
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (regular_user.user_id, seed_content["series_id"]),
        )
        cur.execute(
            "DELETE FROM reading_progress WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (regular_user.user_id, seed_content["series_id"]),
        )
        cur.execute(
            "DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (regular_user.user_id, seed_content["series_id"]),
        )

    read = regular_user.session.get(
        f"/api/reader/{seed_content['series_slug']}/ch-2",
        timeout=15,
    )
    assert_status(read, 200)

    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (regular_user.user_id, seed_content["series_id"]),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM reading_progress WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (regular_user.user_id, seed_content["series_id"]),
        )
        assert cur.fetchone()[0] == 0

    path = f"/api/progress/{seed_content['series_slug']}/ch-2"
    opened = open_chapter(regular_user.session, path, 0)

    # Both canonical facts must exist before the successful open response.
    with db.cursor() as cur:
        cur.execute(
            "SELECT chapter_id::text FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid ORDER BY last_read_at DESC LIMIT 1",
            (regular_user.user_id, seed_content["series_id"]),
        )
        stored = cur.fetchone()
        assert stored is not None
        assert stored[0] == seed_content["chapter_ids"]["ch-2"]

    # History membership is synchronous and does not depend on a separate
    # resume-state delivery path merely to know that this series was visited.
    history = regular_user.session.get("/api/progress/history", timeout=15)
    assert_status(history, 200)
    history_items = history.json()
    assert any(item.get("series_id") == seed_content["series_id"] for item in history_items)

    library = regular_user.session.get("/api/social/library", timeout=15)
    assert_status(library, 200)
    library_body = library.json()
    assert library_body["summary"]["history"] >= 1
    assert any(item.get("series_id") == seed_content["series_id"] for item in library_body["items"])

    commit = regular_user.session.post(
        f"/api/progress/{seed_content['series_slug']}/ch-2/commit",
        json=checkpoint_payload(opened, 2, 1.0, completed_page=2),
        timeout=15,
    )
    assert_status(commit, 200)

    # Commit persists resume and ledger state together and is immediately visible.
    history = regular_user.session.get("/api/progress/history", timeout=15)
    assert_status(history, 200)
    assert any(item.get("series_id") == seed_content["series_id"] for item in history.json())

    state = regular_user.session.get(
        f"/api/progress/series/{seed_content['series_slug']}/state",
        timeout=15,
    )
    assert_status(state, 200)
    body = state.json()
    assert seed_content["chapter_ids"]["ch-2"] in body.get("read_chapter_ids", [])
    assert seed_content["chapter_ids"]["ch-2"] in body.get("completed_chapter_ids", [])


def test_reader_prev_next_navigation_boundaries(anonymous, seed_content):
    first = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/ch-1",
        timeout=15,
    )
    assert_status(first, 200)
    first_body = first.json()
    assert first_body["prev_chapter"] is None
    assert first_body["next_chapter"] == {"slug": "ch-2", "chapter_number": 2}

    last = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/ch-2",
        timeout=15,
    )
    assert_status(last, 200)
    last_body = last.json()
    assert last_body["prev_chapter"] == {"slug": "ch-1", "chapter_number": 1}
    assert last_body["next_chapter"] is None
