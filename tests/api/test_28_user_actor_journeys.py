from __future__ import annotations

from helpers import assert_status
from reading_helpers import checkpoint_payload, open_chapter

import pytest


def _expect_status(journey, action, response, expected, intended):
    allowed = {expected} if isinstance(expected, int) else set(expected)
    journey.assert_true(
        action,
        response.status_code in allowed,
        intended=intended,
        observed={"status": response.status_code, "body": response.text[:300]},
    )


@pytest.mark.journey
@pytest.mark.write
def test_user_account_profile_session_journey(temp_user_factory, journey):
    user = temp_user_factory("actor_account")

    profile = user.session.get("/api/auth/profile", timeout=10)
    _expect_status(journey, "profile-load", profile, 200, "authenticated user can load their profile")
    journey.assert_equal(
        "profile-identity",
        profile.json()["id"],
        user.user_id,
        intended="profile belongs to the newly registered diagnostic user",
    )

    avatar = user.session.put("/api/auth/profile", json={"avatar_key": "bard"}, timeout=10)
    _expect_status(journey, "profile-avatar-update", avatar, 200, "user can select an allowed avatar")
    journey.assert_equal(
        "profile-avatar-persisted",
        avatar.json().get("avatar_key"),
        "bard",
        intended="selected avatar is persisted",
    )

    logout = user.session.post("/api/auth/logout", timeout=10)
    _expect_status(journey, "logout", logout, 200, "logout invalidates the current authenticated session")
    after_logout = user.session.get("/api/auth/profile", timeout=10)
    _expect_status(journey, "logout-session-invalidated", after_logout, 401, "profile becomes inaccessible after logout")

    login = user.session.post(
        "/api/auth/login",
        json={"username_or_email": user.email, "password": user.password, "turnstile_token": ""},
        timeout=15,
    )
    _expect_status(journey, "login", login, 200, "user can log back in with the registered credentials")
    restored = user.session.get("/api/auth/profile", timeout=10)
    _expect_status(journey, "profile-after-login", restored, 200, "profile is available after login")
    journey.assert_equal(
        "profile-state-survives-login",
        restored.json().get("avatar_key"),
        "bard",
        intended="profile changes survive logout/login",
    )


