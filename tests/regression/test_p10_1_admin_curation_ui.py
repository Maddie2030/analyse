from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / "frontend" / "src" / "pages" / "AdminCuration.tsx"
WEB_CATALOG = ROOT / "frontend" / "src" / "pages" / "Catalog.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "client.ts"
ANDROID_CATALOG = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "screens" / "CatalogScreen.kt"
ANDROID_MODELS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "core" / "model" / "Models.kt"
ANDROID_PARSERS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "core" / "network" / "JsonParsers.kt"
ANDROID_REPO = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "core" / "repository" / "MReaderRepository.kt"
ANDROID_APP = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "ui" / "MReaderApp.kt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101AdminCurationUiTests(unittest.TestCase):
    def test_admin_editor_picks_retain_crud_order_activation_and_schedule(self):
        source = read(ADMIN)
        require_all(self, source, (
            "api.getAdminCuration()", "api.createEditorPick(body)",
            "api.updateEditorPick(pickForm.id, body)", "api.deleteEditorPick(item.id)",
            "position", "is_active", "starts_at", "ends_at",
        ))

    def test_admin_announcements_retain_crud_order_activation_schedule_link_and_dismissible(self):
        source = read(ADMIN)
        require_all(self, source, (
            "api.createAnnouncement(body)", "api.updateAnnouncement(announcementForm.id, body)",
            "api.deleteAnnouncement(item.id)", "link_url", "link_label", "dismissible",
            "position", "is_active", "starts_at", "ends_at",
        ))

    def test_web_public_curation_renders_editor_picks_links_and_dismissible_announcements(self):
        source = read(WEB_CATALOG)
        self.assertIn("api.getCuration()", source)
        self.assertIn("<EditorPicks", source)
        self.assertIn("item.link_url", source)
        self.assertIn("item.dismissible", source)
        self.assertIn("mreader_announcement_dismissed:", source)

    def test_android_public_curation_preserves_link_and_dismissible_semantics(self):
        model = read(ANDROID_MODELS)
        parser = read(ANDROID_PARSERS)
        catalog = read(ANDROID_CATALOG)
        repo = read(ANDROID_REPO)
        app = read(ANDROID_APP)

        self.assertIn("val dismissible: Boolean", model)
        self.assertIn('dismissible = item.optBoolean("dismissible", true)', parser)
        self.assertIn("announcement.linkUrl", catalog)
        self.assertIn("announcement.dismissible", catalog)
        self.assertIn("repository.dismissAnnouncement(announcement.id)", catalog)
        self.assertIn("repository.isAnnouncementDismissed", catalog)
        self.assertIn("onAnnouncementLink", catalog)
        self.assertIn("onAnnouncementLink =", app)


if __name__ == "__main__":
    unittest.main()
