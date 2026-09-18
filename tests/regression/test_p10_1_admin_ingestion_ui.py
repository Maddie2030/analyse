from pathlib import Path
import unittest

from p10_1_ui_support import forbid_all, require_all

ROOT = Path(__file__).resolve().parents[2]
EXISTING = ROOT / "frontend" / "src" / "pages" / "AdminScraper.tsx"
NEW = ROOT / "frontend" / "src" / "pages" / "AdminScraperNewSeries.tsx"
OPS = ROOT / "frontend" / "src" / "pages" / "AdminScraperOperations.tsx"
CLIENT = ROOT / "frontend" / "src" / "api" / "client.ts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class P101AdminIngestionUiTests(unittest.TestCase):
    def test_existing_series_editor_exposes_real_page_replacement_not_add_only(self):
        source = read(EXISTING)
        client = read(CLIENT)
        self.assertIn("scraperReplaceDraftPageUrl", client)
        self.assertIn("api.scraperReplaceDraftPageUrl(draft.id, pageId, replacementUrl)", source)
        self.assertIn("Replace from URL", source)

    def test_existing_series_editor_retains_discover_repair_edit_reorder_add_remove_publish_and_batch_conflicts(self):
        source = read(EXISTING)
        require_all(self, source, (
            "api.scraperCreateChapterDraft(", "api.scraperRetryFailedDraftPages(",
            "api.scraperUpdateDraftChapter(", "api.scraperRemoveDraftPage(",
            "api.scraperReorderDraftPages(", "api.scraperAddDraftPageUrl(",
            "api.scraperAddDraftPageFile(", "api.scraperPublishDraft(",
            "api.scraperCreateBatch(", "api.scraperResolveBatchItem(", "api.scraperRetryBatchItem(",
            "Failed / conflict queue", "Retry failed images",
        ))

    def test_new_series_editor_retains_selection_stage_cover_page_edit_single_bulk_publish_and_cancel(self):
        source = read(NEW)
        for call in (
            "api.scraperUpdateSeriesDraftChapter(",
            "api.scraperStageSeriesChapters(",
            "api.scraperReplaceSeriesCoverUrl(",
            "api.scraperUploadSeriesCover(",
            "api.scraperRemoveSeriesCover(",
            "api.scraperRemoveSeriesDraftPage(",
            "api.scraperReorderSeriesDraftPages(",
            "api.scraperAddSeriesDraftPageUrl(",
            "api.scraperAddSeriesDraftPageFile(",
            "api.scraperPublishSeriesDraftChapter(",
            "api.scraperPublishSeriesDraft(",
            "api.scraperCancelSeriesPublish(",
        ):
            self.assertIn(call, source)
        self.assertIn("selected /", source)
        self.assertIn("Staging selected chapters", source)

    def test_operations_dashboard_retains_durable_progress_retry_cancel_and_acknowledge(self):
        source = read(OPS)
        require_all(self, source, (
            "api.scraperListOperations", "api.scraperAcknowledgeOperation",
            "api.scraperRetryDiscovery", "api.scraperCancelOperation",
            "Backend-owned status", "Refreshing the browser does not lose jobs",
            "Cancel task", "Acknowledge",
        ))


if __name__ == "__main__":
    unittest.main()
