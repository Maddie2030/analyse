import uuid

from helpers import assert_status


def test_catalog_write_requires_auth(admin_anonymous):
    response = admin_anonymous.post(
        "/api/catalog/series",
        json={
            "title": "Unauthorized",
            "slug": f"unauthorized-{uuid.uuid4().hex[:6]}",
            "status": "ongoing",
            "genre_ids": [],
            "tag_names": [],
        },
        timeout=10,
    )
    assert_status(response, 401)


def test_catalog_write_requires_admin(admin_regular_user):
    response = admin_regular_user.session.post(
        "/api/catalog/series",
        json={
            "title": "Regular user",
            "slug": f"regular-{uuid.uuid4().hex[:6]}",
            "status": "ongoing",
            "genre_ids": [],
            "tag_names": [],
        },
        timeout=10,
    )
    assert_status(response, 403)


def test_catalog_write_gate_or_crud(admin_user):
    slug = f"pytest-catalog-{uuid.uuid4().hex[:8]}"
    create = admin_user.session.post(
        "/api/catalog/series",
        json={
            "title": "Pytest Catalog Write",
            "slug": slug,
            "description": "Created only by integration tests",
            "status": "ongoing",
            "genre_ids": [],
            "tag_names": ["PYTEST"],
        },
        timeout=15,
    )

    assert_status(create, 201)
    series_id = create.json()["id"]

    try:
        update = admin_user.session.put(
            f"/api/catalog/series/{series_id}",
            json={
                "title": "Pytest Catalog Updated",
                "status": "completed",
                "genre_ids": [],
                "tag_ids": [],
            },
            timeout=15,
        )
        assert_status(update, 200)

        chapter = admin_user.session.post(
            f"/api/catalog/series/{series_id}/chapters",
            json={
                "chapter_number": 1,
                "title": "Chapter One",
                "slug": "ch-1",
                "status": "draft",
            },
            timeout=15,
        )
        assert_status(chapter, 201)
        chapter_id = chapter.json()["id"]

        publish = admin_user.session.post(
            f"/api/catalog/series/{series_id}/chapters/{chapter_id}/publish",
            timeout=15,
        )
        assert_status(publish, 422)
        assert "at least one page" in publish.text.lower()

        duplicate = admin_user.session.post(
            f"/api/catalog/series/{series_id}/chapters",
            json={
                "chapter_number": 1,
                "slug": "ch-duplicate",
                "status": "draft",
            },
            timeout=15,
        )
        assert_status(duplicate, 409)
    finally:
        admin_user.session.delete(
            f"/api/catalog/series/{series_id}",
            timeout=15,
        )


def test_catalog_admin_curation_crud(admin_user):
    slug = f"pytest-curation-{uuid.uuid4().hex[:8]}"
    create_series = admin_user.session.post(
        '/api/catalog/series',
        json={'title': 'Pytest Curation', 'slug': slug, 'status': 'ongoing', 'genre_ids': [], 'tag_names': []},
        timeout=15,
    )
    assert_status(create_series, 201)
    series_id = create_series.json()['id']
    pick_id = None
    announcement_id = None
    try:
        initial = admin_user.session.get('/api/catalog/admin/curation', timeout=10)
        assert_status(initial, 200)

        pick = admin_user.session.post(
            '/api/catalog/admin/editor-picks',
            json={
                'series_id': series_id, 'label': 'Featured', 'note': 'Pytest recommendation',
                'position': 3, 'is_active': True, 'starts_at': None, 'ends_at': None,
            }, timeout=10,
        )
        assert_status(pick, 201)
        pick_id = pick.json()['id']
        assert pick.json()['series']['id'] == series_id

        duplicate = admin_user.session.post(
            '/api/catalog/admin/editor-picks',
            json={'series_id': series_id, 'label': None, 'note': None, 'position': 4, 'is_active': True, 'starts_at': None, 'ends_at': None},
            timeout=10,
        )
        assert_status(duplicate, 409)

        updated = admin_user.session.put(
            f'/api/catalog/admin/editor-picks/{pick_id}',
            json={'series_id': series_id, 'label': 'Updated', 'note': 'Changed', 'position': 1, 'is_active': False, 'starts_at': None, 'ends_at': None},
            timeout=10,
        )
        assert_status(updated, 200)
        assert updated.json()['position'] == 1
        assert updated.json()['is_active'] is False

        announcement = admin_user.session.post(
            '/api/catalog/admin/announcements',
            json={
                'title': 'Pytest announcement', 'body': 'Visible banner test', 'link_url': '/library', 'link_label': 'Open library',
                'tone': 'warning', 'dismissible': True, 'position': 2, 'is_active': True, 'starts_at': None, 'ends_at': None,
            }, timeout=10,
        )
        assert_status(announcement, 201)
        announcement_id = announcement.json()['id']

        changed = admin_user.session.put(
            f'/api/catalog/admin/announcements/{announcement_id}',
            json={
                'title': 'Pytest announcement updated', 'body': 'Updated banner', 'link_url': None, 'link_label': None,
                'tone': 'info', 'dismissible': False, 'position': 0, 'is_active': True, 'starts_at': None, 'ends_at': None,
            }, timeout=10,
        )
        assert_status(changed, 200)
        assert changed.json()['dismissible'] is False

        invalid_url = admin_user.session.put(
            f'/api/catalog/admin/announcements/{announcement_id}',
            json={
                'title': 'Unsafe', 'body': 'Unsafe link', 'link_url': 'javascript:alert(1)', 'link_label': 'Bad',
                'tone': 'info', 'dismissible': True, 'position': 0, 'is_active': True, 'starts_at': None, 'ends_at': None,
            }, timeout=10,
        )
        assert_status(invalid_url, 422)
    finally:
        if announcement_id:
            admin_user.session.delete(f'/api/catalog/admin/announcements/{announcement_id}', timeout=10)
        if pick_id:
            admin_user.session.delete(f'/api/catalog/admin/editor-picks/{pick_id}', timeout=10)
        admin_user.session.delete(f'/api/catalog/series/{series_id}', timeout=15)