@pytest.mark.journey
@pytest.mark.write
def test_user_discovery_engagement_library_journey(temp_user_factory, seed_content, journey):
    user = temp_user_factory("actor_engagement")
    series_id = seed_content["series_id"]
    slug = seed_content["series_slug"]
    comment_id = None

    try:
        search = user.session.get("/api/catalog/series", params={"search": slug.replace("-", " "), "limit": 100}, timeout=10)
        _expect_status(journey, "catalog-search", search, 200, "user can search the catalog")
        journey.assert_true(
            "catalog-search-result",
            any(row.get("id") == series_id for row in search.json()),
            intended="search result contains the expected series",
            observed=[row.get("id") for row in search.json()],
        )

        detail = user.session.get(f"/api/catalog/series/{slug}", timeout=10)
        _expect_status(journey, "series-detail", detail, 200, "user can open series details")
        journey.assert_equal("series-detail-id", detail.json().get("id"), series_id, intended="detail page resolves the selected series")

        genres = user.session.get("/api/catalog/genres", timeout=10)
        _expect_status(journey, "browse-genres", genres, 200, "user can browse catalog genres")
        journey.assert_true("genre-list-nonempty", bool(genres.json()), intended="genre browse returns taxonomy data", observed={"count": len(genres.json())})

        tags = user.session.get("/api/catalog/tags", timeout=10)
        _expect_status(journey, "browse-tags", tags, 200, "user can browse catalog tags")
        journey.assert_true("tag-list-nonempty", bool(tags.json()), intended="tag browse returns taxonomy data", observed={"count": len(tags.json())})

        discover = user.session.get("/api/catalog/discover", timeout=10)
        _expect_status(journey, "catalog-discover", discover, 200, "user can open the catalog discovery surface")
        journey.assert_true("discover-sections", set(discover.json()) >= {"popular", "recent", "new"}, intended="discovery returns popular, recent and new sections", observed=list(discover.json()))

        chapter_detail = user.session.get(f"/api/catalog/series/{slug}/chapters/ch-1", timeout=10)
        _expect_status(journey, "chapter-detail", chapter_detail, 200, "user can open a chapter detail")
        journey.assert_equal("chapter-detail-slug", chapter_detail.json().get("slug"), "ch-1", intended="chapter detail resolves the requested chapter")

        bookmark = user.session.post(f"/api/social/bookmarks/{series_id}", timeout=10)
        _expect_status(journey, "bookmark-series", bookmark, {200, 201}, "user can bookmark the series")
        bookmark_status = user.session.get(f"/api/social/bookmarks/{series_id}/status", timeout=10)
        _expect_status(journey, "bookmark-status", bookmark_status, 200, "bookmark status is readable")
        journey.assert_true("bookmark-persisted", bookmark_status.json().get("bookmarked") is True, intended="bookmark is persisted", observed=bookmark_status.json())

        bookmarks = user.session.get("/api/social/bookmarks", timeout=10)
        _expect_status(journey, "list-bookmarks", bookmarks, 200, "user can list bookmarked series")
        journey.assert_true("bookmark-list-contains-series", any(row.get("series_id") == series_id for row in bookmarks.json()), intended="bookmarked series appears in bookmark listing", observed={"count": len(bookmarks.json())})

        subscribe = user.session.post(f"/api/social/subscriptions/{series_id}", timeout=10)
        _expect_status(journey, "subscribe-series", subscribe, {200, 201}, "user can subscribe to the series")
        subscription_status = user.session.get(f"/api/social/subscriptions/{series_id}/status", timeout=10)
        _expect_status(journey, "subscription-status", subscription_status, 200, "subscription status is readable")
        journey.assert_true("subscription-persisted", subscription_status.json().get("subscribed") is True, intended="subscription is persisted", observed=subscription_status.json())

        subscriptions = user.session.get("/api/social/subscriptions", timeout=10)
        _expect_status(journey, "list-subscriptions", subscriptions, 200, "user can list subscribed series")
        journey.assert_true("subscription-list-contains-series", any(row.get("series_id") == series_id for row in subscriptions.json()), intended="subscribed series appears in subscription listing", observed={"count": len(subscriptions.json())})

        rating = user.session.put(f"/api/social/series/{series_id}/rating", json={"rating": 4}, timeout=10)
        _expect_status(journey, "rate-series", rating, 200, "user can rate a series")
        journey.assert_equal("rating-persisted", rating.json().get("user_rating"), 4, intended="the user's rating is persisted")

        metrics = user.session.get(f"/api/social/series/{series_id}/metrics", timeout=10)
        _expect_status(journey, "series-metrics", metrics, 200, "user can see aggregate engagement metrics")
        journey.assert_true("series-metrics-rating", metrics.json().get("rating_count", 0) >= 1, intended="rating contributes to public series metrics", observed=metrics.json())

        batch_metrics = user.session.post("/api/social/series/metrics-batch", json={"series_ids": [series_id]}, timeout=10)
        _expect_status(journey, "series-metrics-batch", batch_metrics, 200, "client can fetch metrics for multiple series in one request")
        journey.assert_true("series-metrics-batch-contains-series", any(row.get("series_id") == series_id for row in batch_metrics.json().get("items", [])), intended="metrics batch contains the selected series", observed=batch_metrics.json())

        viewer = user.session.get(f"/api/social/series/{series_id}/viewer-state", timeout=10)
        _expect_status(journey, "viewer-state", viewer, 200, "user can retrieve their series engagement state")
        viewer_body = viewer.json()
        journey.assert_true(
            "viewer-state-composed",
            viewer_body.get("bookmarked") is True and viewer_body.get("subscribed") is True and viewer_body.get("user_rating") == 4,
            intended="viewer state composes bookmark, subscription and rating",
            observed=viewer_body,
        )

        comment = user.session.post(
            "/api/social/comments",
            json={"content": "Actor journey comment", "series_id": series_id},
            timeout=10,
        )
        _expect_status(journey, "post-series-comment", comment, 201, "user can post a series-level comment")
        comment_id = comment.json()["id"]
        comments = user.session.get("/api/social/comments", params={"seriesId": series_id}, timeout=10)
        _expect_status(journey, "list-series-comments", comments, 200, "series discussion can be listed")
        journey.assert_true(
            "comment-visible",
            any(row.get("id") == comment_id for row in comments.json().get("items", [])),
            intended="new comment becomes visible in the series discussion",
            observed={"comment_id": comment_id, "total": comments.json().get("total")},
        )

        library = user.session.get("/api/social/library", timeout=15)
        _expect_status(journey, "smart-library", library, 200, "user can open Smart Library")
        item = next((row for row in library.json().get("items", []) if row.get("series_id") == series_id), None)
        journey.assert_true(
            "library-engagement-state",
            bool(item and item.get("bookmarked") and item.get("followed")),
            intended="bookmarked/subscribed series appears in Smart Library with engagement state",
            observed=item,
        )
    finally:
        if comment_id:
            response = user.session.delete(f"/api/social/comments/{comment_id}", timeout=10)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)
        for method, path in (
            ("delete", f"/api/social/series/{series_id}/rating"),
            ("delete", f"/api/social/subscriptions/{series_id}"),
            ("delete", f"/api/social/bookmarks/{series_id}"),
        ):
            response = getattr(user.session, method)(path, timeout=10)
            if response.status_code not in {204, 404}:
                assert_status(response, 204)


