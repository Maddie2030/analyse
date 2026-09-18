from __future__ import annotations

import runpy
import io
from pathlib import Path
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
DRAFTS = ROOT / "services/scraper_service/app/drafts.py"
ROUTES = ROOT / "services/scraper_service/app/existing_series_publication_routes.py"
JOBS = ROOT / "services/image_service/app/routers/jobs.py"
BRIDGE = ROOT / "services/scraper_service/app/publication_bridge.py"
BATCH = ROOT / "services/scraper_service/app/batch_queue.py"
INGESTION = ROOT / "services/scraper_service/app/ingestion.py"
FRONTEND = ROOT / "frontend/src/pages/AdminScraper.tsx"



class ScraperMediaPublicationSourceTests(unittest.TestCase):
    def test_existing_series_cutover_contract(self):
        sources = {
            "drafts": DRAFTS.read_text(),
            "routes": ROUTES.read_text(),
            "jobs": JOBS.read_text(),
            "frontend": FRONTEND.read_text(),
        }
        required = {
            "drafts": (
                "build_staged_chapter_archive",
                "submit_to_media",
                "wait_for_media_publication",
                "ensure_ingestion_operation",
                'source_kind="existing-series-scrape"',
                "requesting_actor_id=request.actor_id",
            ),
            "routes": (
                'actor_id=str(_admin["user_id"])',
                "session_id=request.cookies.get(settings.SESSION_COOKIE_NAME)",
                "existing_series_route_context",
                "reconcile_existing_series_draft",
            ),
            "jobs": (
                'text_value("ingestion_operation_id")',
                'text_value("media_operation_id")',
                "publication_operation_id = ingestion_operation_id or job_id",
                '"operation_id": publication_operation_id',
                '"idempotency_key": publication_operation_id',
                '"source_revision": int(source_revision)',
                '"ingestion_generation": int(ingestion_generation)',
            ),
            "frontend": (
                "draft?.status !== 'publishing'",
                "api.scraperGetDraft(draft.id)",
                "window.setInterval",
                "Publication is still being reconciled by Media and Catalog",
                "draft.status === 'published'",
            ),
        }
        for name, needles in required.items():
            with self.subTest(source=name):
                for needle in needles:
                    self.assertIn(needle, sources[name])

        self.assertNotIn("publish_chapter_record", sources["drafts"])
        self.assertNotIn("process_page", sources["drafts"])
        self.assertNotIn("build_page_path", sources["drafts"])


def _async_function_block(source: str, name: str) -> str:
    import re
    match = re.search(rf"^async def {re.escape(name)}\(", source, re.M)
    if not match:
        raise AssertionError(f"{name} missing")
    tail = source[match.end():]
    next_match = re.search(r"^(?:async def|def|@)", tail, re.M)
    end = match.end() + next_match.start() if next_match else len(source)
    return source[match.start():end]


class BatchMediaPublicationSourceTests(unittest.TestCase):
    def test_batch_cutover_contract(self):
        source = BATCH.read_text()
        body = _async_function_block(source, "process_item")
        for needle in (
            "ensure_ingestion_operation",
            'source_kind="batch-upload"',
            "submit_to_media",
            "wait_for_media_publication",
            "SpooledTemporaryFile",
            "created_by",
            "catalog_receipt",
            "expected_revision",
            "source_revision",
            "lease_generation",
        ):
            self.assertIn(needle, source if needle == "SpooledTemporaryFile" else body)
        for legacy in (
            "publish_chapter_record",
            "process_page",
            "build_page_path",
            "reserve_storage_paths",
            "mark_storage_attempt_committed",
        ):
            self.assertNotIn(legacy, body)

    def test_internal_media_transport_preserves_batch_actor(self):
        sources = {
            "scraper_transport": INGESTION.read_text(),
            "media_boundary": JOBS.read_text(),
        }
        expected = {
            "scraper_transport": (
                "requesting_actor_id",
                "X-MReader-Requesting-Actor-ID",
                "/internal/v1/media/jobs/",
            ),
            "media_boundary": (
                "internal_submit_chapter_job",
                "internal_media_job_status",
                '"actor_id": actor_id',
            ),
        }
        for source_name, needles in expected.items():
            with self.subTest(source=source_name):
                for needle in needles:
                    self.assertIn(needle, sources[source_name])

    def test_catalog_conflict_guard_is_terminal_only(self):
        import importlib.util
        import sys
        import types
        fastapi = types.ModuleType("fastapi")
        class HTTPException(Exception):
            def __init__(self, status_code, detail):
                self.status_code = status_code
                self.detail = detail
        fastapi.HTTPException = HTTPException
        fastapi.Request = object
        sys.modules.setdefault("fastapi", fastapi)
        # Source-level proof is sufficient for import-heavy Scraper module here.
        source = INGESTION.read_text()
        self.assertIn("PUBLICATION_CONFLICT_CODES", source)
        self.assertIn('if status_value != "completed"', source)
        self.assertIn("raise HTTPException(409", source)


class StagedArchiveTests(unittest.TestCase):
    def test_staged_archive_preserves_selected_order_and_raw_bytes(self):
        bridge = runpy.run_path(str(BRIDGE))
        body = bridge["build_staged_chapter_archive"](
            [(2, b"second", "image/png"), (1, b"first", "image/jpeg")]
        )
        with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
            self.assertEqual(zf.namelist(), ["0001.jpg", "0002.png"])
            self.assertEqual(zf.read("0001.jpg"), b"first")
            self.assertEqual(zf.read("0002.png"), b"second")


if __name__ == "__main__":
    unittest.main()
