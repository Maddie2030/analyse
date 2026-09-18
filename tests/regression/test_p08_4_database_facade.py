import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text()


class P084DatabaseFacadeTests(unittest.TestCase):
    def test_database_facade_is_separate_and_canonical(self):
        facade = ROOT / 'services/scraper_service/app/database_facade.py'
        self.assertTrue(facade.is_file(), 'P08.4 must extract the admin database facade into its own module')
        source = facade.read_text()
        self.assertIn('APIRouter(prefix="/api/admin/database"', source)
        for required in (
            'list_database_operations',
            'queue_database_operation',
            'cancel_database_operation',
            'list_recovery_page',
            'resolve_recovery_point',
            'recovery_bridge_internal_url',
            'recovery_bridge_token',
        ):
            self.assertIn(required, source)
        for forbidden in ('staging_store', 'ensure_staging_spool', 'RabbitQueueBroker', 'Redis', 'seaweedfs_filer_url'):
            self.assertNotIn(forbidden, source)

        main = text('services/scraper_service/app/main.py')
        self.assertIn('database_facade_router', main)
        self.assertIn('app.include_router(database_facade_router)', main)
        self.assertNotIn('@app.get("/api/scraper/admin/database")', main)
        self.assertNotIn('/api/scraper/admin/database/', main)

    def test_frontend_gateway_and_api_contract_move_together(self):
        client = text('frontend/src/api/client.ts')
        page = text('frontend/src/pages/AdminDatabase.tsx')
        api_test = text('tests/api/test_25_database_protection.py')
        coverage = text('tests/api/endpoint_coverage.tsv')
        combined = client + page + api_test + coverage
        self.assertIn('/api/admin/database', combined)
        self.assertNotIn('/api/scraper/admin/database', combined)

        admin = text('deploy/docker-desktop-hybrid/Caddyfile.admin')
        self.assertIn('@databaseAdmin path /api/admin/database /api/admin/database/*', admin)
        database_block = admin[admin.index('@databaseAdmin path'):]
        self.assertIn('reverse_proxy scraper-service:8000', database_block)

        user = text('deploy/docker-desktop-hybrid/Caddyfile.user')
        admin_line = next(line for line in user.splitlines() if line.strip().startswith('@adminApi path'))
        self.assertIn('/api/admin/database', admin_line)

    def test_scraper_staging_failure_does_not_prevent_facade_startup(self):
        main = text('services/scraper_service/app/main.py')
        self.assertIn('async def _initialize_scraper_staging', main)
        start = main.index('async def _initialize_scraper_staging')
        end = main.index('\n\n', start)
        helper = main[start:end]
        self.assertIn('try:', helper)
        self.assertIn('ensure_staging_spool', helper)
        self.assertIn('except Exception', helper)
        self.assertIn('return False', helper)
        self.assertIn('staging_ready = await _initialize_scraper_staging(app)', main)
        self.assertIn('if staging_ready:', main)
        self.assertIn('app.state.staging_ready = staging_ready', main)
        self.assertIn('if not request.app.state.staging_ready:', main)

    def test_canonical_facade_keeps_one_queue_catalog_and_restore_engine(self):
        facade_path = ROOT / 'services/scraper_service/app/database_facade.py'
        self.assertTrue(facade_path.is_file(), 'database facade module must exist')
        facade = facade_path.read_text()
        self.assertIn('from app.database_protection import', facade)
        self.assertIn('from app.local_recovery_catalog import', facade)
        self.assertNotIn('CREATE TABLE', facade)
        self.assertNotIn('INSERT INTO database_operations', facade)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS database_operations', facade)
        self.assertNotIn('subprocess', facade)
        self.assertNotIn('backup-agent.sh', facade)

        agent = text('scripts/backup/backup-agent.sh')
        self.assertIn('process_database_operation', agent)
        queue_module = text('services/scraper_service/app/database_protection.py')
        self.assertIn('INSERT INTO database_operations', queue_module)

    def test_old_database_aliases_are_retired_after_consumer_move(self):
        paths = (
            'services/scraper_service/app/main.py',
            'services/scraper_service/app/database_facade.py',
            'frontend/src/api/client.ts',
            'frontend/src/pages/AdminDatabase.tsx',
            'tests/api/test_25_database_protection.py',
            'tests/api/endpoint_coverage.tsv',
        )
        for path in paths:
            candidate = ROOT / path
            if candidate.exists():
                self.assertNotIn('/api/scraper/admin/database', candidate.read_text(), path)


if __name__ == '__main__':
    unittest.main()
