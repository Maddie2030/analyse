from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class LocalDatabaseProtectionDeploymentTests(unittest.TestCase):
    def test_backup_agent_has_one_explicit_host_recovery_bind(self):
        compose = (ROOT / "deploy/compose/docker-compose.hybrid-stateful.yml").read_text()
        self.assertIn(
            '${MREADER_DB_PROTECTION_ROOT:?MREADER_DB_PROTECTION_ROOT is required}:/mreader-db-protection',
            compose,
        )
        self.assertIn('POSTGRES_BACKUP_LOCAL_ROOT: /mreader-db-protection', compose)
        self.assertIn('POSTGRES_BACKUP_SPOOL: /mreader-db-protection/staging/backup-agent', compose)
        self.assertIn('POSTGRES_BACKUP_CATALOG_SYNC_SECONDS: ${POSTGRES_BACKUP_CATALOG_SYNC_SECONDS:-300}', compose)
        self.assertNotIn('backup_spool:', compose)
        self.assertNotIn('HYBRID_BACKUP_SPOOL_VOLUME_NAME', compose)
        backup_agent = compose.split("  backup_agent:", 1)[1].split("\n  migrate:", 1)[0]
        self.assertNotIn("NAS_SEAWEEDFS", backup_agent)
        self.assertNotIn("POSTGRES_BACKUP_NAS_PATH", backup_agent)
        self.assertNotIn("POSTGRES_BACKUP_EXPECTED_PHYSICAL_ROOT", backup_agent)
        self.assertNotIn("POSTGRES_BACKUP_REQUIRE_STORAGE_PROOF", backup_agent)
        self.assertNotIn("POSTGRES_BACKUP_VERIFY_DOWNLOAD", backup_agent)

    def test_retention_defaults_are_consistent(self):
        compose = (ROOT / "deploy/compose/docker-compose.hybrid-stateful.yml").read_text()
        example = (ROOT / ".env.example").read_text()
        config = (ROOT / "services/scraper_service/app/config.py").read_text()
        agent = (ROOT / "scripts/backup/backup-agent.sh").read_text()
        self.assertIn('POSTGRES_BACKUP_DAILY_RETENTION_DAYS:-4', compose)
        self.assertIn('POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS:-2', compose)
        self.assertIn('POSTGRES_BACKUP_DAILY_RETENTION_DAYS=4', example)
        self.assertIn('POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=2', example)
        self.assertIn('postgres_backup_daily_retention_days: int = 4', config)
        self.assertIn('postgres_backup_snapshot_retention_days: int = 2', config)
        self.assertIn('POSTGRES_BACKUP_DAILY_RETENTION_DAYS:-4', agent)
        self.assertIn('POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS:-2', agent)

    def test_backup_image_contains_the_local_store_validator(self):
        dockerfile = (ROOT / "ops/postgres-backup/Dockerfile").read_text()
        self.assertIn(
            'COPY scripts/backup/local-recovery-store.sh /usr/local/bin/mreader-local-recovery-store',
            dockerfile,
        )
        self.assertIn(
            'COPY scripts/backup/sync-local-recovery-catalog.sh /usr/local/bin/mreader-sync-recovery-catalog',
            dockerfile,
        )

    def test_agent_periodically_rebuilds_the_database_projection(self):
        agent = (ROOT / "scripts/backup/backup-agent.sh").read_text()
        self.assertIn('sync_local_catalog_if_due', agent)
        self.assertIn('mreader-sync-recovery-catalog', agent)
        self.assertIn('$LOCAL_STORE" copy-artifact', agent)
        self.assertNotIn("NAS_SEAWEEDFS", agent)
        self.assertNotIn("remote_file_url", agent)
        self.assertNotIn("curl ", agent)


if __name__ == "__main__":
    unittest.main()
