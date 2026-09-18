import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared'))

from shared.config import require_workload_database_url  # noqa: E402


class RuntimeDatabaseStartupContracts(unittest.TestCase):
    def test_async_sqlalchemy_workload_dsn_uses_asyncpg_driver(self):
        keys = {
            'AUTH_DATABASE_URL',
            'AUTH_ADMIN_DATABASE_URL',
            'IMAGE_DATABASE_URL',
            'MEDIA_DATABASE_URL',
            'MEDIA_THUMBNAIL_DATABASE_URL',
            'LIFECYCLE_DATABASE_URL',
        }
        env = {key: '' for key in keys}
        env['AUTH_DATABASE_URL'] = 'postgresql://mreader_auth_service:secret@host.docker.internal:5432/manhwa'
        with patch.dict(os.environ, env, clear=False):
            for key in keys - {'AUTH_DATABASE_URL'}:
                os.environ.pop(key, None)
            self.assertEqual(
                require_workload_database_url(),
                'postgresql+asyncpg://mreader_auth_service:secret@host.docker.internal:5432/manhwa',
            )

    def test_progress_runtime_can_select_reading_state_projection(self):
        contract = json.loads((ROOT / 'contracts/ownership/postgres-roles.v1.json').read_text(encoding='utf-8'))
        progress = next(cap for cap in contract['capabilities'] if cap['name'] == 'progress_runtime')
        grants = {
            (grant['object_type'], grant['resource'], tuple(sorted(grant['privileges'])))
            for grant in progress['grants']
        }
        self.assertIn(('view', 'reading_state_v1', ('select',)), grants)


if __name__ == '__main__':
    unittest.main()
