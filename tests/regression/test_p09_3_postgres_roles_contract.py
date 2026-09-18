import json
from functools import partial
import re
import unittest
from pathlib import Path

from tests.regression.contract_test_utils import read_json_file, run_json_audit, run_mutated_json_audit

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "ownership" / "postgres-roles.v1.json"
SCHEMA = ROOT / "contracts" / "ownership" / "postgres-roles.v1.schema.json"
README = ROOT / "contracts" / "ownership" / "POSTGRES-ROLES.md"
AUDIT = ROOT / "scripts" / "tests" / "postgres-role-audit.py"
ROLE_MUTATION_AUDIT = partial(
    run_mutated_json_audit, root=ROOT, source=CONTRACT,
    command=["python", str(AUDIT), "--contract"],
)

CAPABILITY_FIELDS = {"name", "login", "role_attributes", "grants", "acceptance_test_ids"}
WORKLOAD_FIELDS = {
    "workload",
    "role",
    "login",
    "role_attributes",
    "capabilities",
    "dsn_env",
    "scope_file",
    "acceptance_test_ids",
}
EXCEPTION_FIELDS = {"workload", "resource", "privileges", "evidence", "reason"}
GRANT_FIELDS = {"object_type", "resource", "privileges", "columns"}
ALLOWED_OBJECT_TYPES = {"database", "schema", "table", "view", "sequence", "function"}
ALLOWED_PRIVILEGES = {"connect", "usage", "select", "insert", "update", "delete", "execute"}
ROLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]+$")


def append_table_grant(data, capability_name, resource, privilege="update"):
    capability = next(c for c in data["capabilities"] if c["name"] == capability_name)
    capability["grants"].append({
        "object_type": "table",
        "resource": resource,
        "privileges": [privilege],
        "columns": [],
    })





class P093PostgresRoleStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_json_file(CONTRACT)

    def test_contract_schema_and_readme_define_strict_v1_shape(self):
        self.assertTrue(SCHEMA.is_file(), f"missing {SCHEMA.relative_to(ROOT)}")
        self.assertTrue(README.is_file(), f"missing {README.relative_to(ROOT)}")
        schema = read_json_file(SCHEMA)
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            {"contract", "version", "authorities", "capabilities", "workloads", "worker_exceptions", "acceptance_test_ids"},
            set(schema["required"]),
        )
        for def_name in ("capability", "workload", "grant", "worker_exception"):
            self.assertFalse(schema["$defs"][def_name]["additionalProperties"], def_name)
        readme = README.read_text(encoding="utf-8")
        for phrase in ("P09.2", "NOLOGIN", "workload login", "worker exception", "same source tree"):
            self.assertIn(phrase, readme)

    def test_contract_has_versioned_top_level_authorities(self):
        self.assertEqual("mreader.postgres-roles", self.data["contract"])
        self.assertEqual(1, self.data["version"])
        self.assertIn("contracts/ownership/routes.v1.json", self.data["authorities"])
        self.assertIn("docs/qualification/RC485-TABLE-DISPOSITION.md", self.data["authorities"])
        self.assertTrue(self.data["capabilities"] and self.data["workloads"] and self.data["acceptance_test_ids"])

    def test_capability_roles_are_strict_nonlogin_roles(self):
        seen = set()
        for capability in self.data["capabilities"]:
            self.assertEqual(CAPABILITY_FIELDS, set(capability), capability)
            self.assertRegex(capability["name"], ROLE_NAME_RE)
            self.assertNotIn(capability["name"], seen); seen.add(capability["name"])
            self.assertEqual("NOLOGIN", capability["login"]); self.assertEqual([], capability["role_attributes"])
            self.assertTrue(capability["acceptance_test_ids"])
            for grant in capability["grants"]:
                self.assertEqual(GRANT_FIELDS, set(grant), grant)
                self.assertIn(grant["object_type"], ALLOWED_OBJECT_TYPES)
                self.assertTrue(grant["resource"] and grant["privileges"])
                self.assertTrue(set(grant["privileges"]) <= ALLOWED_PRIVILEGES)
                self.assertIsInstance(grant["columns"], list)

    def test_workload_logins_and_worker_exceptions_are_strict(self):
        capability_names = {c["name"] for c in self.data["capabilities"]}
        workloads, roles = set(), set()
        for workload in self.data["workloads"]:
            self.assertEqual(WORKLOAD_FIELDS, set(workload), workload)
            self.assertNotIn(workload["workload"], workloads); workloads.add(workload["workload"])
            self.assertNotIn(workload["role"], roles); roles.add(workload["role"])
            self.assertEqual("LOGIN", workload["login"]); self.assertEqual([], workload["role_attributes"])
            self.assertTrue(set(workload["capabilities"]) <= capability_names)
            self.assertTrue((ROOT / workload["scope_file"]).is_file(), workload["scope_file"])
        for exception in self.data["worker_exceptions"]:
            self.assertEqual(EXCEPTION_FIELDS, set(exception), exception)
            self.assertTrue(set(exception["privileges"]) <= ALLOWED_PRIVILEGES)
            self.assertTrue(exception["reason"] and exception["evidence"])
            for evidence in exception["evidence"]:
                self.assertTrue((ROOT / evidence).exists(), evidence)



