import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_DRAFTS = ROOT / "services/scraper_service/app/series_drafts.py"
LEGACY_MODULES = (
    ROOT / "services/scraper_service/app/publication.py",
    ROOT / "services/scraper_service/app/draft_image_processor.py",
    ROOT / "services/scraper_service/app/tilepack_codec.py",
    ROOT / "services/scraper_service/app/events.py",
)


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function {name} not found in {path}")


SERIES_SOURCE = SERIES_DRAFTS.read_text(encoding="utf-8")
COMMIT_SOURCE = _function_source(SERIES_DRAFTS, "_publish_one_chapter_commit")


class NewSeriesPublicationCutoverTests(unittest.TestCase):
    def test_commit_delegates_transform_and_catalog_publication_to_media(self) -> None:
        for legacy in (
            "publish_chapter_record",
            "process_page",
            "build_page_path",
            "reserve_storage_paths",
            "await _put(",
        ):
            self.assertNotIn(legacy, COMMIT_SOURCE)
        for required in (
            "ensure_ingestion_operation",
            "build_staged_chapter_archive",
            "media_job_status",
            "MediaSubmission",
            "submit_to_media",
            "wait_for_media_publication",
            "catalog_receipt",
            "requesting_actor_id",
        ):
            self.assertIn(required, COMMIT_SOURCE)

    def test_operation_and_media_identity_are_deterministic_per_chapter(self) -> None:
        self.assertIn('source_kind="new-series-scrape"', COMMIT_SOURCE)
        self.assertIn("_new_series_media_operation_id", COMMIT_SOURCE)
        helper = _function_source(SERIES_DRAFTS, "_new_series_media_operation_id")
        for required in ("chapter_id", "source_revision", "lease_generation", "uuid.uuid5"):
            self.assertIn(required, helper)

    def test_callers_retain_draft_creator_as_publication_actor(self) -> None:
        call_count = SERIES_SOURCE.count('requesting_actor_id=str(draft["created_by"])')
        self.assertGreaterEqual(call_count, 2)

    def test_legacy_scraper_chapter_publication_stack_is_removed(self) -> None:
        for path in LEGACY_MODULES:
            self.assertFalse(path.exists(), f"legacy module still present: {path.relative_to(ROOT)}")
        for legacy_import in (
            "from app.publication import",
            "from app.draft_image_processor import",
            "from app.tilepack_codec import",
            "from app.events import",
        ):
            self.assertNotIn(legacy_import, SERIES_SOURCE)


if __name__ == "__main__":
    unittest.main()
