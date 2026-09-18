from datetime import datetime, timedelta, timezone
import uuid

from helpers import assert_status


def test_catalog_genres_tags_discovery(anonymous, seed_content):
    genres = anonymous.get("/api/catalog/genres", timeout=10)
    assert_status(genres, 200)
    assert any(g["id"] == seed_content["genre_id"] for g in genres.json())

    tags = anonymous.get("/api/catalog/tags", timeout=10)
    assert_status(tags, 200)
    assert any(t["id"] == seed_content["tag_id"] for t in tags.json())

    discover = anonymous.get("/api/catalog/discover", timeout=10)
    assert_status(discover, 200)
    body = discover.json()
    assert set(body) >= {"popular", "recent", "new"}

    seeded = next(item for item in body["recent"] if item["id"] == seed_content["series_id"])
    latest = seeded["latest_chapters"]
    assert 1 <= len(latest) <= 3
    assert [chapter["chapter_number"] for chapter in latest[:2]] == [2, 1]
    assert latest[0]["slug"] == "ch-2"
    assert latest[0]["published_at"]



def test_catalog_trending_windows_are_analytics_backed(anonymous, db):
    cache_isolation_limit = 51 + (int(uuid.uuid4().hex[:2], 16) % 49)
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO series(title, slug, description, status)
            VALUES ('Pytest Trending Series', %s, 'temporary analytics test', 'ongoing')
            RETURNING id
            """,
            (f"pytest-trending-{uuid.uuid4().hex[:10]}",),
        )
        series_id = str(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO series_trending_hourly(series_id, bucket_start, open_count)
            VALUES
              (%s::uuid, date_trunc('hour', NOW()), 3),
              (%s::uuid, date_trunc('hour', NOW() - INTERVAL '2 days'), 7),
              (%s::uuid, date_trunc('hour', NOW() - INTERVAL '10 days'), 11)
            """,
            (series_id, series_id, series_id),
        )

    try:
        expected = {"24h": 3, "7d": 10, "30d": 21}
        for window, score in expected.items():
            response = anonymous.get(
                "/api/catalog/trending",
                params={"window": window, "limit": cache_isolation_limit},
                timeout=10,
            )
            assert_status(response, 200)
            body = response.json()
            assert body["window"] == window
            assert body["generated_at"]
            item = next(row for row in body["items"] if row["id"] == series_id)
            assert item["trend_score"] == score

        invalid = anonymous.get("/api/catalog/trending", params={"window": "1h"}, timeout=10)
        assert_status(invalid, 422)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM series WHERE id = %s::uuid", (series_id,))

def test_catalog_list_search_and_validation(anonymous, seed_content):
    listing = anonymous.get(
        "/api/catalog/series",
        params={"search": seed_content["series_slug"].replace("-", " "), "limit": 100},
        timeout=10,
    )
    assert_status(listing, 200)
    assert isinstance(listing.json(), list)

    invalid = anonymous.get("/api/catalog/series", params={"limit": 0}, timeout=10)
    assert_status(invalid, 422)


def test_catalog_series_and_chapter_details(anonymous, seed_content):
    series = anonymous.get(
        f"/api/catalog/series/{seed_content['series_slug']}",
        timeout=10,
    )
    assert_status(series, 200)
    body = series.json()
    assert body["id"] == seed_content["series_id"]
    assert len(body["chapters"]) >= 2

    chapter = anonymous.get(
        f"/api/catalog/series/{seed_content['series_slug']}/chapters/ch-1",
        timeout=10,
    )
    assert_status(chapter, 200)
    assert chapter.json()["slug"] == "ch-1"

    missing = anonymous.get("/api/catalog/series/pytest-does-not-exist", timeout=10)
    assert_status(missing, 404)



