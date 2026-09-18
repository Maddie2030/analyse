from __future__ import annotations

import re
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


def go_source_of(path: str, name: str) -> str:
    source = text(path)
    match = re.search(rf"func\s+(?:\([^)]*\)\s+)?{re.escape(name)}\s*\(", source)
    if not match:
        raise AssertionError(f"Go function {name} not found in {path}")
    start = match.start()
    brace = source.find("{", match.end())
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Go function {name} is unterminated in {path}")



class P074LifecycleCleanupContract(unittest.TestCase):
    def assert_contract(
        self,
        source: str,
        *,
        includes: tuple[str, ...] = (),
        excludes: tuple[str, ...] = (),
    ) -> None:
        for needle in includes:
            with self.subTest(required=needle):
                self.assertIn(needle, source)
        for needle in excludes:
            with self.subTest(forbidden=needle):
                self.assertNotIn(needle, source)

    def test_catalog_persists_production_generations_for_pages_and_cover(self) -> None:
        migration_path = ROOT / "db/migrations/058_lifecycle_generation_ownership.sql"
        self.assertTrue(migration_path.exists(), "P07.4 generation migration is missing")
        migration = migration_path.read_text(encoding="utf-8")
        self.assert_contract(
            migration,
            includes=(
                "ALTER TABLE pages",
                "ADD COLUMN IF NOT EXISTS media_generation BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE series",
                "ADD COLUMN IF NOT EXISTS cover_media_generation BIGINT NOT NULL DEFAULT 0",
            ),
        )

        publication = text("services/catalog_go/internal/store/publication.go")
        self.assert_contract(publication, includes=("media_generation", "command.MediaGeneration"))

        cover_store = go_source_of("services/catalog_go/internal/store/store.go", "SetSeriesCover")
        self.assert_contract(cover_store, includes=("mediaGeneration", "cover_media_generation"))

        cover_transport = text("services/image_service/app/catalog_series.py")
        worker = source_of("services/image_service/app/worker.py", "generate_thumbnail")
        self.assert_contract(cover_transport, includes=('"media_generation": int(media_generation)',))
        self.assert_contract(worker, includes=("media_generation=claimed_generation",))

    def test_catalog_snapshots_exact_generation_bound_object_refs_transactionally(self) -> None:
        publication_cleanup = go_source_of(
            "services/catalog_go/internal/store/publication.go",
            "publicationCleanupPayloadTx",
        )
        delete_series = go_source_of("services/catalog_go/internal/store/store.go", "DeleteSeries")
        delete_chapter = go_source_of("services/catalog_go/internal/store/store.go", "DeleteChapter")
        set_cover = go_source_of("services/catalog_go/internal/store/store.go", "SetSeriesCover")

        for block in (publication_cleanup, delete_series, delete_chapter):
            self.assert_contract(
                block,
                includes=("media_generation", '"object_refs"'),
                excludes=('"storage_prefixes"',),
            )

        self.assert_contract(
            delete_series,
            includes=("cover_media_generation", 'Kind: "cover"'),
        )
        self.assert_contract(
            set_cover,
            includes=("oldCoverGeneration", 'Kind: "cover"', '"object_refs"'),
        )

    def test_lifecycle_rechecks_live_path_and_generation_before_physical_delete(self) -> None:
        worker = text("services/image_service/app/lifecycle_worker.py")
        cleanup = source_of("services/image_service/app/lifecycle_worker.py", "_cleanup_job")
        live_filter = source_of(
            "services/image_service/app/lifecycle_worker.py",
            "_filter_unowned_object_refs",
        )

        self.assert_contract(
            live_filter,
            includes=("media_generation", "cover_media_generation", "generation"),
        )
        self.assert_contract(cleanup, includes=("_filter_unowned_object_refs", "delete_via_filer"))
        self.assert_contract(worker, excludes=("delete_dir_via_filer",))

    def test_legacy_broad_prefix_cleanup_is_quarantined_not_executed(self) -> None:
        worker = text("services/image_service/app/lifecycle_worker.py")
        cleanup = source_of("services/image_service/app/lifecycle_worker.py", "_cleanup_job")
        fail = source_of("services/image_service/app/lifecycle_worker.py", "_fail")

        self.assert_contract(worker, includes=("UnsafeLegacyCleanupPayload",), excludes=("delete_dir_via_filer",))
        self.assert_contract(cleanup, includes=("storage_prefixes", "UnsafeLegacyCleanupPayload"))
        self.assert_contract(fail, includes=("UnsafeLegacyCleanupPayload",))

    def test_media_production_output_cleanup_is_handed_to_lifecycle(self) -> None:
        ingestion = text("services/image_service/app/services/chapter_ingestion.py")
        thumbnail = source_of("services/image_service/app/worker.py", "generate_thumbnail")
        bridge_path = ROOT / "services/image_service/app/lifecycle_cleanup.py"
        self.assertTrue(bridge_path.exists(), "Media-to-Lifecycle output cleanup bridge is missing")
        bridge = bridge_path.read_text(encoding="utf-8")

        self.assert_contract(
            ingestion,
            includes=("enqueue_production_output_cleanup", "media_generation"),
            excludes=("async def _delete_created_paths",),
        )
        self.assert_contract(bridge, includes=("enqueue_cleanup_job", '"object_refs"', "media_generation"))

        # Thumbnail source staging may still be directly deleted; the produced
        # cover object itself must be handed to Lifecycle with its generation.
        self.assert_contract(
            thumbnail,
            includes=("enqueue_production_output_cleanup", "claimed_generation"),
            excludes=("delete_via_filer(image_path)",),
        )


if __name__ == "__main__":
    unittest.main()
