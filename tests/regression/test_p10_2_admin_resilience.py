from pathlib import Path
import re
import unittest

from p10_1_ui_support import read_text, require_all

ROOT = Path(__file__).resolve().parents[2]
WEB_DATABASE = ROOT / "frontend" / "src" / "pages" / "AdminDatabase.tsx"
WEB_SCRAPER_NEW = ROOT / "frontend" / "src" / "pages" / "AdminScraperNewSeries.tsx"
WEB_ADMIN = ROOT / "frontend" / "src" / "pages" / "AdminDashboard.tsx"
WEB_SERIES = ROOT / "frontend" / "src" / "pages" / "SeriesDetail.tsx"


class P102AdminResilienceTests(unittest.TestCase):
    def test_admin_actions_use_current_state_and_single_flight_guards(self):
        cases = (
            (
                "database reload current cursor",
                WEB_DATABASE,
                (
                    "const backupCursorRef = useRef<string | null>(backupCursor);",
                    "backupCursorRef.current = backupCursor;",
                    "const cursor = backupCursorRef.current;",
                    "api.getDatabaseProtection(75, cursor)",
                ),
            ),
            (
                "series delete",
                WEB_ADMIN,
                (
                    "const [deletingSeriesId, setDeletingSeriesId] = useState<string | null>(null);",
                    "if (deletingSeriesId) return;",
                    "setDeletingSeriesId(id);",
                    "setDeletingSeriesId(null);",
                    "disabled={deletingSeriesId === s.id}",
                ),
            ),
            (
                "chapter delete",
                WEB_SERIES,
                (
                    "const [chapterDeleteBusyId, setChapterDeleteBusyId] = useState<string | null>(null);",
                    "if (!series || chapterDeleteBusyId) return;",
                    "setChapterDeleteBusyId(chapter.id);",
                    "setChapterDeleteBusyId(null);",
                    "disabled={chapterDeleteBusyId === ch.id}",
                ),
            ),
        )
        for label, path, needles in cases:
            with self.subTest(label=label):
                require_all(self, read_text(path), needles)

    def test_new_series_status_poll_is_single_flight(self):
        source = read_text(WEB_SCRAPER_NEW)
        block = re.search(
            r"let cancelled = false;\s+let pollInFlight = false;(?P<body>.*?)const timer = window\.setInterval",
            source,
            re.S,
        )
        self.assertIsNotNone(block, "expected single-flight state beside the staging/publish poll")
        require_all(self, block.group("body"), (
            "if (pollInFlight) return;",
            "pollInFlight = true;",
            "pollInFlight = false;",
        ))

    def test_social_metrics_refresh_is_scoped_to_series_and_account_identity(self):
        source = read_text(WEB_SERIES)
        require_all(self, source, (
            "const socialMetricsRequestRef = useRef(0);",
            "const identity = relationshipIdentityRef.current;",
        ))
        refresh = re.search(r"const refreshSocialMetrics = useCallback\(async \(\) => \{(?P<body>.*?)\n  \}, \[", source, re.S)
        self.assertIsNotNone(refresh)
        require_all(self, refresh.group("body"), (
            "const requestId = ++socialMetricsRequestRef.current;",
            "requestId !== socialMetricsRequestRef.current || identity !== relationshipIdentityRef.current",
        ))


if __name__ == "__main__":
    unittest.main()
