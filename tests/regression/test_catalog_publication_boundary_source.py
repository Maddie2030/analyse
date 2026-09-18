from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'db/migrations/054_catalog_publication_boundary.sql'
MEDIA = ROOT / 'services/image_service/app/media_operations.py'
STORE = ROOT / 'services/catalog_go/internal/store/publication.go'
MODEL = ROOT / 'services/catalog_go/internal/model/publication.go'


class CatalogPublicationBoundarySourceTests(unittest.TestCase):
    def test_migration_extends_existing_media_ledger_and_adds_only_catalog_receipt_table(self):
        self.assertTrue(MIGRATION.is_file())
        text = MIGRATION.read_text()
        self.assertIn('ALTER TABLE media_operations', text)
        self.assertIn('completion_evidence JSONB', text)
        self.assertIn('media_generation BIGINT', text)
        self.assertIn('CREATE OR REPLACE VIEW media_completion_evidence_v1', text)
        self.assertIn('CREATE TABLE IF NOT EXISTS catalog_mutation_receipts', text)
        self.assertIn('catalog_revision BIGINT', text)
        self.assertNotIn('CREATE TABLE media_completion', text)
        receipt_block = text.split('CREATE TABLE IF NOT EXISTS catalog_mutation_receipts', 1)[1].split(');', 1)[0]
        self.assertNotIn('ON DELETE CASCADE', receipt_block)
        self.assertNotIn('REFERENCES chapters', receipt_block)
        self.assertNotIn('REFERENCES series', receipt_block)

    def test_media_has_explicit_durable_publication_evidence_writer(self):
        text = MEDIA.read_text()
        self.assertIn('async def record_publication_completion_evidence(', text)
        for field in ('actor_id', 'source_revision', 'media_generation', 'manifest_sha256', 'page_count'):
            self.assertIn(field, text)
        self.assertIn("status != 'completed'", text)
        self.assertIn('completion_evidence', text)

    def test_catalog_model_mirrors_publication_and_receipt_contract(self):
        self.assertTrue(MODEL.is_file())
        text = MODEL.read_text()
        for symbol in ('PublicationCommand', 'MediaCompletionEvidence', 'CatalogMutationReceipt', 'PublicationPage'):
            self.assertIn('type '+symbol, text)
        for field in ('IdempotencyKey', 'PayloadSHA256', 'ExpectedRevision', 'MediaGeneration', 'ManifestSHA256'):
            self.assertIn(field, text)

    def test_catalog_store_uses_one_transaction_for_receipt_target_pages_revision_and_event(self):
        self.assertTrue(STORE.is_file())
        text = STORE.read_text()
        self.assertIn('func (s *Store) CommitPublication(', text)
        self.assertIn('Begin(ctx)', text)
        self.assertIn('catalog_mutation_receipts', text)
        self.assertIn('media_completion_evidence_v1', text)
        self.assertIn('FOR UPDATE', text)
        self.assertIn('INSERT INTO pages', text)
        self.assertIn('catalog_revision', text)
        self.assertIn('enqueueChapterPublishedTx', text)
        self.assertIn('enqueueCleanupTx', text)
        self.assertIn('model.ValidatePublicationCommand(command)', text)
        self.assertIn('pg_advisory_xact_lock', text)
        self.assertIn('tx.Commit(ctx)', text)


    def test_catalog_reads_sealed_media_evidence_without_write_lock(self):
        text = STORE.read_text()
        block = text.split('func publicationEvidenceTx', 1)[1].split('func validatePublicationEvidence', 1)[0]
        self.assertIn('media_completion_evidence_v1', block)
        self.assertNotIn('FOR UPDATE', block)

    def test_same_key_different_payload_conflicts_and_identical_receipt_replays(self):
        text = STORE.read_text()
        self.assertIn('PayloadSHA256', text)
        self.assertIn('ErrIdempotencyConflict', text)
        self.assertIn('return existing, nil', text)


if __name__ == '__main__':
    unittest.main()
