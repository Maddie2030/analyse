import json
import os
import subprocess
import unittest
from pathlib import Path

from tests.regression.contract_test_utils import text_marker_mismatches

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "ownership" / "postgres-roles.v1.json"
RENDERER = ROOT / "scripts" / "hybrid" / "render-postgres-role-sql.py"
RECONCILE = ROOT / "scripts" / "hybrid" / "reconcile-postgres-roles.sh"
STATEFUL = ROOT / "scripts" / "hybrid" / "stateful-up.sh"


def run_renderer(*, mode: str = "reconcile") -> subprocess.CompletedProcess[str]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    env = os.environ.copy()
    for workload in contract["workloads"]:
        env[f"MREADER_DB_ROLE_PASSWORD_{workload['role'].upper()}"] = "test-secret"
    command = ["python", str(RENDERER), "--contract", str(CONTRACT), "--database", "mreader"]
    if mode != "reconcile":
        command += ["--mode", mode]
    return subprocess.run(
        command, cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )


class P093PostgresRoleRendererTests(unittest.TestCase):
    def test_renderer_emits_restrictive_revoke_and_exact_grant_sql(self):
        self.assertTrue(RENDERER.is_file(), f"missing {RENDERER.relative_to(ROOT)}")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        result = run_renderer()
        self.assertEqual(0, result.returncode, result.stderr)
        sql = result.stdout
        for capability in contract["capabilities"]:
            name = capability["name"]
            self.assertIn(f'ALTER ROLE "{name}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', sql)
        for workload in contract["workloads"]:
            role = workload["role"]
            self.assertIn(f'ALTER ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', sql)
            self.assertIn(f'REVOKE ALL PRIVILEGES ON DATABASE "mreader" FROM "{role}"', sql)
            self.assertIn(f'GRANT CONNECT ON DATABASE "mreader" TO "{role}"', sql)
            self.assertIn(f'GRANT USAGE ON SCHEMA public TO "{role}"', sql)
            for capability in workload["capabilities"]:
                self.assertIn(f'GRANT "{capability}" TO "{role}"', sql)
        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC", sql)
        self.assertIn(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
            sql,
        )
        self.assertIn("has_table_privilege", sql)
        self.assertIn("has_sequence_privilege", RENDERER.read_text(encoding="utf-8"))
        self.assertIn("has_function_privilege", sql)
        self.assertIn("pg_has_role", sql)
        self.assertIn("P09.3 effective privilege verification failed", sql)
        self.assertNotIn("ON ALL TABLES", sql)
        self.assertNotIn("ON ALL SEQUENCES", sql)
        self.assertNotIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT", sql)
        self.assertNotIn(" SUPERUSER", sql)

class P093PostgresRoleVerifyModeTests(unittest.TestCase):
    def test_verify_mode_reuses_effective_assertions_without_mutation(self):
        result = run_renderer(mode="verify")
        self.assertEqual(0, result.returncode, result.stderr)
        sql = result.stdout
        self.assertIn("P09.3 effective privilege verification failed", sql)
        self.assertIn("ROLLBACK;", sql)
        for mutation in ("CREATE ROLE", "ALTER ROLE", "GRANT CONNECT", "REVOKE ALL PRIVILEGES"):
            self.assertNotIn(mutation, sql)

    def test_default_mode_remains_reconciliation(self):
        result = run_renderer()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CREATE ROLE", result.stdout)
        self.assertIn("GRANT CONNECT", result.stdout)
        self.assertIn("COMMIT;", result.stdout)


class P093PostgresRoleReconcileTests(unittest.TestCase):
    def test_reconciler_audits_generates_passwords_persists_dsns_and_uses_compose_psql(self):
        self.assertTrue(RECONCILE.is_file(), f"missing {RECONCILE.relative_to(ROOT)}")
        problems = text_marker_mismatches(
            RECONCILE,
            required=(
                "scripts/run-postgres-role-audit.sh",
                "openssl rand -hex 24",
                "MREADER_DB_ROLE_PASSWORD_",
                "env_set \"$ENV_FILE\"",
                "render-postgres-role-sql.py",
                "--mode verify",
                "docker compose --env-file",
                "psql -X -v ON_ERROR_STOP=1",
            ),
            forbidden=("echo \"$password\"", "printf '%s' \"$password\""),
        )
        self.assertEqual([], problems)

    def test_stateful_core_reconciles_roles_after_migration_before_returning_ready(self):
        text = STATEFUL.read_text(encoding="utf-8")
        migration = ' --profile migration run --rm migrate'
        reconcile = 'reconcile-postgres-roles.sh'
        ready = 'Hybrid stateful core is healthy/migrated'
        self.assertIn(reconcile, text)
        self.assertLess(text.index(migration), text.index(reconcile))
        self.assertLess(text.index(reconcile), text.index(ready))


if __name__ == "__main__":
    unittest.main()
