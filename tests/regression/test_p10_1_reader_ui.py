from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "frontend" / "src" / "pages" / "Reader.tsx"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "ReaderScreen.kt"
WEBVIEW = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "WebReaderScreen.kt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101ReaderUiTests(unittest.TestCase):
    def test_web_reader_clears_prior_manifest_before_loading_new_route(self):
        source = read(WEB)
        markers = ("setData(null);", "const d = await api.getReader(seriesSlug, chapterSlug);")
        require_all(self, source, markers)
        self.assertLess(source.index(markers[0]), source.index(markers[1]))

    def test_web_reader_retains_navigation_comments_and_return_actions(self):
        source = read(WEB)
        self.assertGreaterEqual(source.count("Chapter list"), 2, "Reader must keep chapter-list access at both navigation rails")
        self.assertIn("<CommentSection seriesId={data.series_id} chapterId={data.chapter_id} />", source)
        self.assertIn('to="/library"', source)
        self.assertIn("Back to Library", source)
        self.assertIn("Series page", source)

    def test_web_progress_read_is_account_scoped_and_protected_pages_refresh_grants(self):
        source = read(WEB)
        self.assertIn("repository.account() === null ? undefined", source)
        self.assertIn("api.getProgress(repository.account()!, seriesSlug, chapterSlug)", source)
        self.assertIn("api.refreshChapterToken(seriesSlug, chapterSlug)", source)
        self.assertIn("refreshChapterToken={refreshChapterToken}", source)

    def test_android_reader_retains_top_bottom_navigation_and_comments(self):
        source = read(ANDROID)
        self.assertGreaterEqual(source.count("ChapterNavigation(m, onBack, onChapter"), 2)
        self.assertIn("CommentSection(", source)
        self.assertIn("seriesId = m.seriesId", source)

    def test_android_protected_cache_is_account_gated_and_token_refreshable(self):
        source = read(ANDROID)
        self.assertGreaterEqual(source.count("persistentCacheEnabled = currentUser != null"), 2)
        require_all(self, source, (
            "repository.refreshChapterToken(", "repository.api.mobileReaderPage(",
            "val persistThisPage = persistentCacheEnabled && cacheableProtected",
        ))

    def test_android_web_reader_stays_on_configured_origin_and_returns_series_navigation_to_native(self):
        source = read(WEBVIEW)
        self.assertIn('"$baseUrl/read/${Uri.encode(seriesSlug)}/${Uri.encode(chapterSlug)}"', source)
        self.assertIn('uri.path.orEmpty().startsWith("/series/")', source)


if __name__ == "__main__":
    unittest.main()
