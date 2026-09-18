import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class RuntimeDatabaseConfigContractTests(unittest.TestCase):
    def test_go_runtime_loaders_require_dedicated_dsn_without_bootstrap_fallback(self):
        expected = {
            'services/catalog_go/internal/config/config.go': 'CATALOG_GO_DATABASE_URL',
            'services/progress_go/internal/config/config.go': 'PROGRESS_GO_DATABASE_URL',
            'services/reader_go/internal/config/config.go': 'READER_GO_DATABASE_URL',
            'services/realtime_go/internal/config/config.go': 'REALTIME_DATABASE_URL',
            'services/notification_worker/internal/config/config.go': 'NOTIFICATION_DATABASE_URL',
            'services/outbox_relay/internal/config/config.go': 'OUTBOX_DATABASE_URL',
        }
        for rel, dsn_env in expected.items():
            text = (ROOT / rel).read_text()
            with self.subTest(rel=rel):
                self.assertIn(f'requireEnv("{dsn_env}")', text)
                self.assertNotIn('getenv("POSTGRES_USER"', text)
                self.assertNotIn('getenv("POSTGRES_PASSWORD"', text)
                self.assertNotIn('getenv("POSTGRES_DB"', text)

    def test_social_requires_its_dedicated_dsn(self):
        text = (ROOT / 'services/social_ts/src/config.ts').read_text()
        self.assertIn('process.env.SOCIAL_DATABASE_URL', text)
        self.assertIn('throw new Error', text)
        self.assertNotIn('process.env.POSTGRES_USER', text)
        self.assertNotIn('process.env.POSTGRES_PASSWORD', text)
        self.assertNotIn('process.env.POSTGRES_DB', text)

    def test_shared_python_database_engine_uses_only_dedicated_runtime_dsns(self):
        config = (ROOT / 'shared/shared/config.py').read_text()
        database = (ROOT / 'shared/shared/database.py').read_text()
        for env_name in (
            'AUTH_DATABASE_URL',
            'AUTH_ADMIN_DATABASE_URL',
            'IMAGE_DATABASE_URL',
            'MEDIA_DATABASE_URL',
            'MEDIA_THUMBNAIL_DATABASE_URL',
            'LIFECYCLE_DATABASE_URL',
        ):
            self.assertIn(env_name, config)
        self.assertIn('def database_url', config)
        self.assertIn('settings.database_url', database)
        self.assertNotIn('DATABASE_URL: str = "postgresql+asyncpg://manhwa:manhwa@db:5432/manhwa"', config)

    def test_scraper_api_batch_and_series_use_distinct_scoped_dsns(self):
        config = (ROOT / 'services/scraper_service/app/config.py').read_text()
        main = (ROOT / 'services/scraper_service/app/main.py').read_text()
        batch = (ROOT / 'services/scraper_service/app/batch_worker.py').read_text()
        series = (ROOT / 'services/scraper_service/app/series_worker.py').read_text()
        self.assertIn('scraper_database_url', config)
        self.assertIn('scraper_batch_database_url', config)
        self.assertIn('scraper_series_database_url', config)
        self.assertIn('settings.database_url', main)
        self.assertIn('settings.batch_database_url', batch)
        self.assertIn('settings.series_database_url', series)
        self.assertNotIn('postgres_user:', config)
        self.assertNotIn('postgres_password:', config)
        self.assertNotIn('postgres_url:', config)


if __name__ == '__main__':
    unittest.main()
