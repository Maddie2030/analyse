"""Exercise operator entry points in a private fixture with recording Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RecoveryOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env_file = self.root / '.env'
        self.recovery_root = self.root / 'home recovery'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ['scripts/env/env-lib.sh', 'scripts/env/migrate-known-settings.sh',
                     'scripts/env/db-protection-root.sh', 'scripts/env/resolve-db-protection-root.sh',
                     'scripts/backup/postgres-backup.sh', 'scripts/backup/configure-replication.sh',
                     'scripts/storage/backup-storage-doctor.sh']:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
            dest.chmod(0o755)
        (self.bin / 'docker').write_text(
            '#!/usr/bin/env python3\nimport json, os, sys\n'
            'with open(os.environ["CALLS"], "a") as out:\n'
            ' out.write(json.dumps({"args":sys.argv[1:], "root":os.environ.get("MREADER_DB_PROTECTION_ROOT")})+"\\n")\n'
        )
        (self.bin / 'docker').chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        CALLS=str(self.root / 'calls'))
        self.env.pop('MREADER_DB_PROTECTION_ROOT', None)
        self.env.pop('MREADER_ENV_FILE', None)
        self.initial = f'MREADER_DB_PROTECTION_ROOT={self.recovery_root}\nSECRET_KEEP=unchanged\n'

    def run_script(self, name, *args):
        return subprocess.run(['bash', str(self.root / name), *args], env=self.env,
                              cwd=self.root, text=True, capture_output=True)

    def migrate(self):
        result = self.run_script('scripts/env/migrate-known-settings.sh', str(self.env_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_known_defaults_migrate_once_with_original_configuration_preserved(self):
        original = self.initial + ('POSTGRES_BACKUP_DAILY_RETENTION_DAYS=7\n'
                                   'POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=14\n'
                                   'POSTGRES_BACKUP_NAS_PATH=backups/previous-installation\n')
        self.env_file.write_text(original)
        self.migrate()
        current = self.env_file.read_text()
        self.assertIn('POSTGRES_BACKUP_DAILY_RETENTION_DAYS=4\n', current)
        self.assertIn('POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=2\n', current)
        self.assertIn('POSTGRES_BACKUP_NAS_PATH=backups/previous-installation\n', current)
        self.assertNotIn('POSTGRES_BACKUP_REQUIRE_STORAGE_PROOF=', current)
        before = self.root / '.env.before-rc485-local-recovery'
        self.assertEqual(before.read_text(), original)
        self.migrate()
        self.assertEqual(self.env_file.read_text(), current)
        self.assertEqual(before.read_text(), original)

    def test_custom_retention_is_preserved(self):
        original = self.initial + 'POSTGRES_BACKUP_DAILY_RETENTION_DAYS=9\nPOSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=3\n'
        self.env_file.write_text(original)
        self.migrate()
        self.assertEqual(self.env_file.read_text(), original + 'MREADER_DB_PROTECTION_CONFIG_VERSION=1\n')
        self.assertEqual((self.root / '.env.before-rc485-local-recovery').read_text(), original)

    def test_operator_can_select_a_former_default_after_the_one_time_migration(self):
        self.env_file.write_text(self.initial)
        self.migrate()
        selected = self.env_file.read_text().replace('POSTGRES_BACKUP_DAILY_RETENTION_DAYS=4',
                                                    'POSTGRES_BACKUP_DAILY_RETENTION_DAYS=7')
        self.env_file.write_text(selected)
        self.migrate()
        self.assertEqual(self.env_file.read_text(), selected)

    def test_missing_retention_uses_requested_defaults(self):
        self.env_file.write_text(self.initial)
        self.migrate()
        self.assertIn('POSTGRES_BACKUP_DAILY_RETENTION_DAYS=4\n', self.env_file.read_text())
        self.assertIn('POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=2\n', self.env_file.read_text())

    def test_standalone_backup_resolves_saved_root_before_docker(self):
        self.env_file.write_text(self.initial)
        result = self.run_script('scripts/backup/postgres-backup.sh', 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['root'], str(self.recovery_root))
        self.assertEqual(calls[0]['args'][-2:], ['backup_agent', 'status'])

    def test_conflicting_roots_block_before_docker(self):
        self.env_file.write_text(self.initial)
        self.env['MREADER_DB_PROTECTION_ROOT'] = str(self.root / 'different root')
        result = self.run_script('scripts/backup/postgres-backup.sh', 'status')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'calls').exists())

    def test_storage_doctor_uses_the_same_local_owner_with_selected_env(self):
        custom = self.root / 'selected.env'
        custom.write_text(self.initial)
        result = self.run_script('scripts/storage/backup-storage-doctor.sh', str(custom))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(calls[-1]['args'][-2:], ['backup_agent', 'self-test'])
        self.assertEqual(calls[-1]['root'], str(self.recovery_root))
        self.assertIn(str(custom), calls[-1]['args'])
        self.assertEqual(len(calls), 1)  # No DB startup, replication repair or scheduler stop.

    def test_selected_env_also_reaches_explicit_replication_setup(self):
        custom = self.root / 'selected.env'
        custom.write_text(self.initial + 'POSTGRES_BACKUP_REPLICATION_PASSWORD=fixture-only\n')
        self.env['MREADER_ENV_FILE'] = str(custom)
        result = self.run_script('scripts/backup/postgres-backup.sh', 'self-test')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertIn(str(custom), call['args'])
            self.assertEqual(call['root'], str(self.recovery_root))


if __name__ == '__main__':
    unittest.main()
