import csv
from functools import partial
import importlib.util
import json
import re
import subprocess
import unittest
from pathlib import Path

from tests.regression.contract_test_utils import read_json_file, run_mutated_json_audit

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "contracts" / "ownership" / "routes.v1.json"
SCHEMA = ROOT / "contracts" / "ownership" / "routes.schema.v1.json"
README = ROOT / "contracts" / "ownership" / "README.md"
COVERAGE = ROOT / "tests" / "api" / "endpoint_coverage.tsv"
ROUTE_AUDIT = ROOT / "scripts" / "tests" / "api-route-audit.py"
OWNERSHIP_MUTATION_AUDIT = partial(
    run_mutated_json_audit, root=ROOT, source=MANIFEST,
    command=["python", "scripts/tests/ownership-route-audit.py", "--manifest"],
)

REQUIRED_ROUTE_FIELDS = {
    "operation",
    "method",
    "path",
    "lifecycle",
    "access_plane",
    "owner",
    "handler",
    "version",
    "authentication",
    "permitted_writes",
    "dependencies",
    "consumers",
    "events",
    "acceptance_test_ids",
    "evidence",
}
ALLOWED_PLANES = {"public", "admin", "both", "internal"}
ALLOWED_AUTH_MODES = {"none", "session", "admin-session", "workload-token", "chapter-grant", "mixed"}
ALLOWED_PRINCIPALS = {"anonymous", "user", "admin", "workload", "chapter-reader", "mixed"}
ALLOWED_WRITE_KINDS = {"postgres", "event", "seaweedfs", "cache", "filesystem", "external-http"}
ALLOWED_DEP_KINDS = {"service", "postgres", "cache", "event-bus", "seaweedfs", "filesystem", "external-http"}
ALLOWED_CONSUMER_KINDS = {"web", "android", "admin-web", "service", "operator"}
ALLOWED_EVENT_DIRECTIONS = {"publish", "consume", "request"}
OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]+$")
ACCEPTANCE_RE = re.compile(r"^[A-Z]+-[0-9]{2}$")


