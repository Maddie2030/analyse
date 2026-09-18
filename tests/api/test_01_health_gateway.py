from helpers import assert_status


def test_user_frontend_root_is_reachable(anonymous):
    response = anonymous.get("/", timeout=10)
    assert_status(response, 200)
    assert "text/html" in response.headers.get("content-type", "")


def test_admin_frontend_root_is_reachable(admin_anonymous):
    response = admin_anonymous.get("/", timeout=10)
    assert_status(response, 200)
    assert "text/html" in response.headers.get("content-type", "")


def test_public_catalog_route_is_reachable(anonymous):
    response = anonymous.get("/api/catalog/genres", timeout=10)
    assert_status(response, 200)
    assert isinstance(response.json(), list)


def test_auth_route_is_not_falling_through_to_frontend(anonymous):
    response = anonymous.get("/api/auth/profile", timeout=10)
    assert_status(response, 401)
    assert response.headers.get("content-type", "").startswith("application/json")


def test_user_plane_blocks_admin_scraper_route(anonymous):
    response = anonymous.get("/api/scraper/admin/series", timeout=10)
    assert_status(response, 404)


def test_admin_plane_scraper_route_requires_auth(admin_anonymous):
    response = admin_anonymous.get("/api/scraper/admin/series", timeout=10)
    assert_status(response, 401)
