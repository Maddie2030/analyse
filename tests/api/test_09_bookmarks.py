from helpers import assert_status


def test_bookmark_lifecycle(regular_user, seed_content):
    series_id = seed_content["series_id"]
    base = f"/api/social/bookmarks/{series_id}"

    first = regular_user.session.post(base, timeout=10)
    assert_status(first, 201)
    assert first.json()["series_id"] == series_id

    second = regular_user.session.post(base, timeout=10)
    assert_status(second, 200)
    assert second.json()["id"] == first.json()["id"]

    status = regular_user.session.get(f"{base}/status", timeout=10)
    assert_status(status, 200)
    assert status.json()["bookmarked"] is True

    listing = regular_user.session.get("/api/social/bookmarks", timeout=10)
    assert_status(listing, 200)
    assert any(x["series_id"] == series_id for x in listing.json())

    delete = regular_user.session.delete(base, timeout=10)
    assert_status(delete, 204)

    again = regular_user.session.delete(base, timeout=10)
    assert_status(again, 404)


def test_bookmark_requires_auth(anonymous, seed_content):
    response = anonymous.post(
        f"/api/social/bookmarks/{seed_content['series_id']}",
        timeout=10,
    )
    assert_status(response, 401)


def test_series_metrics_and_one_rating_per_user(regular_user, seed_content):
    series_id = seed_content["series_id"]
    before = regular_user.session.get(f"/api/social/series/{series_id}/metrics", timeout=10)
    assert_status(before, 200)

    rated = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 4},
        timeout=10,
    )
    assert_status(rated, 200)
    assert rated.json()["user_rating"] == 4
    count = rated.json()["rating_count"]

    updated = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 5},
        timeout=10,
    )
    assert_status(updated, 200)
    assert updated.json()["user_rating"] == 5
    assert updated.json()["rating_count"] == count


def test_series_metrics_batch(anonymous, seed_content):
    response = anonymous.post(
        "/api/social/series/metrics-batch",
        json={"series_ids": [seed_content["series_id"]]},
        timeout=10,
    )
    assert_status(response, 200)
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["series_id"] == seed_content["series_id"]
    assert "bookmark_count" in items[0]
    assert "rating_average" in items[0]


def test_rating_average_across_users(
    anonymous,
    regular_user,
    temp_user_factory,
    seed_content,
):
    series_id = seed_content["series_id"]
    second_user = temp_user_factory("rating_peer")

    first = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 5},
        timeout=10,
    )
    assert_status(first, 200)

    second = second_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 3},
        timeout=10,
    )
    assert_status(second, 200)

    public_metrics = anonymous.get(
        f"/api/social/series/{series_id}/metrics",
        timeout=10,
    )
    assert_status(public_metrics, 200)
    body = public_metrics.json()
    assert body["rating_count"] == 2
    assert body["rating_average"] == 4.0
    assert body["user_rating"] is None

    changed = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 4},
        timeout=10,
    )
    assert_status(changed, 200)
    assert changed.json()["rating_count"] == 2
    assert changed.json()["rating_average"] == 3.5
    assert changed.json()["user_rating"] == 4

    for identity in (regular_user, second_user):
        cleared = identity.session.delete(
            f"/api/social/series/{series_id}/rating",
            timeout=10,
        )
        assert_status(cleared, 204)


def test_public_series_aggregates_visible_to_anonymous_guests(
    anonymous,
    regular_user,
    seed_content,
):
    series_id = seed_content["series_id"]

    bookmarked = regular_user.session.post(
        f"/api/social/bookmarks/{series_id}",
        timeout=10,
    )
    assert bookmarked.status_code in (200, 201)

    subscribed = regular_user.session.post(
        f"/api/social/subscriptions/{series_id}",
        timeout=10,
    )
    assert subscribed.status_code in (200, 201)

    rated = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 5},
        timeout=10,
    )
    assert_status(rated, 200)

    public = anonymous.get(
        f"/api/social/series/{series_id}/metrics",
        timeout=10,
    )
    assert_status(public, 200)
    body = public.json()
    assert body["bookmark_count"] >= 1
    assert body["subscription_count"] >= 1
    assert body["rating_count"] >= 1
    assert body["rating_average"] is not None
    assert body["user_rating"] is None

    batch = anonymous.post(
        "/api/social/series/metrics-batch",
        json={"series_ids": [series_id]},
        timeout=10,
    )
    assert_status(batch, 200)
    item = batch.json()["items"][0]
    assert item["bookmark_count"] >= 1
    assert item["subscription_count"] >= 1
    assert item["rating_count"] >= 1
    assert item["rating_average"] is not None
    assert item["user_rating"] is None
