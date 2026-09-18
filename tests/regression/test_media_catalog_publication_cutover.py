import importlib.util
import json
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared" / "shared"
MODULE = ROOT / "services" / "image_service" / "app" / "catalog_publication.py"


def _load_contract():
    package = types.ModuleType("shared")
    package.__path__ = [str(SHARED)]
    sys.modules.setdefault("shared", package)
    for name in ("tilepack_codec", "catalog_publication_contract"):
        full = f"shared.{name}"
        if full in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(full, SHARED / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
    return sys.modules["shared.catalog_publication_contract"]


def _load_module():
    _load_contract()
    app_root = ROOT / "services" / "image_service" / "app"
    app_package = types.ModuleType("app")
    app_package.__path__ = [str(app_root)]
    sys.modules.setdefault("app", app_package)
    transport_name = "app.catalog_transport"
    if transport_name not in sys.modules:
        transport_spec = importlib.util.spec_from_file_location(
            transport_name, app_root / "catalog_transport.py"
        )
        transport = importlib.util.module_from_spec(transport_spec)
        sys.modules[transport_name] = transport
        transport_spec.loader.exec_module(transport)
    spec = importlib.util.spec_from_file_location("media_catalog_publication", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MediaCatalogPublicationCutoverTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        fixture = json.loads((ROOT / "contracts/catalog/v1/fixtures/publication.json").read_text())
        self.fixture = fixture

    def test_chapter_number_is_canonical_two_decimal_contract_value(self):
        self.assertEqual(self.mod.canonical_chapter_number(Decimal("1")), "1.00")
        self.assertEqual(self.mod.canonical_chapter_number(Decimal("12.5")), "12.50")
        with self.assertRaises(ValueError):
            self.mod.canonical_chapter_number(Decimal("12.345"))

    def test_manifest_builder_emits_catalog_contract_asset_evidence(self):
        page = self.fixture["manifest"]["pages"][0]
        media_page = {
            "page_number": page["page_number"],
            "image_path": page["image_path"],
            "width": page["width"],
            "height": page["height"],
            "size_bytes": page["size_bytes"],
            "sha256": page["sha256"],
            "encoding_version": page["encoding_version"],
            "encoding_rows": page["encoding_rows"],
            "encoding_columns": page["encoding_columns"],
            "encoding_seed": page["encoding_seed"],
            "responsive": dict(page["responsive"]),
        }
        manifest = self.mod.build_manifest(
            series_id=self.fixture["manifest"]["series_id"],
            series_slug=self.fixture["manifest"]["series_slug"],
            chapter_slug=self.fixture["manifest"]["chapter_slug"],
            pages=[media_page],
        )
        self.assertEqual(manifest, self.fixture["manifest"])

    def test_command_builder_seals_exact_media_generation_and_actor(self):
        f = self.fixture
        command = self.mod.build_publication_command(
            idempotency_key=f["idempotency_key"],
            operation_id=f["operation_id"],
            actor_id=f["actor_id"],
            source_revision=f["source_revision"],
            ingestion_generation=f["ingestion_generation"],
            media_operation_id=f["media_operation_id"],
            media_generation=f["media_generation"],
            chapter_id=f["chapter_id"],
            expected_revision=f["expected_revision"],
            chapter_number=Decimal(f["chapter_number"]),
            title=f["title"],
            manifest=f["manifest"],
        )
        self.assertEqual(command, f)


class MediaPublicationSourceBoundaryTests(unittest.TestCase):
    def test_chapter_ingestion_no_longer_writes_catalog_tables_or_events(self):
        source = (ROOT / "services/image_service/app/services/chapter_ingestion.py").read_text()
        self.assertNotRegex(source, r"\b(?:Chapter|Page)\(")
        self.assertNotIn("enqueue_chapter_published", source)
        self.assertNotIn("enqueue_series_updated", source)
        self.assertIn("record_publication_completion_evidence", source)
        self.assertIn("publish_catalog_command", source)

    def test_manual_acceptance_persists_retained_admin_identity(self):
        source = (ROOT / "services/image_service/app/routers/jobs.py").read_text()
        self.assertIn('actor_id=str(_admin["user_id"])', source)
        self.assertIn('"actor_id": actor_id', source)
        self.assertIn('text_value("ingestion_operation_id")', source)
        self.assertIn('text_value("media_operation_id")', source)
        self.assertIn('"source_revision": int(source_revision)', source)
        self.assertIn('"ingestion_generation": int(ingestion_generation)', source)
        self.assertIn('"idempotency_key": publication_operation_id', source)

    def test_completed_transform_without_catalog_receipt_remains_recoverable(self):
        source = (ROOT / "services/image_service/app/media_operations.py").read_text()
        self.assertIn("completion_evidence IS NOT NULL", source)
        self.assertIn("catalog_receipt", source)
        worker = (ROOT / "services/image_service/app/worker.py").read_text()
        self.assertIn("reconcile_completed_chapter_publication", worker)


if __name__ == "__main__":
    unittest.main()
