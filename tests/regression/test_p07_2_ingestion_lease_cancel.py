from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text()


class IngestionLeaseCancelTests(unittest.TestCase):
    def test_scraper_recovery_and_cancel_share_catalog_operation_fence_and_receipt_first_decision(self):
        bridge = text('services/scraper_service/app/publication_bridge.py')
        self.assertIn('async def _lock_ingestion_operation_tx(', bridge)
        self.assertIn("pg_advisory_xact_lock(hashtextextended($1, 485063))", bridge)
        self.assertIn('async def _catalog_receipt_for_operation_tx(', bridge)
        self.assertIn('FROM catalog_mutation_receipts', bridge)
        self.assertIn('async def _current_ingestion_outcome_tx(', bridge)
        current = bridge.split('async def _current_ingestion_outcome_tx(', 1)[1].split('async def ', 1)[0]
        self.assertIn('FROM ingestion_operations', current)
        self.assertNotIn('_current_ingestion_outcome_tx(', current)
        for name in ('recover_ingestion_operation_lease_tx', 'cancel_ingestion_operation_tx'):
            self.assertIn(f'async def {name}(', bridge)
            body = bridge.split(f'async def {name}(', 1)[1].split('\nasync def ', 1)[0]
            self.assertLess(body.index('_lock_ingestion_operation_tx('), body.index('_catalog_receipt_for_operation_tx('))

    def test_canonical_cancelled_operation_cannot_be_stale_requeued(self):
        batch = text('services/scraper_service/app/batch_queue.py')
        self.assertIn('async def _recover_stale_batch_item_tx(', batch)
        self.assertIn('async def _recover_stale_batch_items_tx(', batch)
        recover = batch.split('async def _recover_stale_batch_item_tx(', 1)[1].split('\nasync def ', 1)[0]
        self.assertIn('recover_ingestion_operation_lease_tx(', recover)
        self.assertIn("canonical_status == 'cancelled'", recover)
        self.assertIn("status='discarded'", recover)
        # Canonical authority must be consulted before legacy state is moved toward queued.
        self.assertLess(recover.index('recover_ingestion_operation_lease_tx('), recover.index("status='queued'"))
        top = batch.split('async def recover_batch_jobs(', 1)[1].split('\nasync def ', 1)[0]
        self.assertIn('_recover_stale_batch_items_tx(', top)

    def test_media_worker_mutations_are_fenced_by_claimed_media_generation(self):
        operations = text('services/image_service/app/media_operations.py')
        worker = text('services/image_service/app/worker.py')
        self.assertIn('class MediaOperationLeaseLost(', operations)
        for name in ('heartbeat_media_operation', 'mark_media_retry'):
            block = operations.split(f'async def {name}(', 1)[1].split('\nasync def ', 1)[0]
            self.assertIn('expected_generation', block, name)
            self.assertIn('media_generation', block, name)
        for name in ('complete_media_operation', 'fail_media_operation'):
            block = operations.split(f'async def {name}(', 1)[1].split('\nasync def ', 1)[0]
            self.assertIn('expected_generation', block, name)
        for name in ('_persist_media_completion', '_persist_media_failure'):
            block = operations.split(f'async def {name}(', 1)[1].split('\nasync def ', 1)[0]
            self.assertIn('expected_generation', block, name)
            self.assertIn('media_generation', block, name)
        self.assertIn("claimed_generation = int(operation.get('media_generation') or 0)", worker)
        self.assertIn('if claimed_generation <= 0:', worker)
        self.assertIn('expected_generation=claimed_generation', worker)
        self.assertIn('_media_operation_heartbeat(job_id, claimed_generation, heartbeat_stop)', worker)
        self.assertIn('_mark_retry(job_id, error, claimed_generation)', worker)
        self.assertIn('claimed_generation,\n            )', worker)

    def test_unknown_or_lost_media_lease_preserves_deterministic_outputs_for_reconciliation(self):
        ingestion = text('services/image_service/app/services/chapter_ingestion.py')
        worker = text('services/image_service/app/worker.py')
        self.assertIn('MediaOperationLeaseLost', ingestion)
        self.assertRegex(
            ingestion,
            r'(?s)except MediaOperationLeaseLost:.*?preserv',
            msg='lease loss must preserve deterministic outputs owned by a replacement generation',
        )
        self.assertIn('except MediaOperationLeaseLost', worker)
        lease_block = worker.split('except MediaOperationLeaseLost', 1)[1][:1200]
        self.assertNotIn('delete_via_filer', lease_block)

    def test_series_draft_cancel_and_recovery_use_canonical_ingestion_fence(self):
        series = (ROOT / "services/scraper_service/app/series_drafts.py").read_text()
        self.assertIn("cancel_ingestion_operation_tx", series)
        self.assertIn("recover_ingestion_operation_lease_tx", series)
        self.assertIn("async def _cancel_draft_chapter_publications_tx", series)
        self.assertRegex(
            series,
            r"(?s)async def cancel_scraper_operation\(.*?_cancel_draft_chapter_publications_tx\(",
        )
        self.assertRegex(
            series,
            r"(?s)async def request_publish_cancel\(.*?_cancel_draft_chapter_publications_tx\(",
        )
        self.assertRegex(
            series,
            r"(?s)async def recover_incomplete_chapter_publish_jobs\(.*?_recover_draft_chapter_publication_tx\(",
        )
        self.assertRegex(
            series,
            r"(?s)async def _recover_stale_parent_publish_tx\(.*?_recover_draft_chapter_publication_tx\(",
        )



if __name__ == '__main__':
    unittest.main()