def test_catalog_taxonomy_filters_use_assigned_data(
    anonymous,
    seed_content,
    db,
):
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO genres(name)
            VALUES (%s)
            ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            ("Orphan Pytest Genre",),
        )
        orphan_genre_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO tags(name)
            VALUES (%s)
            ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            ("ORPHAN_PYTEST_TAG",),
        )
        orphan_tag_id = cur.fetchone()[0]

    try:
        genres = anonymous.get("/api/catalog/genres", timeout=10)
        assert_status(genres, 200)
        genre_ids = {item["id"] for item in genres.json()}
        assert seed_content["genre_id"] in genre_ids
        assert orphan_genre_id not in genre_ids

        tags = anonymous.get("/api/catalog/tags", timeout=10)
        assert_status(tags, 200)
        tag_ids = {item["id"] for item in tags.json()}
        assert seed_content["tag_id"] in tag_ids
        assert orphan_tag_id not in tag_ids

        filtered = anonymous.get(
            "/api/catalog/series",
            params={
                "genre": str(seed_content["genre_id"]),
                "tag": str(seed_content["tag_id"]),
                "limit": 100,
            },
            timeout=10,
        )
        assert_status(filtered, 200)

        matching = [
            item
            for item in filtered.json()
            if item["id"] == seed_content["series_id"]
        ]
        assert matching
        assert any(
            genre["id"] == seed_content["genre_id"]
            for genre in matching[0].get("genres", [])
        )
        assert any(
            tag["id"] == seed_content["tag_id"]
            for tag in matching[0].get("tags", [])
        )

    finally:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM genres WHERE id = %s",
                (orphan_genre_id,),
            )
            cur.execute(
                "DELETE FROM tags WHERE id = %s",
                (orphan_tag_id,),
            )



