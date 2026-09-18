from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'db/migrations/053_legacy_operation_reconciliation.sql'
M050 = ROOT / 'db/migrations/050_retire_backup_requests.sql'


class LegacyOperationReconciliationSourceTests(unittest.TestCase):
    def test_forward_repair_exists_without_rewriting_historical_migration(self):
        self.assertTrue(MIGRATION.is_file(), 'missing forward repair migration 053')
        self.assertIn("WHEN legacy.status = 'queued'", M050.read_text())
        text = MIGRATION.read_text()
        self.assertIn("metadata->>'migrated_from' = 'backup_requests'", text)
        self.assertIn("phase = 'migration-recovery-required'", text)
        self.assertIn("status = 'failed'", text)

    def test_unproven_migrated_queue_cannot_remain_active(self):
        text = MIGRATION.read_text()
        self.assertIn("phase = 'migrated-queued'", text)
        self.assertIn("status = 'queued'", text)
        self.assertIn('completed_at = COALESCE(completed_at, now())', text)
        self.assertIn('request a new backup', text.lower())

    def test_terminal_legacy_records_are_not_requeued(self):
        text = MIGRATION.read_text()
        # The repair is intentionally narrow: only the legacy migrated-queued
        # outcome is rewritten. Verified/failed/cancelled history stays history.
        self.assertNotIn("status = 'verified'", text)
        self.assertNotIn("status = 'completed'", text)

    def test_scraper_history_is_not_retired_before_ingestion_header_exists(self):
        text = MIGRATION.read_text()
        self.assertNotIn('DROP TABLE scraper_history', text)
        self.assertNotIn('CREATE TABLE ingestion_operations', text)


if __name__ == '__main__':
    unittest.main()
