from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRAPER_SERIES = ROOT / "services/scraper_service/app/series_drafts.py"
SCRAPER_CATALOG = ROOT / "services/scraper_service/app/catalog_series.py"
SCRAPER_INGESTION = ROOT / "services/scraper_service/app/ingestion.py"
MEDIA_JOBS = ROOT / "services/image_service/app/routers/jobs.py"
MEDIA_UPLOAD = ROOT / "services/image_service/app/routers/upload.py"
MEDIA_WORKER = ROOT / "services/image_service/app/worker.py"
MEDIA_CATALOG = ROOT / "services/image_service/app/catalog_series.py"
MEDIA_TRANSPORT = ROOT / "services/image_service/app/catalog_transport.py"
MEDIA_EVENTS = ROOT / "services/image_service/app/events.py"
CATALOG_API = ROOT / "services/catalog_go/internal/httpapi/api.go"
CATALOG_MODEL = ROOT / "services/catalog_go/internal/model/model.go"
CATALOG_STORE = ROOT / "services/catalog_go/internal/store/store.go"
SHARED_INIT = ROOT / "shared/shared/__init__.py"
SHARED_LIFECYCLE = ROOT / "shared/shared/lifecycle.py"


class SeriesOwnershipCutoverTests(unittest.TestCase):
    def test_scraper_routes_series_taxonomy_and_cover_through_catalog_and_media(self) -> None:
        source = SCRAPER_SERIES.read_text(encoding="utf-8")
        self.assertIn("ensure_catalog_series", source)
        self.assertIn("submit_series_cover_to_media", source)
        self.assertNotIn("import pyvips", source)
        self.assertNotIn("INSERT INTO series ", source)
        self.assertNotIn("INSERT INTO genres ", source)
        self.assertNotIn("INSERT INTO series_genres ", source)
        self.assertNotIn("INSERT INTO tags ", source)
        self.assertNotIn("INSERT INTO series_tags ", source)
        self.assertNotIn("operation_type=\"series_cover\"", source)

        bridge = SCRAPER_CATALOG.read_text(encoding="utf-8")
        self.assertIn("/internal/v1/catalog/series", bridge)
        self.assertIn('"genre_names":', bridge)
        self.assertIn('"tag_names":', bridge)
        self.assertIn("X-MReader-Requesting-Actor-ID", bridge)

        ingestion = SCRAPER_INGESTION.read_text(encoding="utf-8")
        self.assertIn("submit_series_cover_to_media", ingestion)
        self.assertIn("thumbnail/", ingestion)

    def test_catalog_owns_series_taxonomy_creation_and_cover_commit(self) -> None:
        api = CATALOG_API.read_text(encoding="utf-8")
        model = CATALOG_MODEL.read_text(encoding="utf-8")
        store = CATALOG_STORE.read_text(encoding="utf-8")

        self.assertIn('r.Post("/internal/v1/catalog/series"', api)
        self.assertIn('r.Put("/internal/v1/catalog/series/{seriesID}/cover"', api)
        self.assertIn("GenreNames", model)
        self.assertIn('json:"genre_names"', model)
        self.assertIn("getOrCreateTaxonomyIDsTx", store)
        self.assertIn("SetSeriesCover", store)
        self.assertIn("enqueueCleanupTx", store)
        self.assertIn("enqueueSeriesUpdatedTx", store)

    def test_media_cover_paths_transform_only_and_delegate_canonical_mutation(self) -> None:
        upload = MEDIA_UPLOAD.read_text(encoding="utf-8")
        worker = MEDIA_WORKER.read_text(encoding="utf-8")
        events = MEDIA_EVENTS.read_text(encoding="utf-8")
        catalog = MEDIA_CATALOG.read_text(encoding="utf-8")
        transport = MEDIA_TRANSPORT.read_text(encoding="utf-8")

        for source in (upload, worker):
            self.assertNotRegex(source, r"series\.cover_image_path\s*=")
            self.assertNotRegex(source, r"series\.updated_at\s*=")
            self.assertNotIn("enqueue_series_updated", source)
            self.assertIn("set_catalog_series_cover", source)

        self.assertNotIn("async def enqueue_series_updated", events)
        self.assertNotIn("async def enqueue_chapter_published", events)
        self.assertNotIn('"chapter.published"', events)
        self.assertIn("/internal/v1/catalog/series/", catalog)
        self.assertIn("/cover", catalog)
        self.assertIn("X-MReader-Requesting-Actor-ID", transport)

    def test_internal_thumbnail_job_retains_actor_for_catalog_cover_commit(self) -> None:
        jobs = MEDIA_JOBS.read_text(encoding="utf-8")
        worker = MEDIA_WORKER.read_text(encoding="utf-8")

        self.assertIn('@internal_router.post("/thumbnail/{series_slug}"', jobs)
        self.assertIn('"actor_id": actor_id', jobs)
        self.assertIn('metadata.get("actor_id")', worker)
        self.assertIn("set_catalog_series_cover", worker)

    def test_no_scraper_or_media_production_catalog_writers_remain(self) -> None:
        catalog_tables = (
            "series", "genres", "series_genres", "tags", "series_tags",
            "chapters", "pages",
        )
        sql_writer = re.compile(
            r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:"
            + "|".join(re.escape(table) for table in catalog_tables)
            + r")\b",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for service in ("services/scraper_service/app", "services/image_service/app"):
            for path in (ROOT / service).rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                if sql_writer.search(source):
                    offenders.append(str(path.relative_to(ROOT)))
                if re.search(r"\b(?:series|chapter|page)\.(?:cover_image_path|title|status|updated_at)\s*=", source):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], sorted(set(offenders)))

    def test_shared_cleanup_lazy_export_still_has_implementation(self) -> None:
        evidence = {
            "module": SHARED_LIFECYCLE.exists(),
            "lazy_export": '"enqueue_cleanup_job": (".lifecycle", "enqueue_cleanup_job")'
            in SHARED_INIT.read_text(encoding="utf-8"),
            "implementation": "async def enqueue_cleanup_job"
            in SHARED_LIFECYCLE.read_text(encoding="utf-8"),
        }
        self.assertEqual({key: True for key in evidence}, evidence)


if __name__ == "__main__":
    unittest.main()
