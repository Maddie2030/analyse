from helpers import assert_status


def test_comment_list_requires_discussion_target(anonymous):
    response = anonymous.get("/api/social/comments", timeout=10)
    assert_status(response, 400)


def test_comment_create_reply_depth_and_delete(
    regular_user,
    admin_user,
    seed_content,
):
    chapter_id = seed_content["chapter_ids"]["ch-1"]

    empty = regular_user.session.post(
        "/api/social/comments",
        json={
            "content": " ",
            "chapter_id": chapter_id,
        },
        timeout=10,
    )
    assert_status(empty, 422)

    root = regular_user.session.post(
        "/api/social/comments",
        json={
            "content": "Root pytest comment",
            "chapter_id": chapter_id,
        },
        timeout=10,
    )
    assert_status(root, 201)
    root_id = root.json()["id"]

    reply = regular_user.session.post(
        "/api/social/comments",
        json={
            "content": "Reply pytest comment",
            "chapter_id": chapter_id,
            "parent_id": root_id,
        },
        timeout=10,
    )
    assert_status(reply, 201)
    reply_id = reply.json()["id"]

    nested = regular_user.session.post(
        "/api/social/comments",
        json={
            "content": "Nested reply level two",
            "series_id": seed_content["series_id"],
            "chapter_id": chapter_id,
            "parent_id": reply_id,
        },
        timeout=10,
    )
    assert_status(nested, 201)
    nested_id = nested.json()["id"]

    listing = regular_user.session.get(
        "/api/social/comments",
        params={"chapterId": chapter_id},
        timeout=10,
    )
    assert_status(listing, 200)
    assert listing.json()["total"] >= 2

    other_delete = admin_user.session.delete(
        f"/api/social/comments/{root_id}",
        timeout=10,
    )
    assert_status(other_delete, 404)

    assert_status(
        regular_user.session.delete(
            f"/api/social/comments/{nested_id}",
            timeout=10,
        ),
        204,
    )
    assert_status(
        regular_user.session.delete(
            f"/api/social/comments/{reply_id}",
            timeout=10,
        ),
        204,
    )
    assert_status(
        regular_user.session.delete(
            f"/api/social/comments/{root_id}",
            timeout=10,
        ),
        204,
    )


def test_comment_create_requires_auth(anonymous, seed_content):
    response = anonymous.post(
        "/api/social/comments",
        json={
            "content": "Unauthorized",
            "series_id": seed_content["series_id"],
        },
        timeout=10,
    )
    assert_status(response, 401)