def load_route_audit():
    spec = importlib.util.spec_from_file_location("mreader_api_route_audit_for_manifest", ROUTE_AUDIT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ROUTE_AUDIT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_manifest():
    return read_json_file(MANIFEST)


class OwnershipRouteManifestTests(unittest.TestCase):
    def test_schema_and_readme_define_strict_v1_contract(self):
        self.assertTrue(SCHEMA.is_file(), f"missing {SCHEMA.relative_to(ROOT)}")
        self.assertTrue(README.is_file(), f"missing {README.relative_to(ROOT)}")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual(False, schema["additionalProperties"])
        route = schema["$defs"]["route"]
        self.assertEqual(False, route["additionalProperties"])
        self.assertEqual(REQUIRED_ROUTE_FIELDS, set(route["required"]))
        self.assertEqual(ALLOWED_PLANES, set(route["properties"]["access_plane"]["enum"]))
        self.assertEqual(ALLOWED_AUTH_MODES, set(schema["$defs"]["authentication"]["properties"]["mode"]["enum"]))
        self.assertEqual(ALLOWED_PRINCIPALS, set(schema["$defs"]["authentication"]["properties"]["principal"]["enum"]))
        self.assertEqual(ALLOWED_WRITE_KINDS, set(schema["$defs"]["write"]["properties"]["kind"]["enum"]))
        self.assertEqual(ALLOWED_DEP_KINDS, set(schema["$defs"]["dependency"]["properties"]["kind"]["enum"]))
        self.assertEqual(ALLOWED_CONSUMER_KINDS, set(schema["$defs"]["consumer"]["properties"]["kind"]["enum"]))
        self.assertEqual(ALLOWED_EVENT_DIRECTIONS, set(schema["$defs"]["event"]["properties"]["direction"]["enum"]))
        readme = README.read_text(encoding="utf-8")
        for phrase in ("current source routes only", "permitted_writes", "P09.3", "same source tree"):
            self.assertIn(phrase, readme)

    def test_manifest_has_versioned_top_level_contract(self):
        data = load_manifest()
        self.assertEqual("mreader.ownership-routes", data["contract"])
        self.assertEqual(1, data["version"])
        self.assertIsInstance(data["routes"], list)
        self.assertTrue(data["routes"])

    def test_manifest_route_rows_are_structurally_strict(self):
        routes = load_manifest()["routes"]
        operations = set()
        keys = set()
        for route in routes:
            self.assertEqual(REQUIRED_ROUTE_FIELDS, set(route), route)
            self.assertRegex(route["operation"], OPERATION_RE)
            self.assertNotIn(route["operation"], operations)
            operations.add(route["operation"])
            key = (route["method"], route["path"], route["lifecycle"])
            self.assertNotIn(key, keys)
            keys.add(key)
            self.assertEqual("current", route["lifecycle"])
            self.assertIn(route["access_plane"], ALLOWED_PLANES)
            self.assertTrue(route["owner"])
            self.assertTrue(route["handler"])
            self.assertEqual("v1", route["version"])
            auth = route["authentication"]
            self.assertIn(auth["mode"], ALLOWED_AUTH_MODES)
            self.assertIn(auth["principal"], ALLOWED_PRINCIPALS)
            self.assertIn("required_role", auth)
            self.assertIn("credential_scope", auth)
            for write in route["permitted_writes"]:
                self.assertIn(write["kind"], ALLOWED_WRITE_KINDS)
                self.assertTrue(write["resource"])
                self.assertTrue(write["actions"])
            for dep in route["dependencies"]:
                self.assertIn(dep["kind"], ALLOWED_DEP_KINDS)
                self.assertTrue(dep["name"])
            for consumer in route["consumers"]:
                self.assertIn(consumer["kind"], ALLOWED_CONSUMER_KINDS)
                self.assertTrue(consumer["name"])
            for event in route["events"]:
                self.assertIn(event["direction"], ALLOWED_EVENT_DIRECTIONS)
                self.assertTrue(event["name"])
            self.assertTrue(route["acceptance_test_ids"])
            for gate in route["acceptance_test_ids"]:
                self.assertRegex(gate, ACCEPTANCE_RE)
            self.assertTrue(route["evidence"])

    def test_current_manifest_matches_source_and_coverage_exactly(self):
        audit = load_route_audit()
        source_records = audit.source_route_records()
        source = {(r.method, r.path) for r in source_records}
        with COVERAGE.open(encoding="utf-8", newline="") as fh:
            coverage_rows = list(csv.DictReader(fh, delimiter="\t"))
        coverage = {(r["method"].upper(), audit.normalize(r["path"])) for r in coverage_rows}
        data = load_manifest()
        manifest = {(r["method"].upper(), audit.normalize(r["path"])) for r in data["routes"]}
        self.assertEqual(source, coverage)
        self.assertEqual(source, manifest)
        by_key = {(r["method"], audit.normalize(r["path"])): r for r in data["routes"]}
        for record in source_records:
            self.assertEqual(
                f"{record.source}:{record.handler}",
                by_key[(record.method, record.path)]["handler"],
            )


    def test_postgres_write_resources_are_current_tables(self):
        schema_text = (ROOT / "db" / "init.sql").read_text(encoding="utf-8")
        for migration in (ROOT / "db" / "migrations").glob("*.sql"):
            schema_text += "\n" + migration.read_text(encoding="utf-8", errors="ignore")
        tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([A-Za-z0-9_]+)", schema_text))
        self.assertTrue(tables)
        for route in load_manifest()["routes"]:
            for write in route["permitted_writes"]:
                if write["kind"] == "postgres":
                    self.assertIn(write["resource"], tables, f"{route['method']} {route['path']}")

    def test_literal_first_party_consumers_have_current_source_evidence(self):
        roots = {
            "web": [ROOT / "frontend" / "src"],
            "admin-web": [ROOT / "frontend" / "src"],
            "android": [ROOT / "android" / "app" / "src"],
        }
        corpora = {}
        for kind, source_roots in roots.items():
            texts = []
            for source_root in source_roots:
                if not source_root.is_dir():
                    continue
                for source in source_root.rglob("*"):
                    if source.is_file() and source.suffix in {".ts", ".tsx", ".js", ".jsx", ".kt"}:
                        texts.append(source.read_text(encoding="utf-8", errors="ignore"))
            corpora[kind] = "\n".join(texts)
        for route in load_manifest()["routes"]:
            fragments = [f for f in re.split(r"\{[^}]+\}|\*", route["path"]) if len(f) >= 4]
            for consumer in route["consumers"]:
                if consumer["kind"] not in corpora:
                    continue
                self.assertTrue(
                    any(fragment in corpora[consumer["kind"]] for fragment in fragments),
                    f"unproven {consumer['kind']} consumer for {route['method']} {route['path']}",
                )

    def test_internal_consumers_are_non_browser_and_read_only_gets_do_not_write(self):
        for route in load_manifest()["routes"]:
            if route["access_plane"] == "internal":
                self.assertFalse(
                    {c["kind"] for c in route["consumers"]} & {"web", "android", "admin-web"},
                    route,
                )
            if route["method"] == "GET":
                self.assertEqual([], route["permitted_writes"], route)

    def test_hybrid_validation_and_readme_include_ownership_audit_workflow(self):
        validate = (ROOT / "scripts" / "hybrid" / "validate.sh").read_text(encoding="utf-8")
        self.assertIn("./scripts/run-ownership-route-audit.sh", validate)
        readme = README.read_text(encoding="utf-8")
        ordered = [
            "change the route source",
            "update `tests/api/endpoint_coverage.tsv`",
            "update `routes.v1.json`",
            "run both the route coverage audit and ownership route audit",
            "only then allow downstream P09.3+ consumers",
        ]
        positions = [readme.index(marker) for marker in ordered]
        self.assertEqual(sorted(positions), positions)


    def test_semantic_auditor_rejects_missing_route_and_handler_drift(self):
        missing = OWNERSHIP_MUTATION_AUDIT(mutate=lambda data: data["routes"].pop())
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("route set", missing.stderr.lower())

        def drift(data):
            data["routes"][0]["handler"] = "services/nowhere.py:nope"
        handler = OWNERSHIP_MUTATION_AUDIT(mutate=drift)
        self.assertNotEqual(0, handler.returncode)
        self.assertIn("handler", handler.stderr.lower())

    def test_semantic_auditor_rejects_gateway_and_internal_auth_contradictions(self):
        def public_admin(data):
            row = next(r for r in data["routes"] if r["path"].startswith("/api/scraper/"))
            row["access_plane"] = "public"
        gateway = OWNERSHIP_MUTATION_AUDIT(mutate=public_admin)
        self.assertNotEqual(0, gateway.returncode)
        self.assertIn("access_plane", gateway.stderr)

        def browser_internal(data):
            row = next(r for r in data["routes"] if r["path"].startswith("/internal/v1/"))
            row["authentication"] = {"mode": "session", "principal": "user", "required_role": None, "credential_scope": None}
            row["consumers"] = [{"kind": "web", "name": "frontend"}]
        internal = OWNERSHIP_MUTATION_AUDIT(mutate=browser_internal)
        self.assertNotEqual(0, internal.returncode)
        self.assertIn("internal", internal.stderr.lower())

    def test_semantic_auditor_rejects_missing_evidence_and_undeclared_mutation(self):
        def missing_evidence(data):
            data["routes"][0]["evidence"] = ["tests/api/does-not-exist.py"]
        evidence = OWNERSHIP_MUTATION_AUDIT(mutate=missing_evidence)
        self.assertNotEqual(0, evidence.returncode)
        self.assertIn("evidence", evidence.stderr.lower())

        def no_writer(data):
            row = next(r for r in data["routes"] if r["method"] == "DELETE")
            row["permitted_writes"] = []
        mutation = OWNERSHIP_MUTATION_AUDIT(mutate=no_writer)
        self.assertNotEqual(0, mutation.returncode)
        self.assertIn("permitted_writes", mutation.stderr)


if __name__ == "__main__":
    unittest.main()
