from helpers import assert_status


def test_subscription_lifecycle(regular_user, seed_content):
    series_id = seed_content["series_id"]
    base = f"/api/social/subscriptions/{series_id}"

    first = regular_user.session.post(base, timeout=10)
    assert_status(first, 201)
    assert first.json()["unread_count"] == 0

    second = regular_user.session.post(base, timeout=10)
    assert_status(second, 200)
    assert second.json()["id"] == first.json()["id"]

    status = regular_user.session.get(f"{base}/status", timeout=10)
    assert_status(status, 200)
    assert status.json()["subscribed"] is True

    listing = regular_user.session.get("/api/social/subscriptions", timeout=10)
    assert_status(listing, 200)
    assert any(x["series_id"] == series_id for x in listing.json())

    delete = regular_user.session.delete(base, timeout=10)
    assert_status(delete, 204)

    again = regular_user.session.delete(base, timeout=10)
    assert_status(again, 404)


def test_subscription_requires_auth(anonymous, seed_content):
    response = anonymous.post(
        f"/api/social/subscriptions/{seed_content['series_id']}",
        timeout=10,
    )
    assert_status(response, 401)
