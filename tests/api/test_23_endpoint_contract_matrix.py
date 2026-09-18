import uuid

from helpers import assert_status


def test_catalog_admin_stats_contract(admin_anonymous, admin_regular_user, admin_user):
    assert_status(admin_anonymous.get('/api/catalog/admin/stats', timeout=10), 401)
    assert_status(admin_regular_user.session.get('/api/catalog/admin/stats', timeout=10), 403)
    response = admin_user.session.get('/api/catalog/admin/stats', timeout=10)
    assert_status(response, 200)
    assert isinstance(response.json(), dict)


def test_notification_retention_sweep_contract(admin_regular_user, admin_user):
    assert_status(admin_regular_user.session.post('/api/notifications/admin/retention/sweep', timeout=10), 403)
    response = admin_user.session.post('/api/notifications/admin/retention/sweep', timeout=20)
    assert_status(response, 200)
    body = response.json()
    assert 'policy' in body


def test_scraper_staging_health_and_failed_batch_listing(admin_user):
    health = admin_user.session.get('/api/scraper/admin/staging-health', timeout=15)
    assert_status(health, 200)
    body = health.json()
    assert 'healthy' in body
    assert 'canonical' in body

    failed = admin_user.session.get('/api/scraper/batches/failed', params={'limit': 5}, timeout=10)
    assert_status(failed, 200)
    assert isinstance(failed.json(), list)


def test_scraper_diagnostic_and_legacy_discovery_ingest_reject_ssrf(admin_user, seed_content):
    private = 'http://127.0.0.1:9/diagnostics'
    diagnose = admin_user.session.post('/api/scraper/diagnose', json={'url': private}, timeout=10)
    assert_status(diagnose, 400)

    payload = {
        'manifest': {
            'chapter_url': private,
            'series_slug': seed_content['series_slug'],
            'chapter_slug': 'ssrf-check',
            'chapter_number': '999',
            'title': 'SSRF Check',
        }
    }
    assert_status(admin_user.session.post('/api/scraper/discover/chapter', json=payload, timeout=10), 400)
    assert_status(admin_user.session.post('/api/scraper/ingest/chapter', json=payload, timeout=10), 400)


def test_scraper_history_list_and_missing_detail(admin_user):
    listing = admin_user.session.get('/api/scraper/history', params={'limit': 5, 'offset': 0}, timeout=10)
    assert_status(listing, 200)
    body = listing.json()
    assert body['limit'] == 5
    assert body['offset'] == 0
    assert isinstance(body['items'], list)

    missing = admin_user.session.get(f'/api/scraper/history/{uuid.uuid4()}', timeout=10)
    assert_status(missing, 404)


def test_reader_chapter_token_and_cloudfront_cookie_clear(api, seed_content):
    token = api.get(
        f"/api/token/chapter/{seed_content['series_slug']}/ch-1",
        timeout=10,
    )
    assert_status(token, 200)
    body = token.json()
    assert body['chapter_id'] == seed_content['chapter_ids']['ch-1']
    assert body['token']

    missing_chapter = api.get(
        f"/api/token/chapter/{seed_content['series_slug']}/does-not-exist",
        timeout=10,
    )
    assert_status(missing_chapter, 404)

    cleared = api.post('/api/token/cloudfront/clear', timeout=10)
    assert_status(cleared, 204)


def test_admin_chapter_export_and_lifecycle_contracts(admin_user, seed_content):
    chapter_id = seed_content['chapter_ids']['ch-1']
    exported = admin_user.session.get(
        f'/api/upload/admin/chapters/{chapter_id}/download',
        params={'mode': 'stored'},
        timeout=30,
    )
    assert_status(exported, 200)
    assert exported.content.startswith(b'PK')

    jobs = admin_user.session.get(
        '/api/upload/admin/lifecycle/cleanup-jobs',
        params={'limit': 10},
        timeout=10,
    )
    assert_status(jobs, 200)
    assert isinstance(jobs.json(), list)

    retry = admin_user.session.post(
        f'/api/upload/admin/lifecycle/cleanup-jobs/{uuid.uuid4()}/retry',
        timeout=10,
    )
    assert_status(retry, 409)
