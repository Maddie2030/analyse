from pathlib import Path
import re
import unittest

from p10_1_ui_support import read_text

ROOT = Path(__file__).resolve().parents[2]
WEB_SEARCH = ROOT / "frontend" / "src" / "pages" / "AdvancedSearch.tsx"


class P102BrowseSearchResilienceTests(unittest.TestCase):
    def test_advanced_search_ignores_stale_social_metrics_from_an_older_search(self):
        source = read_text(WEB_SEARCH)
        match = re.search(
            r"const metrics = await api\.seriesSocialMetricsBatch\((?P<request>.*?)\);(?P<after>.*?)\n\s*}\s*catch\s*\{(?P<catch>.*?)\n\s*}\s*else",
            source,
            re.S,
        )
        self.assertIsNotNone(match, "expected the Advanced Search Social enrichment block")
        self.assertIn(
            "if (requestId !== searchRequestRef.current) return;",
            match.group("after"),
            "a delayed Social response from an older search must not overwrite newer metrics",
        )
        self.assertIn(
            "if (requestId !== searchRequestRef.current) return;",
            match.group("catch"),
            "a delayed Social failure from an older search must not clear newer metrics",
        )


if __name__ == "__main__":
    unittest.main()
