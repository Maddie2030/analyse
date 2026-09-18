from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/ownership/postgres-roles.v1.json"
ROUTES = ROOT / "contracts/ownership/routes.v1.json"
AUDIT = ROOT / "scripts/tests/postgres-role-audit.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P127PermissionSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.routes = json.loads(ROUTES.read_text(encoding="utf-8"))["routes"]
        cls.capabilities = {c["name"]: c for c in cls.contract["capabilities"]}

    def grants(self, capability: str):
        return {
            (g["object_type"], g["resource"]): set(g["privileges"])
            for g in self.capabilities[capability]["grants"]
        }

    def test_catalog_runtime_covers_taxonomy_sequences_and_delete_cleanup_reads(self):
        grants = self.grants("catalog_runtime")
        self.assertIn("usage", grants.get(("sequence", "genres_id_seq"), set()))
        self.assertIn("usage", grants.get(("sequence", "tags_id_seq"), set()))
        for table in ("scraper_series_drafts", "scraper_drafts", "scraper_batch_uploads"):
            self.assertIn("select", grants.get(("table", table), set()), table)

    def test_scraper_runtime_covers_history_publication_receipts_and_operation_sequence(self):
        grants = self.grants("scraper_runtime")
        self.assertTrue({"select", "insert"} <= grants.get(("table", "scraper_history"), set()))
        self.assertIn("select", grants.get(("table", "catalog_mutation_receipts"), set()))
        self.assertIn("usage", grants.get(("sequence", "scraper_operation_events_id_seq"), set()))

    def test_progress_runtime_keeps_catalog_read_for_reading_commands(self):
        grants = self.grants("progress_runtime")
        self.assertIn("select", grants.get(("table", "chapters"), set()))
        self.assertIn("select", grants.get(("view", "reading_state_v1"), set()))

    def test_scraper_scrape_route_declares_optional_history_write(self):
        route = next(r for r in self.routes if r["method"] == "POST" and r["path"] == "/api/scraper/scrape")
        writes = {
            (w["resource"], action)
            for w in route["permitted_writes"]
            if w["kind"] == "postgres"
            for action in w["actions"]
        }
        self.assertIn(("scraper_history", "insert"), writes)

    def test_postgres_role_audit_discovers_implicit_serial_sequences(self):
        audit = _load_module(AUDIT, "p127_postgres_role_audit")
        _tables, _views, _functions, sequences = audit.current_schema_objects()
        for sequence in ("genres_id_seq", "tags_id_seq", "scraper_operation_events_id_seq"):
            self.assertIn(sequence, sequences)


if __name__ == "__main__":
    unittest.main()
