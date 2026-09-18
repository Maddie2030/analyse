from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.diagnostics.support import load_script

HELPERS = Path(__file__).resolve().parents[1] / 'api' / 'helpers.py'


def load_helpers():
    return load_script(HELPERS)


class JourneyRecorderTests(unittest.TestCase):
    def test_records_pass_and_failure_without_secrets(self):
        helpers = load_helpers()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'journey_actions.jsonl'
            recorder = helpers.JourneyRecorder(path, 'test_user_actor_journeys.py::test_user_engagement_journey')
            recorder.record('bookmark-series', intended='bookmark is persisted', observed={'bookmarked': True, 'token': 'super-secret-token', 'source_url': 'https://example.invalid/chapter?token=query-secret&chapter=1'}, passed=True)
            with self.assertRaises(AssertionError):
                recorder.assert_true('library-contains-series', False, intended='bookmarked series appears in library', observed='missing')
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(['bookmark-series', 'library-contains-series'], [row['action'] for row in rows])
            self.assertTrue(rows[0]['passed'])
            self.assertFalse(rows[1]['passed'])
            self.assertNotIn('super-secret-token', path.read_text(encoding='utf-8'))
            self.assertNotIn('query-secret', path.read_text(encoding='utf-8'))
            self.assertIn('***', path.read_text(encoding='utf-8'))

    def test_assert_equal_records_observed_and_expected(self):
        helpers = load_helpers()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'journey_actions.jsonl'
            recorder = helpers.JourneyRecorder(path, 'test_admin_actor_journeys.py::test_admin_catalog_journey')
            recorder.assert_equal('status-change', 'hiatus', 'hiatus', intended='admin status is visible publicly')
            row = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual('hiatus', row['observed'])
            self.assertEqual('hiatus', row['expected'])
            self.assertTrue(row['passed'])


if __name__ == '__main__':
    unittest.main()
