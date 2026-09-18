from helpers import assert_status


def test_mobile_reader_adapter_health(anonymous):
    response = anonymous.get('/api/mobile/v1/health', timeout=10)
    assert_status(response, 200)
    body = response.json()
    assert body.get('status') == 'ok'
    assert body.get('service') == 'reader-mobile-adapter'
    assert body.get('version') == 'v1'


def test_mobile_reader_adapter_streams_authorized_primary_page(anonymous, seed_content):
    manifest = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/ch-1",
        timeout=15,
    )
    assert_status(manifest, 200)
    token = manifest.json()['chapter_token']

    response = anonymous.get(
        f"/api/mobile/v1/reader/{seed_content['series_slug']}/ch-1/page/1",
        params={'variant': 'primary', 'token': token},
        timeout=20,
    )
    assert_status(response, 200)
    assert response.content
    assert response.headers.get('X-MReader-Mobile-Adapter') == 'v1'
    assert response.headers.get('X-MReader-Mobile-Variant') == 'primary'


def test_mobile_reader_adapter_rejects_invalid_variant(anonymous, seed_content):
    manifest = anonymous.get(
        f"/api/reader/{seed_content['series_slug']}/ch-1",
        timeout=15,
    )
    assert_status(manifest, 200)
    token = manifest.json()['chapter_token']

    response = anonymous.get(
        f"/api/mobile/v1/reader/{seed_content['series_slug']}/ch-1/page/1",
        params={'variant': 'not-a-real-variant', 'token': token},
        timeout=15,
    )
    assert_status(response, 422)
