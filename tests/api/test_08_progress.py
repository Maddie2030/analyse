from uuid import uuid4

from helpers import assert_status
from reading_helpers import open_chapter, checkpoint_payload


def test_progress_requires_auth(anonymous, seed_content):
    path = f"/api/progress/{seed_content['series_slug']}/ch-1"

    get = anonymous.get(path, timeout=10)
    assert_status(get, 401)

    commit = anonymous.post(
        f"{path}/commit",
        json={"last_page": 1, "scroll_position": 0.25, "command_id": str(uuid4()), "session_generation": 1, "command_sequence": 1, "completed": False, "completed_page": 0},
        timeout=10,
    )
    assert_status(commit, 401)


def test_progress_roundtrip_and_clamp(regular_user, seed_content):
    path = f"/api/progress/{seed_content['series_slug']}/ch-1"

    initial = regular_user.session.get(path, timeout=15)
    assert_status(initial, 200)

    opened = open_chapter(regular_user.session, path, initial.json()["revision"])
    save = regular_user.session.post(
        f"{path}/commit",
        json=checkpoint_payload(opened, 999, 0.625),
        timeout=15,
    )
    assert_status(save, 200)
    assert save.json()["last_page"] == 2
    assert save.json()["revision"] == opened["revision"] + 1
    assert save.json()["accepted"] is True

    read = regular_user.session.get(path, timeout=15)
    assert_status(read, 200)
    assert read.json()["last_page"] == 2
    assert abs(float(read.json()["scroll_position"]) - 0.625) < 0.0001


def test_completion_is_explicit_and_requires_the_chapter_end(
    temp_user_factory, seed_content, db
):
    user = temp_user_factory("progress_explicit_completion")
    path = f"/api/progress/{seed_content['series_slug']}/ch-1/commit"
    chapter_id = seed_content["chapter_ids"]["ch-1"]

    try:
        opened = open_chapter(user.session, path.removesuffix("/commit"), 0)
        checkpoint_only = user.session.post(
            path,
            json=checkpoint_payload(opened, 999, 1.0),
            timeout=15,
        )
        assert_status(checkpoint_only, 200)
        with db.cursor() as cur:
            cur.execute(
                "SELECT completed FROM chapter_reads WHERE user_id=%s::uuid AND chapter_id=%s::uuid",
                (user.user_id, chapter_id),
            )
            assert cur.fetchone() == (False,)

        premature = user.session.post(
            path,
            json=checkpoint_payload(checkpoint_only.json(), 1, 0.5, completed_page=1),
            timeout=15,
        )
        assert_status(premature, 422)

        completed = user.session.post(
            path,
            json=checkpoint_payload(checkpoint_only.json(), 2, 1.0, completed_page=2),
            timeout=15,
        )
        assert_status(completed, 200)
        with db.cursor() as cur:
            cur.execute(
                "SELECT completed, completed_at IS NOT NULL FROM chapter_reads WHERE user_id=%s::uuid AND chapter_id=%s::uuid",
                (user.user_id, chapter_id),
            )
            assert cur.fetchone() == (True, True)
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


def test_progress_rejects_bad_payloads(regular_user, seed_content):
    path = f"/api/progress/{seed_content['series_slug']}/ch-1"

    low_page = regular_user.session.post(
        f"{path}/commit",
        json={"last_page": 0, "scroll_position": 0.2, "command_id": str(uuid4()), "session_generation": 1, "command_sequence": 1, "completed": False, "completed_page": 0},
        timeout=10,
    )
    assert_status(low_page, 422)

    bad_scroll = regular_user.session.post(
        f"{path}/commit",
        json={"last_page": 1, "scroll_position": 1.5, "command_id": str(uuid4()), "session_generation": 1, "command_sequence": 1, "completed": False, "completed_page": 0},
        timeout=10,
    )
    assert_status(bad_scroll, 422)

    unknown = regular_user.session.post(
        f"{path}/commit",
        json={
            "last_page": 1,
            "scroll_position": 0.2,
            "command_id": str(uuid4()), "session_generation": 1, "command_sequence": 1,
            "unexpected": True,
        },
        timeout=10,
    )
    assert_status(unknown, 400)


def test_progress_missing_chapter(regular_user, seed_content):
    response = regular_user.session.get(
        f"/api/progress/{seed_content['series_slug']}/missing",
        timeout=10,
    )
    assert_status(response, 404)
