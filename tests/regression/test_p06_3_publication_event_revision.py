import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PublicationEventRevisionTests(unittest.TestCase):
    def test_v2_schema_requires_positive_chapter_revision(self):
        path = ROOT / 'contracts/events/v2/chapter.published.schema.json'
        self.assertTrue(path.exists(), 'chapter.published v2 schema is required')
        schema = json.loads(path.read_text())
        self.assertIn('chapter_revision', schema['required'])
        self.assertEqual({'type': 'integer', 'minimum': 1}, schema['properties']['chapter_revision'])

    def test_registry_keeps_v1_and_adds_v2(self):
        rows = (ROOT / 'contracts/events/registry.tsv').read_text().splitlines()
        self.assertIn('chapter.published\tchapter.published\t1\tseries_id\tv1/chapter.published.schema.json', rows)
        self.assertIn('chapter.published\tchapter.published\t2\tseries_id\tv2/chapter.published.schema.json', rows)

    def test_catalog_emits_v2_and_committed_chapter_revision(self):
        events = (ROOT / 'services/catalog_go/internal/store/events.go').read_text()
        publication = (ROOT / 'services/catalog_go/internal/store/publication.go').read_text()
        self.assertIn('chapterPublishedEventVersion = 2', events)
        self.assertIn('"chapter_revision": chapterRevision', events)
        self.assertIn('"v2/chapter.published.schema.json"', events)
        self.assertRegex(
            publication,
            re.compile(r'enqueueChapterPublishedTx\(\s*ctx, tx, chapterID, command\.Manifest\.SeriesID, chapterRevision,', re.S),
        )

    def test_notification_worker_uses_versioned_decode_and_revision_dedupe(self):
        event_src = (ROOT / 'services/notification_worker/internal/events/events.go').read_text()
        store_src = (ROOT / 'services/notification_worker/internal/store/store.go').read_text()
        self.assertIn('ChapterRevision int64', event_src)
        self.assertIn('func DecodeChapterPublished(raw json.RawMessage, eventVersion int)', event_src)
        self.assertIn('func ChapterPublishedDedupeKey(eventVersion int, payload ChapterPublished)', event_src)
        self.assertIn('DecodeChapterPublished(envelope.Payload, envelope.EventVersion)', store_src)
        self.assertIn('ChapterPublishedDedupeKey(envelope.EventVersion, payload)', store_src)
        self.assertIn('insertChapterNotifications(ctx, tx, envelope.EventID, dedupeKey, payload)', store_src)

    def test_real_notification_db_suite_declares_revision_dedupe_case(self):
        path = ROOT / 'services/notification_worker/internal/store/chapter_published_postgres_test.go'
        self.assertTrue(path.exists(), 'real notification revision-dedupe DB test is required')
        text = path.read_text()
        self.assertIn('TestChapterPublishedV2DedupeIsPublicationRevisionScoped', text)
        self.assertIn('MREADER_TEST_POSTGRES_DSN', text)
        self.assertIn('first := v2.process(t, 2, 1)', text)
        self.assertIn('retry := v2.process(t, 2, 1)', text)
        self.assertIn('second := v2.process(t, 2, 2)', text)
        self.assertIn('legacyFirst := legacy.process(t, 1, 0)', text)
        self.assertIn('legacyRetry := legacy.process(t, 1, 0)', text)
        self.assertIn('Inserted != 1', text)



if __name__ == '__main__':
    unittest.main()
