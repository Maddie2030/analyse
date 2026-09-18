import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text()


class P083PrivateRecoveryDownloadTests(unittest.TestCase):
    def test_backup_agent_owns_private_authenticated_recovery_bridge(self):
        bridge = ROOT / 'ops/postgres-backup/recovery_bridge/main.go'
        self.assertTrue(bridge.is_file(), 'private recovery bridge source must exist')
        source = bridge.read_text()
        for needle in (
            'X-MReader-Internal-Token',
            'subtle.ConstantTimeCompare',
            '/internal/v1/recovery/download/',
            'bkp_[0-9a-f]{24}',
            'copy-artifact',
            'catalog',
            'Cache-Control',
            'no-store',
        ):
            self.assertIn(needle, source)
        self.assertNotIn('relative_directory', source.split('Content-Disposition')[-1])

        dockerfile = text('ops/postgres-backup/Dockerfile')
        self.assertIn('ops/postgres-backup/recovery_bridge', dockerfile)
        self.assertIn('mreader-recovery-bridge', dockerfile)
        agent = text('scripts/backup/backup-agent.sh')
        self.assertIn('mreader-recovery-bridge', agent)
        self.assertIn('RECOVERY_BRIDGE_TOKEN', agent)

    def test_scraper_download_is_streamed_through_private_bridge(self):
        config = text('services/scraper_service/app/config.py')
        self.assertIn('recovery_bridge_internal_url', config)
        self.assertIn('recovery_bridge_token', config)

        facade_path = ROOT / 'services/scraper_service/app/database_facade.py'
        self.assertTrue(facade_path.is_file(), 'database facade module must own the private download proxy')
        facade = facade_path.read_text()
        start = facade.index('async def admin_download_database_backup')
        body = facade[start:]
        self.assertIn('StreamingResponse', body)
        self.assertIn('X-MReader-Internal-Token', body)
        self.assertIn('settings.recovery_bridge_internal_url', body)
        self.assertIn('settings.recovery_bridge_token', body)
        self.assertNotIn('host-local export delivery is being requalified', body)
        for forbidden in ('MREADER_DB_PROTECTION_ROOT', 'relative_directory', 'artifact_name'):
            self.assertNotIn(forbidden, body)

    def test_recovery_bridge_credential_is_scoped_only_to_scraper_service(self):
        scope_dir = ROOT / 'deploy/docker-desktop-hybrid/env-scopes'
        consumers = []
        for scope in scope_dir.glob('*.keys'):
            keys = {
                line.strip() for line in scope.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#')
            }
            if 'RECOVERY_BRIDGE_TOKEN' in keys:
                consumers.append(scope.stem)
        self.assertEqual(consumers, ['scraper-service'])

        self.assertIn('RECOVERY_BRIDGE_TOKEN=', text('.env.example'))
        secret_helper = text('scripts/hybrid/ensure-private-transport-secrets.sh')
        self.assertIn('RECOVERY_BRIDGE_TOKEN', secret_helper)
        stateful_up = text('scripts/hybrid/stateful-up.sh')
        self.assertIn('ensure-private-transport-secrets.sh', stateful_up)
        deploy = text('scripts/hybrid/deploy.sh')
        self.assertIn('RECOVERY_BRIDGE_INTERNAL_URL', deploy)
        self.assertIn('HYBRID_RECOVERY_BRIDGE_PORT', deploy)

    def test_only_host_backup_agent_mounts_recovery_root_and_bridge_is_not_public_routed(self):
        compose = text('deploy/compose/docker-compose.hybrid-stateful.yml')
        backup = compose[compose.index('  backup_agent:'):compose.index('\n  migrate:', compose.index('  backup_agent:'))]
        self.assertIn('MREADER_DB_PROTECTION_ROOT', backup)
        self.assertIn('RECOVERY_BRIDGE_TOKEN', backup)
        self.assertIn('HYBRID_RECOVERY_BRIDGE_PORT', backup)

        admin_apps = text('deploy/docker-desktop-hybrid/admin-apps.yaml')
        user_apps = text('deploy/docker-desktop-hybrid/user-apps.yaml')
        self.assertNotIn('MREADER_DB_PROTECTION_ROOT', admin_apps)
        self.assertNotIn('MREADER_DB_PROTECTION_ROOT', user_apps)
        self.assertNotIn('/mreader-db-protection', admin_apps)
        self.assertNotIn('/mreader-db-protection', user_apps)

        for filename in ('Caddyfile.user', 'Caddyfile.admin'):
            caddy = text(f'deploy/docker-desktop-hybrid/{filename}')
            self.assertNotIn('18084', caddy)
            self.assertNotIn('recovery/download', caddy)
            self.assertIn('@internal path /internal /internal/*', caddy)
            self.assertIn('respond @internal 404', caddy)

    def test_admin_ui_exposes_download_only_through_authenticated_scraper_route(self):
        client = text('frontend/src/api/client.ts')
        page = text('frontend/src/pages/AdminDatabase.tsx')
        self.assertIn('/api/admin/database/backups/', client + page)
        self.assertNotIn('/api/scraper/admin/database', client + page)
        self.assertIn('/download', client + page)
        self.assertIn('Download', page)
        self.assertNotIn('RECOVERY_BRIDGE_TOKEN', client + page)
        self.assertNotIn('host.docker.internal', client + page)


if __name__ == '__main__':
    unittest.main()
