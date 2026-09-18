from urllib.parse import quote

from helpers import assert_status


def _manifest(session, seed_content):
    return session.get_json(
        f"/api/reader/{seed_content['series_slug']}/ch-1",
        timeout=15,
    )


def test_image_requires_valid_token(anonymous, seed_content):
    page = _manifest(anonymous, seed_content)["pages"][0]
    path = page["image_path"]

    missing = anonymous.get(f"/images/{path}", timeout=10)
    assert_status(missing, 403)

    invalid = anonymous.get(
        f"/images/{path}",
        params={"token": "invalid.token"},
        timeout=10,
    )
    assert_status(invalid, 403)


def test_valid_image_token_streams_page(anonymous, seed_content):
    manifest = _manifest(anonymous, seed_content)
    page = manifest["pages"][0]

    response = anonymous.get(
        f"/images/{page['image_path']}",
        params={"token": manifest["chapter_token"]},
        timeout=15,
    )
    assert_status(response, 200)
    assert response.content



def test_manifest_reuses_one_chapter_token_for_every_page(anonymous, seed_content):
    manifest = _manifest(anonymous, seed_content)
    assert len(manifest["pages"]) >= 2
    chapter_token = manifest["chapter_token"]
    assert chapter_token
    assert all("token" not in page for page in manifest["pages"])

    # Regression: a published webtoon previously appeared to load page 1 while
    # later/random pages failed. The chapter grant is intentionally shared by
    # every primary/responsive path, so prove the whole manifest rather than
    # sampling only page 1/2.
    for page in manifest["pages"]:
        primary = anonymous.get(
            f"/images/{page['image_path']}",
            params={"token": chapter_token},
            timeout=20,
        )
        assert_status(primary, 200)
        assert primary.content

        responsive = page.get("responsive") or {}
        for variant in responsive.values():
            if not isinstance(variant, dict) or not variant.get("path"):
                continue
            image = anonymous.get(
                f"/images/{variant['path']}",
                params={"token": chapter_token},
                timeout=20,
            )
            assert_status(image, 200)
            assert image.content

def test_chapter_grant_refresh_returns_chapter_scoped_token(anonymous, seed_content):
    manifest = _manifest(anonymous, seed_content)

    refresh = anonymous.get(
        f"/api/token/chapter/{seed_content['series_slug']}/ch-1",
        timeout=10,
    )
    assert_status(refresh, 200)
    payload = refresh.json()
    refreshed = payload["token"]
    assert refreshed
    assert payload["chapter_id"] == manifest["chapter_id"]

    for candidate in manifest["pages"]:
        response = anonymous.get(
            f"/images/{candidate['image_path']}",
            params={"token": refreshed},
            timeout=15,
        )
        assert_status(response, 200)


