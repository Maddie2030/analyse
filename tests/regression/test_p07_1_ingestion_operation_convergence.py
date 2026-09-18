from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text()


class IngestionOperationConvergenceTests(unittest.TestCase):
    def test_scraper_media_submissions_carry_canonical_source_kind(self):
        ingestion = text('services/scraper_service/app/ingestion.py')
        drafts = text('services/scraper_service/app/drafts.py')
        batch = text('services/scraper_service/app/batch_queue.py')
        series = text('services/scraper_service/app/series_drafts.py')

        self.assertIn('source_kind: str | None = None', ingestion)
        self.assertIn('"source_kind": submission.source_kind', ingestion)
        self.assertIn('source_kind="existing-series-scrape"', drafts)
        self.assertIn('source_kind="batch-upload"', batch)
        self.assertIn('source_kind="new-series-scrape"', series)

    def test_manual_media_acceptance_creates_header_in_acceptance_transaction(self):
        jobs = text('services/image_service/app/routers/jobs.py')
        operations = text('services/image_service/app/media_operations.py')

        self.assertIn('create_ingestion_header=True', jobs)
        self.assertIn('expected_source_kind="manual-upload"', jobs)
        self.assertRegex(operations, r'INSERT INTO ingestion_operations\s*\(')
        self.assertIn('source_kind', operations)
        self.assertIn('requesting_actor_id', operations)
        self.assertIn("'running'", operations)
        self.assertIn("'media_transform'", operations)

        chapter_submit = re.search(
            r'async def _submit_chapter_job\(.*?\n@router\.post\(',
            jobs,
            flags=re.S,
        )
        self.assertIsNotNone(chapter_submit)
        acceptance = re.findall(
            r'async with AsyncSessionLocal\(\) as db:.*?await db\.commit\(\)',
            chapter_submit.group(0),
            flags=re.S,
        )
        body = next((block for block in acceptance if 'create_media_operation(' in block), '')
        self.assertTrue(body, 'chapter media acceptance transaction must be discoverable')
        self.assertIn('authorize_ingestion_operation(', body)
        self.assertIn('create_media_operation(', body)
        self.assertLess(body.index('authorize_ingestion_operation('), body.index('create_media_operation('))

    def test_internal_media_acceptance_validates_existing_header_without_creating_it(self):
        jobs = text('services/image_service/app/routers/jobs.py')
        operations = text('services/image_service/app/media_operations.py')

        self.assertIn('create_ingestion_header=False', jobs)
        self.assertIn('source_kind = authority.expected_source_kind or job_input.source_kind', jobs)
        self.assertIn('Internal chapter ingestion requires source_kind.', jobs)
        self.assertIn('cancel_requested_at', operations)
        for field in (
            'source_kind',
            'requesting_actor_id',
            'source_revision',
            'lease_generation',
            'status',
        ):
            self.assertIn(field, operations)
        self.assertIn('ingestion operation source kind does not match', operations)
        self.assertIn('ingestion operation is owned by another requesting actor', operations)
        self.assertIn('ingestion operation source revision is stale', operations)
        self.assertIn('ingestion operation lease generation is stale', operations)
        self.assertIn('ingestion operation is cancelled', operations)

    def test_internal_media_does_not_become_a_second_ingestion_coordinator(self):
        jobs = text('services/image_service/app/routers/jobs.py')
        submit = re.search(
            r'async def internal_submit_chapter_job\(.*?\n\s*\)',
            jobs,
            flags=re.S,
        )
        self.assertIsNotNone(submit)
        nearby = jobs[submit.start(): submit.start() + 700]
        self.assertIn('create_ingestion_header=False', nearby)
        self.assertNotIn('manual-upload', nearby)


if __name__ == '__main__':
    unittest.main()