def test_public_curation_cache_invalidates_after_admin_mutations(admin_user, anonymous):
    slug = f"pytest-curation-cache-{uuid.uuid4().hex[:8]}"
    created = admin_user.session.post(
        "/api/catalog/series",
        json={"title": "Pytest Curation Cache", "slug": slug, "status": "ongoing", "genre_ids": [], "tag_names": []},
        timeout=15,
    )
    assert_status(created, 201)
    series_id = created.json()["id"]
    pick_id = None
    announcement_id = None

    try:
        # Prime the user-plane local cache before any curation mutation.
        primed = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(primed, 200)
        assert primed.headers.get("X-MReader-Local-Cache") in {"MISS", "HIT", "STALE", "LOAD", None}

        pick = admin_user.session.post(
            "/api/catalog/admin/editor-picks",
            json={
                "series_id": series_id,
                "label": "Cache invalidation",
                "note": "must become visible without TTL wait",
                "position": 0,
                "is_active": True,
                "starts_at": None,
                "ends_at": None,
            },
            timeout=10,
        )
        assert_status(pick, 201)
        pick_id = pick.json()["id"]

        after_pick = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(after_pick, 200)
        assert any(row["id"] == pick_id for row in after_pick.json()["editor_picks"])

        disabled = admin_user.session.put(
            f"/api/catalog/admin/editor-picks/{pick_id}",
            json={
                "series_id": series_id,
                "label": "Cache invalidation",
                "note": "disabled",
                "position": 0,
                "is_active": False,
                "starts_at": None,
                "ends_at": None,
            },
            timeout=10,
        )
        assert_status(disabled, 200)

        after_disable = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(after_disable, 200)
        assert all(row["id"] != pick_id for row in after_disable.json()["editor_picks"])

        announcement = admin_user.session.post(
            "/api/catalog/admin/announcements",
            json={
                "title": "Cache invalidation announcement",
                "body": "version one",
                "link_url": None,
                "link_label": None,
                "tone": "info",
                "dismissible": True,
                "position": 0,
                "is_active": True,
                "starts_at": None,
                "ends_at": None,
            },
            timeout=10,
        )
        assert_status(announcement, 201)
        announcement_id = announcement.json()["id"]

        after_announcement = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(after_announcement, 200)
        visible = next(row for row in after_announcement.json()["announcements"] if row["id"] == announcement_id)
        assert visible["body"] == "version one"

        changed = admin_user.session.put(
            f"/api/catalog/admin/announcements/{announcement_id}",
            json={
                "title": "Cache invalidation announcement",
                "body": "version two",
                "link_url": None,
                "link_label": None,
                "tone": "warning",
                "dismissible": False,
                "position": 0,
                "is_active": True,
                "starts_at": None,
                "ends_at": None,
            },
            timeout=10,
        )
        assert_status(changed, 200)

        after_update = anonymous.get("/api/catalog/curation", timeout=10)
        assert_status(after_update, 200)
        visible = next(row for row in after_update.json()["announcements"] if row["id"] == announcement_id)
        assert visible["body"] == "version two"
        assert visible["dismissible"] is False
    finally:
        if announcement_id:
            admin_user.session.delete(f"/api/catalog/admin/announcements/{announcement_id}", timeout=10)
        if pick_id:
            admin_user.session.delete(f"/api/catalog/admin/editor-picks/{pick_id}", timeout=10)
        admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=15)
