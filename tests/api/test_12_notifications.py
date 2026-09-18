from helpers import assert_status


def test_notification_count_list_mark_read(
    regular_user,
    notification_factory,
):
    notification_id = notification_factory(read=False)

    count = regular_user.session.get("/api/notifications/count", timeout=10)
    assert_status(count, 200)
    assert count.json()["unread"] >= 1

    listing = regular_user.session.get(
        "/api/notifications",
        params={"unread_only": "true"},
        timeout=10,
    )
    assert_status(listing, 200)
    assert any(x["id"] == notification_id for x in listing.json())

    marked = regular_user.session.post(
        f"/api/notifications/{notification_id}/read",
        timeout=10,
    )
    assert_status(marked, 200)
    assert marked.json()["marked"] is True

    missing = regular_user.session.post(
        "/api/notifications/00000000-0000-4000-8000-000000000000/read",
        timeout=10,
    )
    assert_status(missing, 404)


def test_notification_read_all_and_admin_stats(
    regular_user,
    admin_regular_user,
    admin_user,
    notification_factory,
):
    notification_factory(read=False)
    notification_factory(read=False)

    read_all = regular_user.session.post(
        "/api/notifications/read-all",
        timeout=10,
    )
    assert_status(read_all, 200)
    assert read_all.json()["marked"] >= 2

    regular_stats = admin_regular_user.session.get(
        "/api/notifications/admin/stats",
        timeout=10,
    )
    assert_status(regular_stats, 403)

    admin_stats = admin_user.session.get(
        "/api/notifications/admin/stats",
        timeout=10,
    )
    assert_status(admin_stats, 200)


def test_notifications_require_auth(anonymous):
    assert_status(anonymous.get("/api/notifications", timeout=10), 401)
    assert_status(anonymous.get("/api/notifications/count", timeout=10), 401)
