from pathlib import Path
import re
import unittest

from p10_1_ui_support import read_text, require_all

ROOT = Path(__file__).resolve().parents[2]
WEB_NOTIFICATIONS = ROOT / "frontend" / "src" / "pages" / "Notifications.tsx"
WEB_NOTIFICATION_HOOK = ROOT / "frontend" / "src" / "hooks" / "useNotifications.ts"
WEB_DATABASE = ROOT / "frontend" / "src" / "pages" / "AdminDatabase.tsx"
WEB_SCRAPER_OPERATIONS = ROOT / "frontend" / "src" / "pages" / "AdminScraperOperations.tsx"
WEB_SERIES = ROOT / "frontend" / "src" / "pages" / "SeriesDetail.tsx"
ANDROID_VM = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "AppViewModel.kt"
ANDROID_NOTIFICATIONS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "NotificationsScreen.kt"


class P102ResilienceRaceTests(unittest.TestCase):
    def test_web_async_surfaces_reject_stale_identity_or_filter_responses(self):
        cases = (
            (
                "notifications page account",
                WEB_NOTIFICATIONS,
                (
                    "useAuth",
                    "const accountId = user?.id ?? null;",
                    "accountRef.current = user?.id ?? null;",
                    "const requestId = ++loadRequestRef.current;",
                    "return requestId === loadRequestRef.current && accountId === accountRef.current;",
                    "if (!isCurrentNotificationRequest(requestId, accountId, loadRequestRef, accountRef)) return;",
                    "setNotifications([]);",
                ),
                r"const\s+loadRequestRef\s*=\s*useRef\(0\)",
            ),
            (
                "notification badge account",
                WEB_NOTIFICATION_HOOK,
                (
                    "const accountId = user?.id ?? null;",
                    "accountRef.current = user?.id ?? null;",
                    "const generation = ++refreshGeneration.current;",
                    "if (generation !== refreshGeneration.current || accountId !== accountRef.current) return;",
                ),
                r"const\s+refreshGeneration\s*=\s*useRef\(0\)",
            ),
            (
                "database cursor page",
                WEB_DATABASE,
                (
                    "const requestId = ++loadRequestRef.current;",
                    "if (requestId !== loadRequestRef.current) return;",
                    "if (requestId === loadRequestRef.current) setLoading(false);",
                ),
                r"const\s+loadRequestRef\s*=\s*useRef\(0\)",
            ),
            (
                "scraper operation filter",
                WEB_SCRAPER_OPERATIONS,
                (
                    "const requestId = ++loadRequestRef.current;",
                    "if (requestId !== loadRequestRef.current) return;",
                    "if (requestId === loadRequestRef.current && !quiet) setRefreshing(false);",
                ),
                r"const\s+loadRequestRef\s*=\s*useRef\(0\)",
            ),
        )
        for label, path, needles, ref_pattern in cases:
            with self.subTest(label=label):
                source = read_text(path)
                require_all(self, source, needles)
                self.assertRegex(source, ref_pattern)

    def test_series_relationship_mutations_are_single_flight_and_identity_scoped(self):
        source = read_text(WEB_SERIES)
        require_all(self, source, (
            "const [relationshipBusy, setRelationshipBusy] = useState(false);",
            "const relationshipMutationRef = useRef(0);",
            "relationshipIdentityRef.current = `${user?.id ?? 'guest'}:${series?.id ?? ''}`;",
            "disabled={relationshipBusy || bookmarked === null}",
            "disabled={relationshipBusy || subscribed === null}",
        ))
        bookmark = re.search(r"const toggleBookmark = async \(\) => \{(?P<body>.*?)\n  \};", source, re.S)
        subscribe = re.search(r"const toggleSubscribe = async \(\) => \{(?P<body>.*?)\n  \};", source, re.S)
        self.assertIsNotNone(bookmark)
        self.assertIsNotNone(subscribe)
        for body in (bookmark.group("body"), subscribe.group("body")):
            require_all(self, body, (
                "if (relationshipBusy)",
                "setRelationshipBusy(true);",
                "const requestId = ++relationshipMutationRef.current;",
                "identity !== relationshipIdentityRef.current",
            ))

    def test_android_notification_mutations_do_not_cross_account_switches(self):
        view_model = read_text(ANDROID_VM)
        refresh = re.search(r"fun refreshNotificationCount\(\) \{(?P<body>.*?)\n    \}", view_model, re.S)
        self.assertIsNotNone(refresh)
        require_all(self, refresh.group("body"), (
            "val accountId = _user.value?.id",
            "if (_user.value?.id == accountId)",
            "repository.notificationCount()",
        ))

        screen = read_text(ANDROID_NOTIFICATIONS)
        require_all(self, screen, (
            "val currentAccountId by rememberUpdatedState(currentUser?.id)",
            "val accountId = currentUser?.id",
            "if (currentAccountId != accountId) return@launch",
            "appViewModel.setUnreadNotificationCount(0)",
        ))
        self.assertLess(
            screen.index("if (currentAccountId != accountId) return@launch"),
            screen.index("appViewModel.setUnreadNotificationCount(0)"),
        )


if __name__ == "__main__":
    unittest.main()