def test_catalog_multi_taxonomy_and_search_filters(
    anonymous,
    seed_content,
    db,
):
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO genres(name)
            VALUES (%s)
            ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            ("Secondary Pytest Genre",),
        )
        genre_2 = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO tags(name)
            VALUES (%s)
            ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            ("SECONDARY_PYTEST_TAG",),
        )
        tag_2 = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO series_genres(series_id, genre_id)
            VALUES (%s::uuid, %s)
            ON CONFLICT DO NOTHING
            """,
            (seed_content["series_id"], genre_2),
        )
        cur.execute(
            """
            INSERT INTO series_tags(series_id, tag_id)
            VALUES (%s::uuid, %s)
            ON CONFLICT DO NOTHING
            """,
            (seed_content["series_id"], tag_2),
        )

    try:
        response = anonymous.get(
            "/api/catalog/series",
            params={
                "search": "Pytest Series",
                "genre": (
                    f"{seed_content['genre_id']},{genre_2}"
                ),
                "tag": (
                    f"{seed_content['tag_id']},{tag_2}"
                ),
                "limit": 100,
            },
            timeout=10,
        )
        assert_status(response, 200)

        matches = [
            item
            for item in response.json()
            if item["id"] == seed_content["series_id"]
        ]
        assert matches

        genre_ids = {
            item["id"]
            for item in matches[0].get("genres", [])
        }
        tag_ids = {
            item["id"]
            for item in matches[0].get("tags", [])
        }

        assert {
            seed_content["genre_id"],
            genre_2,
        }.issubset(genre_ids)
        assert {
            seed_content["tag_id"],
            tag_2,
        }.issubset(tag_ids)

    finally:
        with db.cursor() as cur:
            cur.execute(
                """
                DELETE FROM series_genres
                WHERE series_id = %s::uuid
                  AND genre_id = %s
                """,
                (seed_content["series_id"], genre_2),
            )
            cur.execute(
                """
                DELETE FROM series_tags
                WHERE series_id = %s::uuid
                  AND tag_id = %s
                """,
                (seed_content["series_id"], tag_2),
            )
            cur.execute(
                """
                DELETE FROM genres
                WHERE id = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM series_genres
                    WHERE genre_id = %s
                  )
                """,
                (genre_2, genre_2),
            )
            cur.execute(
                """
                DELETE FROM tags
                WHERE id = %s
                  AND NOT EXISTS (
                    SELECT 1
                    FROM series_tags
                    WHERE tag_id = %s
                  )
                """,
                (tag_2, tag_2),
            )


def test_catalog_chapter_search_is_number_only(anonymous, seed_content):
    response = anonymous.get(
        f"/api/catalog/series/{seed_content['series_slug']}",
        params={"chapter_search": "2", "chapter_limit": 100},
        timeout=10,
    )
    assert_status(response, 200)
    chapters = response.json()["chapters"]
    assert chapters
    assert all("2" in str(chapter["chapter_number"]) for chapter in chapters)

    # Titles/slugs must no longer participate in the chapter-search contract.
    title_search = anonymous.get(
        f"/api/catalog/series/{seed_content['series_slug']}",
        params={"chapter_search": "Chapter 2", "chapter_limit": 100},
        timeout=10,
    )
    assert_status(title_search, 200)
    assert title_search.json()["chapters"] == []


def test_catalog_min_rating_filter_runs_before_pagination(
    anonymous,
    regular_user,
    seed_content,
):
    series_id = seed_content["series_id"]

    rated = regular_user.session.put(
        f"/api/social/series/{series_id}/rating",
        json={"rating": 4},
        timeout=10,
    )
    assert_status(rated, 200)

    included = anonymous.get(
        "/api/catalog/series",
        params={"min_rating": "3.5", "limit": 100},
        timeout=10,
    )
    assert_status(included, 200)
    assert any(item["id"] == series_id for item in included.json())

    excluded = anonymous.get(
        "/api/catalog/series",
        params={"min_rating": "4.5", "limit": 100},
        timeout=10,
    )
    assert_status(excluded, 200)
    assert all(item["id"] != series_id for item in excluded.json())

    invalid = anonymous.get(
        "/api/catalog/series",
        params={"min_rating": "5.5", "limit": 20},
        timeout=10,
    )
    assert_status(invalid, 422)

    cleared = regular_user.session.delete(
        f"/api/social/series/{series_id}/rating",
        timeout=10,
    )
    assert_status(cleared, 204)


def test_public_curation_honors_active_schedule(anonymous, admin_user):
    slug = f"pytest-curated-{uuid.uuid4().hex[:8]}"
    created = admin_user.session.post(
        "/api/catalog/series",
        json={
            "title": "Pytest Curated Series",
            "slug": slug,
            "description": "temporary curation test",
            "status": "ongoing",
            "genre_ids": [],
            "tag_names": [],
        },
        timeout=15,
    )
    assert_status(created, 201)
    series_id = created.json()["id"]
    pick_id = None
    announcement_ids = []
    now = datetime.now(timezone.utc)

    try:
        pick = admin_user.session.post(
            "/api/catalog/admin/editor-picks",
            json={
                "series_id": series_id,
                "label": "Staff pick",
                "note": "Recommended by pytest",
                "position": 2,
                "is_active": True,
                "starts_at": None,
                "ends_at": None,
            },
            timeout=10,
        )
        assert_status(pick, 201)
        pick_id = pick.json()["id"]

        announcement_specs = [
            ("Live pytest notice", "Visible now", "info", True, now - timedelta(hours=1), now + timedelta(hours=1)),
            ("Future pytest notice", "Not visible yet", "warning", True, now + timedelta(days=1), now + timedelta(days=2)),
            ("Expired pytest notice", "No longer visible", "critical", True, now - timedelta(days=2), now - timedelta(days=1)),
            ("Inactive pytest notice", "Disabled", "success", False, None, None),
        ]
        for position, (title, body, tone, active, starts_at, ends_at) in enumerate(announcement_specs, 1):
            response = admin_user.session.post(
                "/api/catalog/admin/announcements",
                json={
                    "title": title,
                    "body": body,
                    "link_url": None,
                    "link_label": None,
                    "tone": tone,
                    "dismissible": True,
                    "position": position,
                    "is_active": active,
                    "starts_at": starts_at.isoformat() if starts_at else None,
                    "ends_at": ends_at.isoformat() if ends_at else None,
                },
                timeout=10,
            )
            assert_status(response, 201)
            announcement_ids.append(response.json()["id"])

        response = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(response, 200)
        body = response.json()
        assert set(body) >= {"editor_picks", "announcements"}
        visible_pick = next(item for item in body["editor_picks"] if item["id"] == pick_id)
        assert visible_pick["series"]["id"] == series_id
        assert visible_pick["label"] == "Staff pick"
        titles = {item["title"] for item in body["announcements"]}
        assert "Live pytest notice" in titles
        assert "Future pytest notice" not in titles
        assert "Expired pytest notice" not in titles
        assert "Inactive pytest notice" not in titles
    finally:
        for announcement_id in announcement_ids:
            admin_user.session.delete(
                f"/api/catalog/admin/announcements/{announcement_id}",
                timeout=10,
            )
        if pick_id:
            admin_user.session.delete(f"/api/catalog/admin/editor-picks/{pick_id}", timeout=10)
        admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=15)

