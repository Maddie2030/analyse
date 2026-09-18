from pathlib import Path
import re
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
WEB_CATALOG = ROOT / "frontend" / "src" / "pages" / "Catalog.tsx"
WEB_SEARCH = ROOT / "frontend" / "src" / "pages" / "AdvancedSearch.tsx"
ANDROID_CATALOG = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "CatalogScreen.kt"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101BrowseSearchUiTests(unittest.TestCase):
    def test_web_catalog_keeps_previous_navigation_on_empty_later_page(self):
        source = text(WEB_CATALOG)
        self.assertRegex(
            source,
            r"!loading\s*&&\s*\(series\.length\s*>\s*0\s*\|\|\s*offset\s*>\s*0\)\s*&&",
            "Catalog must keep pagination visible when a speculative next page is empty so Previous remains available",
        )

    def test_web_advanced_search_keeps_pagination_on_empty_later_page(self):
        source = text(WEB_SEARCH)
        self.assertRegex(
            source,
            r"hasSearched\s*&&\s*!loading\s*&&\s*\(series\.length\s*>\s*0\s*\|\|\s*offset\s*>\s*0\)",
            "Advanced Search must keep pagination visible on an empty later page so the user is not stranded",
        )

    def test_android_surprise_me_is_disabled_when_the_actual_candidate_pool_is_empty(self):
        source = text(ANDROID_CATALOG)
        require_all(self, source, ("enabled = pool.isNotEmpty()",))
        forbid_all(self, source, ("enabled = rows.isNotEmpty() || discovery != null",))


    def test_web_browse_retains_public_discovery_and_account_scoped_continue_reading(self):
        source = text(WEB_CATALOG)
        require_all(self, source, (
            "api.getDiscovery()", "api.getTrending(", "api.getCuration()", "api.listSeries(",
            "if (!user) {", "setHistory([]);", "scope: 'history'", "<ContinueReading items={history} />",
        ))
        forbid_all(self, source, ("/api/admin", "/internal/"))

    def test_web_advanced_search_persists_applied_filters_in_the_url(self):
        source = text(WEB_SEARCH)
        require_all(self, source, (
            "useSearchParams()", "setSearchParams(params, { replace: true })",
            "params.search", "params.status", "params.min_rating", "params.sort", "params.genre", "params.tag",
            "setSearchParams({}, { replace: true })",
        ))

    def test_android_browse_keeps_public_discovery_separate_from_account_history(self):
        source = text(ANDROID_CATALOG)
        require_all(self, source, (
            "repository.discovery()", "repository.trending(", "repository.curation()", "repository.listSeries(",
            "if (currentUser == null) emptyList()",
            "repository.history(limit = 8, scope = currentUser?.id)",
            "historyOwner == currentUser?.id",
        ))


if __name__ == "__main__":
    unittest.main()
