import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'db' / 'migrations' / '056_media_completion_evidence_immutability.sql'


class MediaCompletionEvidenceImmutabilityTests(unittest.TestCase):
    def test_forward_migration_seals_completed_publication_evidence(self):
        self.assertTrue(MIGRATION.exists(), 'forward-only evidence immutability migration is required')
        text = MIGRATION.read_text(encoding='utf-8')
        self.assertIn('CREATE OR REPLACE FUNCTION enforce_media_completion_evidence_immutability', text)
        self.assertIn('CREATE TRIGGER trg_media_completion_evidence_immutability', text)
        self.assertIn("OLD.completion_evidence IS NOT NULL", text)
        self.assertIn("NEW.completion_evidence IS DISTINCT FROM OLD.completion_evidence", text)
        for column in (
            'publication_operation_id',
            'publication_actor_id',
            'source_revision',
            'manifest_sha256',
            'publication_page_count',
            'media_generation',
        ):
            self.assertIn(f'NEW.{column} IS DISTINCT FROM OLD.{column}', text)

    def test_trigger_is_scoped_to_evidence_columns_not_all_media_updates(self):
        text = MIGRATION.read_text(encoding='utf-8') if MIGRATION.exists() else ''
        self.assertIn('BEFORE UPDATE OF', text)
        self.assertNotIn('BEFORE UPDATE ON media_operations', text)


if __name__ == '__main__':
    unittest.main()
