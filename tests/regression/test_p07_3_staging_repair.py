from __future__ import annotations

import runpy
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


function_source = runpy.run_path(
    str(ROOT / "tests/regression/test_new_series_publication_cutover.py")
)["_function_source"]


def source_of(path: str, name: str) -> str:
    return function_source(ROOT / path, name)


class P073StagingRepairContract(unittest.TestCase):
    def test_migration_adds_revision_and_stage_generation_fences(self) -> None:
        migration = text("db/migrations/057_scraper_staging_repair_fences.sql")
        self.assertIn("ALTER TABLE scraper_drafts", migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1", migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS stage_generation BIGINT NOT NULL DEFAULT 1", migration)
        self.assertIn("ALTER TABLE scraper_series_draft_chapters", migration)
        self.assertGreaterEqual(migration.count("stage_generation"), 4)

    def test_existing_draft_retry_repairs_only_url_backed_missing_bytes_under_fence(self) -> None:
        source = text("services/scraper_service/app/drafts.py")
        retry = source_of("services/scraper_service/app/drafts.py", "retry_failed_draft_pages")
        self.assertIn("_classify_existing_draft_retry", source)
        self.assertIn("StagedObjectMissing", source)
        self.assertIn("re-upload", source.lower())
        self.assertIn("revision", retry)
        self.assertIn("stage_generation", retry)
        self.assertIn("_commit_retry_fence_loss_cleanup", source)
        self.assertIn("retry fence", source.lower())

    def test_series_stage_repairs_missing_url_pages_and_rejects_missing_manual_pages(self) -> None:
        source = text("services/scraper_service/app/series_drafts.py")
        queued = source_of("services/scraper_service/app/series_drafts.py", "queue_stage_chapters")
        worker = source_of("services/scraper_service/app/series_drafts.py", "stage_one_chapter")
        recovery = source_of("services/scraper_service/app/series_drafts.py", "recover_incomplete_stage_jobs")
        self.assertIn("_stage_repair_decision", source)
        self.assertIn("re-upload", source.lower())
        self.assertIn("stage_generation", queued)
        self.assertIn("revision", worker)
        self.assertIn("stage_generation", worker)
        wrapper_start = worker.index("async def report_stage_progress")
        wrapper_end = worker.index("\n\n    try:", wrapper_start)
        progress_wrapper = worker[wrapper_start:wrapper_end]
        self.assertIn("await _update_stage_progress(", progress_wrapper)
        self.assertNotIn("await report_stage_progress(", progress_wrapper)
        self.assertIn("stage_generation", recovery)

    def test_preview_and_publish_remain_strict_staging_readers(self) -> None:
        drafts_publish = source_of("services/scraper_service/app/drafts.py", "_raw_staged_archive")
        series_preview = source_of("services/scraper_service/app/series_drafts.py", "preview_page")
        series_publish = source_of("services/scraper_service/app/series_drafts.py", "_publish_one_chapter_commit")
        combined = "\n".join((drafts_publish, series_preview, series_publish))
        self.assertNotIn("_download_source_page", combined)
        self.assertNotIn("_download_image", combined)
        self.assertNotIn("_fetch_html", combined)
        self.assertIn("_get_staged", drafts_publish)
        self.assertIn("_get(", series_preview)

    def test_thumbnail_compatibility_route_delegates_to_durable_media_job(self) -> None:
        upload = source_of("services/image_service/app/routers/upload.py", "upload_series_thumbnail")
        client = source_of("frontend/src/api/client.ts", "uploadSeriesThumbnail") if False else text("frontend/src/api/client.ts")
        self.assertIn("_submit_thumbnail_job", upload)
        self.assertNotIn("convert_image_to_webp", upload)
        self.assertNotIn("upload_via_filer", upload)
        self.assertIn("status_code=status.HTTP_202_ACCEPTED", text("services/image_service/app/routers/upload.py"))
        self.assertIn("job_id", client)
        self.assertIn("/api/upload/jobs/", client)
        self.assertIn("completed", client)

    def test_retry_fence_loss_cleanup_is_committed_before_conflict_is_raised(self) -> None:
        source = text("services/scraper_service/app/drafts.py")
        cleanup = source_of("services/scraper_service/app/drafts.py", "_commit_retry_fence_loss_cleanup")
        commit = source_of("services/scraper_service/app/drafts.py", "_commit_existing_draft_retry")
        self.assertIn("enqueue_local_staging_cleanup", cleanup)
        self.assertNotIn("raise HTTPException", cleanup)
        cleanup_call = commit.find("_commit_retry_fence_loss_cleanup")
        conflict = commit.find("raise HTTPException", cleanup_call)
        self.assertGreaterEqual(cleanup_call, 0)
        self.assertGreater(conflict, cleanup_call)


if __name__ == "__main__":
    unittest.main()
