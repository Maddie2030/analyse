import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _function_body(path, pattern, label):
    text = path.read_text()
    match = re.search(pattern, text, flags=re.S)
    if match is None:
        raise AssertionError(f'{label} implementation must be discoverable')
    return text, match.group(0)


class PublicationEventFinalizationTests(unittest.TestCase):
    def test_update_chapter_publication_attempt_is_blocked_at_store_and_http(self):
        store, store_body = _function_body(
            ROOT / 'services/catalog_go/internal/store/store.go',
            r'func \(s \*Store\) UpdateChapter\(.*?\n}\n\nfunc ',
            'UpdateChapter',
        )
        self.assertIn('ErrPublicationRequiresMedia', store)
        self.assertIn('return model.Chapter{}, ErrPublicationRequiresMedia', store_body)
        self.assertNotIn('enqueueChapterPublishedTx(', store_body)
        self.assertNotIn('catalog-chapter-update', store_body)

        _api, api_body = _function_body(
            ROOT / 'services/catalog_go/internal/httpapi/api.go',
            r'func \(a \*API\) updateChapter\(.*?\n}\n\nfunc ',
            'updateChapter HTTP handler',
        )
        self.assertIn('store.ErrPublicationRequiresMedia', api_body)
        self.assertIn('http.StatusConflict', api_body)
        self.assertIn('Media', api_body)

    def test_commit_publication_is_only_catalog_chapter_published_writer(self):
        store_files = list((ROOT / 'services/catalog_go/internal/store').glob('*.go'))
        writers = []
        for path in store_files:
            text = path.read_text()
            if path.name == 'events.go':
                continue
            if 'enqueueChapterPublishedTx(' in text:
                writers.append(path.name)
        self.assertEqual(['publication.go'], writers)

    def test_notification_dedupe_remains_publication_revision_scoped(self):
        events = (ROOT / 'services/notification_worker/internal/events/events.go').read_text()
        store = (ROOT / 'services/notification_worker/internal/store/store.go').read_text()
        self.assertIn('base + ":revision:" + strconv.FormatInt(payload.ChapterRevision, 10)', events)
        self.assertIn('ChapterPublishedDedupeKey(envelope.EventVersion, payload)', store)
        self.assertIn('insertChapterNotifications(ctx, tx, envelope.EventID, dedupeKey, payload)', store)


if __name__ == '__main__':
    unittest.main()
