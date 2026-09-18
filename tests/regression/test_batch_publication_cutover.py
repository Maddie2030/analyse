from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
BATCH = (ROOT / 'services/scraper_service/app/batch_queue.py').read_text()
INGESTION = (ROOT / 'services/scraper_service/app/ingestion.py').read_text()
MEDIA_JOBS = (ROOT / 'services/image_service/app/routers/jobs.py').read_text()
MEDIA_MAIN = (ROOT / 'services/image_service/app/main.py').read_text()


def function_block(source: str, name: str) -> str:
    match = re.search(rf'^async def {re.escape(name)}\(', source, re.M)
    assert match, f'{name} missing'
    start = match.start()
    next_match = re.search(r'^async def |^def |^@', source[match.end():], re.M)
    end = match.end() + next_match.start() if next_match else len(source)
    return source[start:end]


class BatchPublicationCutoverTests(unittest.TestCase):
    def test_batch_worker_no_longer_owns_final_transform_or_catalog_write(self):
        body = function_block(BATCH, 'process_item')
        for legacy in (
            'process_page(',
            'build_page_path(',
            'publish_chapter_record(',
            'reserve_storage_paths(',
            'new_seed(',
        ):
            self.assertNotIn(legacy, body)
        self.assertIn('submit_to_media(', body)
        self.assertIn('wait_for_media_publication(', body)
        self.assertIn('ensure_ingestion_operation(', body)
        self.assertIn('catalog_receipt', body)

    def test_batch_archive_is_spooled_not_full_bytes(self):
        self.assertIn('SpooledTemporaryFile', BATCH)
        self.assertIn('zipfile.ZipFile', BATCH)
        self.assertIn('archive=archive_file', BATCH)

    def test_background_media_transport_preserves_retained_actor(self):
        self.assertIn('requesting_actor_id', INGESTION)
        self.assertIn('X-MReader-Requesting-Actor-ID', INGESTION)
        self.assertIn('/internal/v1/media/jobs/', INGESTION)
        self.assertIn('path=f"chapter/{submission.series_slug}/{submission.chapter_slug}"', INGESTION)
        self.assertIn('actor_id', MEDIA_JOBS)
        self.assertIn('X-MReader-Requesting-Actor-ID', MEDIA_JOBS)
        self.assertIn('/internal/v1/media/jobs', MEDIA_MAIN)


if __name__ == '__main__':
    unittest.main()
