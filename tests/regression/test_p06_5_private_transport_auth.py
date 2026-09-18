import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def text(path: str) -> str:
    return (ROOT / path).read_text()


class P065PrivateTransportAuthTests(unittest.TestCase):
    def _assert_contains_all(self, path: str, *needles: str) -> str:
        source = text(path)
        for needle in needles:
            self.assertIn(needle, source)
        return source

    def test_catalog_internal_routes_require_workload_token_and_active_admin(self):
        api = self._assert_contains_all(
            'services/catalog_go/internal/httpapi/api.go',
            'X-MReader-Internal-Token', 'subtle.ConstantTimeCompare', 'IsActiveAdmin',
        )
        self._assert_contains_all('services/catalog_go/internal/config/config.go', 'CATALOG_INTERNAL_TOKEN')
        for handler in ('commitPublication', 'createInternalSeries', 'setInternalSeriesCover'):
            self.assertIn(handler, api)
        self.assertIn('requireInternalWrite', api)

    def test_internal_callers_send_mandatory_scoped_tokens(self):
        scraper_series = text('services/scraper_service/app/catalog_series.py')
        scraper_ingestion = text('services/scraper_service/app/ingestion.py')
        image_transport = text('services/image_service/app/catalog_transport.py')
        scraper_config = text('services/scraper_service/app/config.py')
        self.assertIn('catalog_internal_token', scraper_config)
        self.assertIn('media_internal_token', scraper_config)
        self.assertIn('X-MReader-Internal-Token', scraper_series)
        self.assertIn('catalog_internal_token', scraper_series)
        self.assertIn('X-MReader-Internal-Token', scraper_ingestion)
        self.assertIn('media_internal_token', scraper_ingestion)
        self.assertIn('CATALOG_INTERNAL_TOKEN', image_transport)
        self.assertIn('X-MReader-Internal-Token', image_transport)
        self.assertNotIn('if token:', image_transport)

    def test_media_internal_routes_require_token_and_revalidate_retained_admin(self):
        self._assert_contains_all(
            'services/image_service/app/routers/jobs.py',
            'MEDIA_INTERNAL_TOKEN', 'X-MReader-Internal-Token', 'compare_digest',
            'User.is_active', 'User.role', 'admin', '_require_internal_actor',
        )

    def test_scoped_secret_distribution_is_exact(self):
        scopes = ROOT / 'deploy/docker-desktop-hybrid/env-scopes'
        def keys(name: str) -> set[str]:
            return {
                line.strip() for line in (scopes / f'{name}.keys').read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#')
            }
        catalog_consumers = {
            'catalog-admin', 'scraper-service', 'scraper-series-worker',
            'image-service', 'media-worker', 'media-thumbnail-worker',
        }
        media_consumers = {
            'image-service', 'scraper-service', 'scraper-batch-worker', 'scraper-series-worker',
        }
        all_scopes = {p.stem: keys(p.stem) for p in scopes.glob('*.keys')}
        for name, scope in all_scopes.items():
            self.assertEqual('CATALOG_INTERNAL_TOKEN' in scope, name in catalog_consumers, name)
            self.assertEqual('MEDIA_INTERNAL_TOKEN' in scope, name in media_consumers, name)
        env_example = text('.env.example')
        self.assertIn('CATALOG_INTERNAL_TOKEN=', env_example)
        self.assertIn('MEDIA_INTERNAL_TOKEN=', env_example)

    def test_both_gateways_explicitly_deny_internal_namespace(self):
        for filename in ('Caddyfile.user', 'Caddyfile.admin'):
            caddy = text(f'deploy/docker-desktop-hybrid/{filename}')
            self.assertIn('@internal path /internal /internal/*', caddy)
            self.assertIn('respond @internal 404', caddy)
            self.assertLess(caddy.index('@internal path'), caddy.index('@healthz path'))

    def test_hybrid_up_generates_missing_private_transport_tokens(self):
        hybrid = text('scripts/hybrid-up.sh')
        helper = ROOT / 'scripts/hybrid/ensure-private-transport-secrets.sh'
        self.assertTrue(helper.is_file())
        self.assertIn('ensure-private-transport-secrets.sh', hybrid)
        script = helper.read_text()
        self.assertIn('CATALOG_INTERNAL_TOKEN', script)
        self.assertIn('MEDIA_INTERNAL_TOKEN', script)
        self.assertIn('env_set', script)

    def test_public_catalog_publish_route_cannot_bypass_media_evidence(self):
        api = text('services/catalog_go/internal/httpapi/api.go')
        start = api.index('func (a *API) publishChapter')
        end = api.index('func (a *API) invalidateChapterCaches', start)
        body = api[start:end]
        self.assertIn('publication_requires_media', body)
        self.assertNotIn('a.store.PublishChapter', body)


if __name__ == '__main__':
    unittest.main()
