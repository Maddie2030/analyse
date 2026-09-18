from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "src" / "App.tsx"
DASH = ROOT / "frontend" / "src" / "pages" / "AdminDashboard.tsx"
UPLOAD = ROOT / "frontend" / "src" / "pages" / "AdminUpload.tsx"
SERIES = ROOT / "frontend" / "src" / "pages" / "SeriesDetail.tsx"
STORAGE = ROOT / "frontend" / "src" / "pages" / "AdminStorage.tsx"
MEDIA_JOBS = ROOT / "services" / "image_service" / "app" / "routers" / "jobs.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101AdminContentUiTests(unittest.TestCase):
    def test_manual_upload_surfaces_accept_pdf_supported_by_media_backend(self):
        upload = read(UPLOAD)
        series = read(SERIES)
        media = read(MEDIA_JOBS)
        self.assertIn('file_ext not in {".zip", ".cbz", ".pdf"}', media)
        self.assertIn('ZIP/CBZ/PDF', upload)
        self.assertIn('.pdf', upload)
        self.assertIn('application/pdf', upload)
        self.assertIn('ZIP/CBZ/PDF', series)
        self.assertIn('.pdf', series)
        self.assertIn('application/pdf', series)

    def test_admin_content_routes_are_admin_only_and_plane_gated(self):
        app = read(APP)
        self.assertIn("if (!user || user.role !== 'admin')", app)
        self.assertIn("runtimeConfig.adminPlane", app)
        for route in ('/admin', '/admin/upload', '/admin/storage'):
            self.assertIn(f'path="{route}"', app)
            self.assertIn('<AdminOnly>', app)

    def test_series_admin_retains_create_status_tags_cover_and_delete_lifecycle(self):
        source = read(DASH)
        self.assertIn("api.createSeries({", source)
        self.assertIn("api.updateSeries(s.id, { status })", source)
        self.assertIn("api.updateSeries(s.id, { tag_names: tagNames })", source)
        self.assertIn("api.uploadSeriesThumbnail(s.slug, file)", source)
        self.assertIn("api.deleteSeries(id)", source)
        self.assertIn("Storage cleanup is", source)
        self.assertIn('to="/admin/storage"', source)

    def test_manual_chapter_upload_retains_boundary_pages_and_durable_media_job(self):
        upload = read(UPLOAD)
        series = read(SERIES)
        for source in (upload, series):
            self.assertIn("api.uploadChapter(", source)
            self.assertIn("firstImage", source) if source is upload else self.assertIn("uploadFirstImage", source)
            self.assertIn("lastImage", source) if source is upload else self.assertIn("uploadLastImage", source)
        self.assertIn("First page image (optional)", upload)
        self.assertIn("Last page image (optional)", upload)

    def test_storage_retains_exports_and_retryable_lifecycle_cleanup(self):
        source = read(STORAGE)
        require_all(self, source, (
            "api.downloadChapterExport(chapter.id, mode)", "'stored'", "'decoded'",
            "api.listLifecycleCleanupJobs", "api.retryLifecycleCleanupJob",
            "Durable lifecycle cleanup", "Staging volume needs attention",
        ))

    def test_series_admin_retains_chapter_delete_and_export(self):
        source = read(SERIES)
        require_all(self, source, (
            "api.downloadChapterExport(chapter.id, 'stored')",
            "api.deleteChapter(series.id, chapter.id)",
            "Storage cleanup is",
        ))


if __name__ == "__main__":
    unittest.main()