class P093PostgresScopePolicyTests(unittest.TestCase):
    def test_env_example_preserves_generated_role_credentials_during_salvage(self):
        keys = {
            line.split("=", 1)[0]
            for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        for workload in read_json_file(CONTRACT)["workloads"]:
            role = workload["role"].upper()
            self.assertIn(f"MREADER_DB_ROLE_PASSWORD_{role}", keys)
            self.assertIn(f"MREADER_DB_DSN_{role}", keys)

    def test_database_workload_scopes_use_only_contract_dsn_keys(self):
        forbidden = {"POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL", "POSTGRES_URL"}
        for workload in read_json_file(CONTRACT)["workloads"]:
            scope_path = ROOT / workload["scope_file"]
            if scope_path.suffix != ".keys":
                continue
            keys = {
                line.strip()
                for line in scope_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
            self.assertIn(workload["dsn_env"], keys, workload["workload"])
            self.assertFalse(
                (keys - {workload["dsn_env"]}) & forbidden,
                f"{workload['workload']} still exposes bootstrap/generic database keys",
            )


class P093PostgresRoleAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_json_file(CONTRACT)


    def test_real_contract_passes_same_tree_semantic_audit(self):
        result = run_json_audit(root=ROOT, candidate=CONTRACT, command=["python", str(AUDIT), "--contract"])
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_audit_rejects_unknown_table_and_uncovered_request_write(self):
        def unknown(data):
            data["capabilities"][0]["grants"].append({"object_type":"table","resource":"definitely_not_a_table","privileges":["update"],"columns":[]})
        result = ROLE_MUTATION_AUDIT(mutate=unknown)
        self.assertNotEqual(0, result.returncode); self.assertIn("unknown postgres table", (result.stdout + result.stderr).lower())
        def missing(data):
            cap = next(c for c in data["capabilities"] if c["name"] == "catalog_runtime")
            cap["grants"] = [g for g in cap["grants"] if g["resource"] != "series"]
        result = ROLE_MUTATION_AUDIT(mutate=missing)
        self.assertNotEqual(0, result.returncode); self.assertIn("uncovered p09.2 postgres write", (result.stdout + result.stderr).lower())

    def test_audit_rejects_extra_write_keda_mutation_and_bootstrap_dsn(self):
        result = ROLE_MUTATION_AUDIT(
            mutate=lambda data: append_table_grant(data, "realtime_runtime", "comments")
        )
        self.assertNotEqual(0, result.returncode); self.assertIn("undocumented extra write", (result.stdout + result.stderr).lower())
        result = ROLE_MUTATION_AUDIT(
            mutate=lambda data: append_table_grant(data, "keda_metrics_runtime", "database_operations")
        )
        self.assertNotEqual(0, result.returncode); self.assertIn("keda must be read-only", (result.stdout + result.stderr).lower())
        result = ROLE_MUTATION_AUDIT(mutate=lambda data: data["workloads"][0].update(dsn_env="POSTGRES_PASSWORD"))
        self.assertNotEqual(0, result.returncode); self.assertIn("bootstrap credential", (result.stdout + result.stderr).lower())


class P093PostgresIntegrationTests(unittest.TestCase):
    def test_hybrid_validation_and_operator_docs_use_supported_role_flow(self):
        validate = (ROOT / "scripts/hybrid/validate.sh").read_text(encoding="utf-8")
        audit_call = "./scripts/run-postgres-role-audit.sh"
        docker_preflight = "for cmd in docker kubectl awk grep"
        self.assertIn(audit_call, validate)
        self.assertLess(validate.index(audit_call), validate.index(docker_preflight))

        role_doc = README.read_text(encoding="utf-8").lower()
        ops_doc = (ROOT / "docs/operations/POSTGRES_BACKUP_AND_RESTORE.md").read_text(encoding="utf-8").lower()
        for marker in ("after migrations", "workload-specific", "scripts/hybrid/reconcile-postgres-roles.sh"):
            with self.subTest(marker=marker):
                self.assertIn(marker, role_doc)
                self.assertIn(marker, ops_doc)
        self.assertIn("p09-3-postgres-grants-gate.sh", role_doc)
        self.assertIn("p09-3-postgres-grants-gate.sh", ops_doc)


if __name__ == "__main__":
    unittest.main()
