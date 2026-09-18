from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "frontend" / "src" / "pages" / "Library.tsx"
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "LibraryScreen.kt"
WEB_APP = ROOT / "frontend" / "src" / "App.tsx"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101LibraryUiTests(unittest.TestCase):
    def test_web_library_distinguishes_unknown_initial_failure_from_empty_library(self):
        source = read(WEB)
        require_all(self, source, (
            "const [libraryKnown, setLibraryKnown] = useState(false);",
            "setLibraryKnown(true);", "setLibraryKnown(false);",
            "hasLoadedRef.current ? 'Library refresh failed. Showing the last successful snapshot.' : 'Library is unavailable. Retry to load your personal library.'",
            "libraryKnown ? item.count : '—'", "libraryKnown ? summary.updates : '—'",
            "libraryKnown ? summary.caught_up : '—'", "libraryKnown ? summary.not_started : '—'",
            "items.length ? (", ") : libraryKnown ? (", "Library data is unavailable",
        ))

    def test_web_library_is_authenticated_and_uses_only_smart_library_owner(self):
        source = read(WEB)
        app = read(WEB_APP)
        self.assertIn('path="/library" element={<Protected><Library /></Protected>}', app)
        self.assertIn("api.getSmartLibrary({", source)
        self.assertNotIn("api.getHistory(", source)
        self.assertNotIn("/api/progress/history", source)
        for scope in ("'all'", "'bookmarks'", "'following'", "'history'"):
            self.assertIn(scope, source)
        for state in ("'updates'", "'caught_up'", "'not_started'"):
            self.assertIn(state, source)
        for sort in ('value="activity"', 'value="updated"', 'value="unread"', 'value="title"'):
            self.assertIn(sort, source)
        self.assertIn("Recently opened", source)
        self.assertIn("recent.total", source)

    def test_android_library_requires_account_and_uses_smart_library_owner(self):
        source = read(ANDROID)
        self.assertIn("if (currentUser == null)", source)
        self.assertIn("Sign in to sync bookmarks, follows, updates and reading history", source)
        self.assertIn("repository.smartLibrary(", source)
        self.assertIn("repository.cachedSmartLibrary(", source)
        self.assertNotIn("repository.history(", source)
        self.assertIn('LibraryFilter("bookmarks", "Bookmarks"', source)
        self.assertIn('LibraryFilter("following", "Subscriptions"', source)
        self.assertIn('LibraryFilter("history", "History"', source)
        self.assertIn('"updates" to "Updates"', source)
        self.assertIn('"caught_up" to "Caught up"', source)
        self.assertIn('"not_started" to "Not started"', source)
        self.assertIn("Recently opened", source)

    def test_android_library_never_renders_unknown_counts_as_zero(self):
        source = read(ANDROID)
        self.assertIn('Text(if (known) item.count.toString() else "—"', source)
        self.assertIn('Text(if (known) "$total series in this view" else "Reading state unavailable"', source)
        self.assertIn("else if (rows.isEmpty() && known)", source)


if __name__ == "__main__":
    unittest.main()
