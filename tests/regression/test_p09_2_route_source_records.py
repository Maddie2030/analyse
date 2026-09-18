import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts" / "tests" / "api-route-audit.py"


def load_route_audit():
    spec = importlib.util.spec_from_file_location("mreader_api_route_audit", AUDIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUDIT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P092RouteSourceRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_route_audit()

    def test_source_route_records_preserve_the_canonical_route_set(self):
        records = self.audit.source_route_records()
        record_keys = {(record.method, record.path) for record in records}
        self.assertEqual(139, len(record_keys))
        self.assertEqual(record_keys, self.audit.source_routes())
        self.assertEqual(len(record_keys), len(records), "route records must be unique by method/path")

    def test_every_source_route_record_has_source_and_handler_provenance(self):
        records = self.audit.source_route_records()
        self.assertTrue(records)
        for record in records:
            self.assertTrue(record.source, record)
            self.assertTrue(record.handler, record)
            self.assertTrue((ROOT / record.source).is_file(), record)

    def test_representative_python_go_and_typescript_handlers_are_exact(self):
        records = {(record.method, record.path): record for record in self.audit.source_route_records()}

        login = records[("POST", "/api/auth/login")]
        self.assertEqual("services/auth_service/app/routers/auth.py", login.source)
        self.assertEqual("login", login.handler)

        catalog = records[("GET", "/api/catalog/series")]
        self.assertEqual("services/catalog_go/internal/httpapi/api.go", catalog.source)
        self.assertEqual("a.listSeries", catalog.handler)

        metrics = records[("GET", "/api/social/series/{seriesId}/metrics")]
        self.assertEqual("services/social_ts/src/routes.ts", metrics.source)
        self.assertEqual("GET /api/social/series/{seriesId}/metrics", metrics.handler)

        media_internal = {
            ("POST", "/internal/v1/media/jobs/thumbnail/{series_slug}"),
            ("GET", "/internal/v1/media/jobs/{job_id}"),
            ("POST", "/internal/v1/media/jobs/chapter/{series_slug}/{chapter_slug}"),
        }
        self.assertTrue(media_internal <= records.keys())
        for key in media_internal:
            self.assertEqual("services/image_service/app/routers/jobs.py", records[key].source)


if __name__ == "__main__":
    unittest.main()
