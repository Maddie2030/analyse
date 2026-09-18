from pathlib import Path
import re
import unittest

from p10_1_ui_support import require_all

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "frontend" / "src" / "pages" / "SeriesDetail.tsx"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "SeriesScreen.kt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101SeriesUiTests(unittest.TestCase):
    def test_web_chapter_pagination_keeps_previous_on_empty_later_page(self):
        source = read(WEB)
        self.assertRegex(
            source,
            r"\(\(series\.chapters\?\.length\s*\|\|\s*0\)\s*>\s*0\s*\|\|\s*chapterOffset\s*>\s*0\)\s*&&",
            "Series chapter pagination must remain recoverable from an empty later page",
        )

    def test_web_social_metrics_do_not_render_unavailable_as_zero(self):
        source = read(WEB)
        self.assertIn("socialMetricsError", source)
        self.assertNotIn("socialMetrics?.rating_count ?? 0", source)
        self.assertNotIn("socialMetrics?.bookmark_count ?? 0", source)
        self.assertNotIn("socialMetrics?.subscription_count ?? 0", source)
        self.assertIn("Social metrics are unavailable", source)

    def test_web_resets_social_identity_state_when_series_changes(self):
        source = read(WEB)
        effect = re.search(
            r"useEffect\(\(\)\s*=>\s*\{(?P<body>.*?)return \(\) => \{ cancelled = true; \};\s*\}, \[user, series\?\.id, series\?\.slug\]\);",
            source,
            re.S,
        )
        self.assertIsNotNone(effect)
        body = effect.group("body")
        self.assertIn("setSocialMetrics(null);", body)
        self.assertIn("setBookmarked(null);", body)
        self.assertIn("setSubscribed(null);", body)

    def test_android_unknown_viewer_state_cannot_mutate_relationships(self):
        source = read(ANDROID)
        require_all(self, source, (
            "relationshipBusy || (signedIn && viewerState == null)",
            "!ratingBusy && (!signedIn || viewerState != null)",
            "socialMetrics?.let { metrics ->",
        ))


if __name__ == "__main__":
    unittest.main()