@pytest.mark.journey
@pytest.mark.write
def test_user_reader_progress_history_notification_journey(temp_user_factory, seed_content, db, journey):
    user = temp_user_factory("actor_reader")
    series_id = seed_content["series_id"]
    slug = seed_content["series_slug"]
    chapter_id = seed_content["chapter_ids"]["ch-1"]
    notification_ids = []

    try:
        manifest = user.session.get(f"/api/reader/{slug}/ch-1", timeout=15)
        _expect_status(journey, "open-reader-manifest", manifest, 200, "user can open a published chapter")
        manifest_body = manifest.json()
        journey.assert_true(
            "reader-manifest-pages",
            len(manifest_body.get("pages", [])) >= 2 and bool(manifest_body.get("chapter_token")),
            intended="reader manifest contains pages and a chapter-scoped token",
            observed={"page_count": manifest_body.get("page_count"), "token_present": bool(manifest_body.get("chapter_token"))},
        )

        page = manifest_body["pages"][0]
        image = user.session.get(f"/images/{page['image_path']}", params={"token": manifest_body["chapter_token"]}, timeout=20)
        _expect_status(journey, "stream-reader-page", image, 200, "chapter token authorizes the reader image")
        journey.assert_true("reader-page-bytes", bool(image.content), intended="authorized page returns image bytes", observed={"bytes": len(image.content)})

        progress_path = f"/api/progress/{slug}/ch-1"
        opened = open_chapter(user.session, progress_path, 0)
        journey.record("record-chapter-open", intended="opening a chapter creates canonical reading history", observed={"accepted": opened.get("accepted"), "revision": opened.get("revision")}, passed=opened.get("accepted") is True)
        commit = user.session.post(f"{progress_path}/commit", json=checkpoint_payload(opened, 2, 1.0, completed_page=2), timeout=15)
        _expect_status(journey, "save-reading-progress", commit, 200, "user progress can be committed")
        journey.assert_true("chapter-completed", commit.json().get("completed") is True, intended="finishing the last page marks the chapter completed", observed=commit.json())

        history = user.session.get("/api/progress/history", timeout=15)
        _expect_status(journey, "reading-history", history, 200, "user can retrieve reading history")
        journey.assert_true(
            "history-contains-read-series",
            any(row.get("series_id") == series_id for row in history.json()),
            intended="opened/completed series is present in reading history",
            observed={"series_ids": [row.get("series_id") for row in history.json()]},
        )

        series_state = user.session.get(f"/api/progress/series/{slug}/state", timeout=15)
        _expect_status(journey, "series-reading-state", series_state, 200, "user can retrieve per-series reading state")
        journey.assert_true("series-state-completed-chapter", chapter_id in series_state.json().get("completed_chapter_ids", []), intended="completed chapter appears in canonical per-series state", observed=series_state.json())

        library = user.session.get("/api/social/library", params={"scope": "history"}, timeout=15)
        _expect_status(journey, "history-library-projection", library, 200, "Smart Library can project reading history")
        journey.assert_true(
            "library-history-contains-series",
            any(row.get("series_id") == series_id for row in library.json().get("items", [])),
            intended="history projection contains the read series",
            observed={"total": library.json().get("total")},
        )

        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications(user_id, series_id, chapter_id, message, is_read)
                VALUES (%s::uuid,%s::uuid,%s::uuid,'Actor journey notification',FALSE)
                RETURNING id::text
                """,
                (user.user_id, series_id, chapter_id),
            )
            notification_ids.append(cur.fetchone()[0])

        count = user.session.get("/api/notifications/count", timeout=10)
        _expect_status(journey, "notification-count", count, 200, "user can retrieve unread notification count")
        journey.assert_true("notification-count-positive", count.json().get("unread", 0) >= 1, intended="new unread notification increments the unread count", observed=count.json())

        notification_id = notification_ids[0]
        notifications = user.session.get("/api/notifications", params={"unread_only": "true"}, timeout=10)
        _expect_status(journey, "list-notifications", notifications, 200, "user can list unread notifications")
        journey.assert_true(
            "notification-visible",
            any(row.get("id") == notification_id for row in notifications.json()),
            intended="new notification appears in unread notifications",
            observed={"notification_id": notification_id, "count": len(notifications.json())},
        )
        marked = user.session.post(f"/api/notifications/{notification_id}/read", timeout=10)
        _expect_status(journey, "mark-notification-read", marked, 200, "user can mark a notification read")
        journey.assert_true("notification-read-state", marked.json().get("marked") is True, intended="notification transitions to read", observed=marked.json())

        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications(user_id, series_id, chapter_id, message, is_read)
                VALUES (%s::uuid,%s::uuid,%s::uuid,'Actor journey read-all notification',FALSE)
                RETURNING id::text
                """,
                (user.user_id, series_id, chapter_id),
            )
            notification_ids.append(cur.fetchone()[0])
        read_all = user.session.post("/api/notifications/read-all", timeout=10)
        _expect_status(journey, "mark-all-notifications-read", read_all, 200, "user can mark all notifications read")
        journey.assert_true("notification-read-all-count", read_all.json().get("marked", 0) >= 1, intended="read-all marks outstanding notifications", observed=read_all.json())
    finally:
        with db.cursor() as cur:
            for notification_id in notification_ids:
                cur.execute("DELETE FROM notifications WHERE id=%s::uuid", (notification_id,))
            cur.execute("DELETE FROM reading_progress WHERE user_id=%s::uuid AND series_id=%s::uuid", (user.user_id, series_id))
            cur.execute("DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid", (user.user_id, series_id))
