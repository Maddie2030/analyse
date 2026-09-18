from __future__ import annotations

import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def function_source(path: str, name: str, language: str = "python") -> str:
    source = text(path)
    if language == "go":
        match = re.search(rf"func\s+(?:\([^)]*\)\s+)?{re.escape(name)}\s*\(", source)
    else:
        match = re.search(rf"^(?:async\s+)?def\s+{re.escape(name)}\s*\(", source, re.M)
    if not match:
        raise AssertionError(f"function {name} not found in {path}")
    brace = source.find("{", match.end()) if language == "go" else -1
    if language == "go":
        depth = 0
        for i in range(brace, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    return source[match.start(): i + 1]
        raise AssertionError(f"unterminated Go function {name}")
    next_match = re.search(r"^(?:async\s+)?def\s+\w+\s*\(", source[match.end():], re.M)
    end = match.end() + next_match.start() if next_match else len(source)
    return source[match.start():end]


def assert_contains_all(case: unittest.TestCase, source: str, *needles: str) -> None:
    for needle in needles:
        case.assertIn(needle, source)


def assert_function_contains(
    case: unittest.TestCase,
    path: str,
    name: str,
    *needles: str,
    language: str = "python",
) -> None:
    assert_contains_all(case, function_source(path, name, language), *needles)


class P075StatusUIConvergenceContract(unittest.TestCase):
    def test_new_series_discovery_creates_parent_ingestion_header_and_children_link_to_it(self) -> None:
        path = "services/scraper_service/app/series_drafts.py"
        assert_function_contains(self, path, "_sync_series_ingestion_operation_tx", "INSERT INTO ingestion_operations", '"new-series-scrape"')
        assert_function_contains(self, path, "queue_series_discovery", "_sync_series_ingestion_operation_tx(conn, draft_id)")
        assert_function_contains(
            self,
            "services/scraper_service/app/publication_bridge.py",
            "ensure_ingestion_operation",
            "parent_operation_id: str | None = None",
            "parent_operation_id",
        )
        assert_function_contains(self, path, "_publish_one_chapter_commit", "parent_operation_id=draft_id")

    def test_parent_operation_header_is_synced_across_coordinator_transitions(self) -> None:
        path = "services/scraper_service/app/series_drafts.py"
        names = (
            "run_series_discovery", "queue_stage_chapters", "queue_publish",
            "_refresh_parent_after_single_publish", "publish_one_series",
            "recover_incomplete_discovery_jobs", "retry_series_discovery",
            "acknowledge_scraper_operation", "unacknowledge_scraper_operation",
        )
        for name in names:
            with self.subTest(function=name):
                assert_function_contains(self, path, name, "_sync_series_ingestion_operation_tx")
        assert_function_contains(self, path, "cancel_scraper_operation", "cancel_ingestion_operation_tx(conn, draft_id)", "_sync_series_ingestion_operation_tx")
        assert_function_contains(self, path, "_finalize_cancelled_operation", "_sync_series_ingestion_operation_tx")

    def test_publish_retry_and_worker_recovery_keep_parent_operation_in_sync(self) -> None:
        path = "services/scraper_service/app/series_drafts.py"
        for name in ("_defer_series_publish_retry", "_recover_stale_parent_publish_tx", "_recover_parent_publish_row"):
            with self.subTest(function=name):
                assert_function_contains(self, path, name, "_sync_series_ingestion_operation_tx")

    def test_admin_delete_ui_reports_catalog_removal_separately_from_storage_cleanup(self) -> None:
        assert_contains_all(self, text("frontend/src/pages/AdminDashboard.tsx"), "Catalog removed", "Storage cleanup", "deleteSeries")
        assert_contains_all(self, text("frontend/src/pages/SeriesDetail.tsx"), "Chapter removed from Catalog", "Storage cleanup", "deleteChapter")

    def test_migration_backfills_parent_headers_and_child_links(self) -> None:
        assert_contains_all(
            self,
            text("db/migrations/059_scraper_parent_ingestion_status.sql"),
            "INSERT INTO ingestion_operations", "FROM scraper_series_drafts d",
            "parent_operation_id = c.draft_id", "io.id = c.id", "io.source_kind = 'new-series-scrape'",
        )

    def test_scrape_operations_project_canonical_ingestion_header(self) -> None:
        assert_function_contains(
            self,
            "services/scraper_service/app/series_drafts.py",
            "list_scraper_operations",
            "LEFT JOIN ingestion_operations io ON io.id = d.id",
            "io.status AS operation_status", "io.phase AS operation_phase",
            "io.revision AS operation_revision", "io.lease_generation AS operation_lease_generation",
            "io.cancel_requested_at AS operation_cancel_requested_at", "io.error_code AS operation_error_code",
            '_operation_group(row.get("operation_status")',
        )

    def test_workflow_status_exposes_canonical_operation_header(self) -> None:
        assert_function_contains(
            self,
            "services/scraper_service/app/series_drafts.py",
            "get_series_workflow_status",
            "LEFT JOIN ingestion_operations io ON io.id = d.id", "io.status AS operation_status",
            "io.phase AS operation_phase", "io.lease_generation AS operation_lease_generation",
        )
        assert_contains_all(
            self,
            text("frontend/src/api/client.ts"),
            "operation_status: string | null;", "operation_phase: string | null;",
            "operation_lease_generation: number | null;",
        )

    def test_admin_operations_ui_labels_canonical_status_separately_from_workflow_detail(self) -> None:
        assert_contains_all(self, text("frontend/src/pages/AdminScraperOperations.tsx"), "Canonical operation", "operation.operation_status", "operation.operation_phase")
        assert_contains_all(self, text("frontend/src/pages/AdminScraperNewSeries.tsx"), "Canonical operation", "draft.operation_status")

    def test_catalog_delete_returns_catalog_removed_plus_async_cleanup_receipt(self) -> None:
        store = text("services/catalog_go/internal/store/store.go")
        assert_contains_all(self, store, "func enqueueCleanupTxWithID")
        self.assertRegex(store, r"func \(s \*Store\) DeleteSeries\(ctx context\.Context, seriesID string\) \(string, error\)")
        self.assertRegex(store, r"func \(s \*Store\) DeleteChapter\(ctx context\.Context, seriesID, chapterID string\) \(string, error\)")
        for name in ("deleteSeries", "deleteChapter"):
            assert_function_contains(self, "services/catalog_go/internal/httpapi/api.go", name, "http.StatusAccepted", '"catalog_removed"', '"storage_cleanup"', '"job_id"', language="go")
        assert_contains_all(
            self,
            text("frontend/src/api/client.ts"),
            "export interface CatalogDeletionResult", "request<CatalogDeletionResult>(`/api/catalog/series/${id}`",
            "request<CatalogDeletionResult>(`/api/catalog/series/${seriesId}/chapters/${chapterId}`",
        )

    def test_live_status_routes_are_retained_while_obsolete_publish_status_alias_stays_retired(self) -> None:
        main = text("services/scraper_service/app/main.py")
        assert_contains_all(
            self, main,
            '@app.get("/api/scraper/series-drafts/{draft_id}/workflow-status")',
            '@app.get("/api/scraper/series-drafts/{draft_id}/events")',
        )
        assert_contains_all(self, text("frontend/src/api/client.ts"), "scraperGetSeriesPublishStatus", "scraperGetSeriesOperationEvents")
        self.assertNotIn('@app.get("/api/scraper/series-drafts/{draft_id}/publish-status")', main)


if __name__ == "__main__":
    unittest.main()
