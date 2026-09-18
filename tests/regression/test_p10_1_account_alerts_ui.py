from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WEB_PROFILE = ROOT / "frontend" / "src" / "pages" / "Profile.tsx"
WEB_NOTIFICATIONS = ROOT / "frontend" / "src" / "pages" / "Notifications.tsx"
WEB_AUTH = ROOT / "frontend" / "src" / "hooks" / "useAuth.tsx"
ANDROID_SETTINGS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "SettingsScreen.kt"
ANDROID_NOTIFICATIONS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "NotificationsScreen.kt"
ANDROID_VM = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "AppViewModel.kt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101AccountAlertsUiTests(unittest.TestCase):
    def test_android_notifications_are_scoped_to_account_and_filter_and_do_not_false_empty_on_failure(self):
        source = read(ANDROID_NOTIFICATIONS)
        self.assertIn("var rows by remember(currentUser?.id, unreadOnly)", source)
        self.assertIn("var known by remember(currentUser?.id, unreadOnly)", source)
        self.assertIn("known = true", source)
        self.assertIn("else if (rows.isEmpty() && known)", source)
        self.assertIn("Notifications are unavailable", source)
        self.assertIn("if (currentUser == null) { rows = emptyList(); known = false;", source)

    def test_android_profile_marks_admin_without_exposing_mutable_role_field(self):
        source = read(ANDROID_SETTINGS)
        self.assertIn('if (signedInUser.role == "admin")', source)
        self.assertIn('contentDescription = "Administrator account"', source)
        self.assertNotIn('LockedAccountField("Role"', source)
        self.assertIn('LockedAccountField("Username", signedInUser.username)', source)
        self.assertIn('LockedAccountField("Email", signedInUser.email)', source)

    def test_web_profile_identity_is_locked_and_admin_marked(self):
        source = read(WEB_PROFILE)
        self.assertIn("user?.role === 'admin'", source)
        self.assertIn('title="Administrator"', source)
        self.assertGreaterEqual(source.count('readOnly aria-readonly="true"'), 2)
        self.assertIn("await api.updateProfile({ avatar_key: form.avatar_key });", source)

    def test_web_notifications_reconcile_and_roll_back_failed_mutations(self):
        source = read(WEB_NOTIFICATIONS)
        self.assertIn("subscribeNotifications", source)
        self.assertIn("subscribeRealtimeStatus", source)
        self.assertIn("() => api.markRead(id)", source)
        self.assertIn("setNotifications(before);", source)
        self.assertIn("() => api.markAllRead()", source)
        self.assertIn("Notifications are temporarily unavailable.", source)

    def test_auth_logout_is_explicit_privacy_boundary_and_android_has_signout(self):
        web = read(WEB_AUTH)
        android = read(ANDROID_SETTINGS)
        vm = read(ANDROID_VM)
        self.assertIn("if (hasPrivatePendingReading() && !window.confirm", web)
        self.assertIn("await api.logout();", web)
        self.assertIn("await clearPrivateReading();", web)
        self.assertIn("await clearProtectedAssetCache();", web)
        self.assertIn('title = { Text("Sign out?") }', android)
        self.assertIn("appViewModel.logout()", android)
        self.assertIn("repository.logout()", vm)
        self.assertIn("_user.value = null", vm)


if __name__ == "__main__":
    unittest.main()
