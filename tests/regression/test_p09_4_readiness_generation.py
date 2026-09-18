import hashlib
import json
import re
import runpy
import subprocess
import types
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "hybrid" / "p09-4-readiness.py"
WRAPPER = ROOT / "scripts" / "hybrid" / "p09-4-readiness.sh"
CONTRACT = ROOT / "contracts" / "ownership" / "postgres-roles.v1.json"
MIGRATIONS = ROOT / "db" / "migrations"
MANIFEST_RENDERER = ROOT / "scripts" / "hybrid" / "render-generation-manifests.py"
USER_APPS = ROOT / "deploy" / "docker-desktop-hybrid" / "user-apps.yaml"
ADMIN_APPS = ROOT / "deploy" / "docker-desktop-hybrid" / "admin-apps.yaml"
DEPLOY_SCRIPT = ROOT / "scripts" / "hybrid" / "deploy.sh"
STATEFUL_SCRIPT = ROOT / "scripts" / "hybrid" / "stateful-up.sh"
RESTORE_SCRIPT = ROOT / "scripts" / "backup" / "postgres-restore.sh"
RUNTIME_GATE = ROOT / "scripts" / "test" / "p09-4-runtime-gate.sh"
VALIDATE_SCRIPT = ROOT / "scripts" / "hybrid" / "validate.sh"


HELPER_API = types.SimpleNamespace(**runpy.run_path(str(HELPER)))


def render_generation_manifests(output_dir: Path, token: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python", str(MANIFEST_RENDERER), "--contract", str(CONTRACT),
            "--generation", token, "--input", str(USER_APPS), "--input", str(ADMIN_APPS),
            "--output-dir", str(output_dir),
        ],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def deployment_documents(text: str) -> dict[str, str]:
    result = {}
    for document in re.split(r"(?m)^---\s*$", text):
        if not re.search(r"(?m)^kind:\s*Deployment\s*$", document):
            continue
        match = re.search(r"(?ms)^metadata:\s*\n(?:(?:  .*)\n)*?  name:\s*([^\s#]+)", document)
        if match:
            result[match.group(1)] = document
    return result


class P094TokenAndMigrationTests(unittest.TestCase):
    def test_token_is_stable_and_changes_on_generation_contract_or_migration(self):
        token = HELPER_API.deployment_generation_token(
            generation=7, installation_fingerprint="inst_0123456789abcdef",
            migration="060_database_restore_fencing.sql", contract_sha256="a" * 64,
        )
        self.assertRegex(token, r"^p094-[0-9a-f]{64}$")
        self.assertEqual(token, HELPER_API.deployment_generation_token(
            generation=7, installation_fingerprint="inst_0123456789abcdef",
            migration="060_database_restore_fencing.sql", contract_sha256="a" * 64,
        ))
        variants = [
            dict(generation=8, installation_fingerprint="inst_0123456789abcdef", migration="060_database_restore_fencing.sql", contract_sha256="a" * 64),
            dict(generation=7, installation_fingerprint="inst_fedcba9876543210", migration="060_database_restore_fencing.sql", contract_sha256="a" * 64),
            dict(generation=7, installation_fingerprint="inst_0123456789abcdef", migration="061_future.sql", contract_sha256="a" * 64),
            dict(generation=7, installation_fingerprint="inst_0123456789abcdef", migration="060_database_restore_fencing.sql", contract_sha256="b" * 64),
        ]
        for values in variants:
            self.assertNotEqual(token, HELPER_API.deployment_generation_token(**values))

    def test_latest_migration_is_060_database_restore_fencing(self):
        self.assertEqual("060_database_restore_fencing.sql", HELPER_API.latest_migration_name(MIGRATIONS))


class P094CredentialReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_missing_or_malformed_role_dsn_is_credentials_not_ready(self):
        with self.assertRaises(HELPER_API.ReadinessError) as ctx:
            HELPER_API.validate_workload_credentials(self.contract, {}, ROOT)
        self.assertEqual("credentials-not-ready", ctx.exception.category)
        env = {
            f"MREADER_DB_DSN_{row['role'].upper()}": "postgresql://wrong-role:secret@host/db"
            for row in self.contract["workloads"] if row["workload"] != "keda-postgres"
        }
        with self.assertRaises(HELPER_API.ReadinessError) as ctx:
            HELPER_API.validate_workload_credentials(self.contract, env, ROOT)
        self.assertEqual("credentials-not-ready", ctx.exception.category)

    def test_scope_must_contain_declared_runtime_dsn_and_omit_bootstrap_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = {"workloads": [{"workload": "demo", "role": "mreader_demo", "dsn_env": "DEMO_DATABASE_URL", "scope_file": "scope.keys"}]}
            env = {"MREADER_DB_DSN_MREADER_DEMO": "postgresql://mreader_demo:secret@host/db"}
            (root / "scope.keys").write_text("POSTGRES_USER\nDEMO_DATABASE_URL\n", encoding="utf-8")
            with self.assertRaises(HELPER_API.ReadinessError) as ctx:
                HELPER_API.validate_workload_credentials(contract, env, root)
            self.assertEqual("credentials-not-ready", ctx.exception.category)
            (root / "scope.keys").write_text("DEMO_DATABASE_URL\n", encoding="utf-8")
            self.assertEqual("demo", HELPER_API.validate_workload_credentials(contract, env, root)[0]["workload"])


class P094RestoreMirrorTests(unittest.TestCase):
    def test_restore_control_requires_inst_fingerprint_and_positive_generation(self):
        with tempfile.TemporaryDirectory() as td:
            control = Path(td) / "restore-control.json"
            control.write_text(json.dumps({"installation_fingerprint": "bad", "restore_generation": 0}), encoding="utf-8")
            with self.assertRaises(HELPER_API.ReadinessError) as ctx:
                HELPER_API.load_restore_control(control)
            self.assertEqual("generation-not-ready", ctx.exception.category)
            control.write_text(json.dumps({"installation_fingerprint": "inst_0123456789abcdef", "restore_generation": 3}), encoding="utf-8")
            self.assertEqual(("inst_0123456789abcdef", 3), HELPER_API.load_restore_control(control))

    def test_readiness_sql_checks_latest_migration_and_singleton_restore_mirror(self):
        sql = HELPER_API.render_readiness_sql(
            database="manhwa", migration="060_database_restore_fencing.sql",
            installation_fingerprint="inst_0123456789abcdef", generation=3,
        )
        for marker in ("schema_migrations", "database_restore_state", "restore_rows <> 1",
                       "P09.4 schema-not-ready", "P09.4 generation-not-ready",
                       ":'latest_migration'", ":'installation_fingerprint'", ":restore_generation", "ROLLBACK;"):
            self.assertIn(marker, sql)


class P094ManifestCoverageTests(unittest.TestCase):
    def test_renderer_stamps_every_contract_database_deployment(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        expected = {row["workload"] for row in contract["workloads"] if row["workload"] != "keda-postgres"}
        with tempfile.TemporaryDirectory() as td:
            result = render_generation_manifests(Path(td), "p094-" + "a" * 64)
            self.assertEqual(0, result.returncode, result.stderr)
            rendered = {}
            for source in (USER_APPS, ADMIN_APPS):
                rendered.update(deployment_documents((Path(td) / source.name).read_text(encoding="utf-8")))
            self.assertTrue(expected <= set(rendered))
            for workload in expected:
                self.assertIn("name: MREADER_DEPLOYMENT_GENERATION", rendered[workload])
                self.assertIn("value: p094-" + "a" * 64, rendered[workload])

    def test_renderer_preserves_replica_zero_workers_and_adds_generation_env(self):
        originals = {}
        for source in (USER_APPS, ADMIN_APPS):
            originals.update(deployment_documents(source.read_text(encoding="utf-8")))
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        expected = {row["workload"] for row in contract["workloads"] if row["workload"] != "keda-postgres"}
        zero_workers = {name for name, doc in originals.items() if name in expected and "replicas: 0" in doc}
        with tempfile.TemporaryDirectory() as td:
            result = render_generation_manifests(Path(td), "p094-" + "b" * 64)
            self.assertEqual(0, result.returncode, result.stderr)
            rendered = {}
            for source in (USER_APPS, ADMIN_APPS):
                rendered.update(deployment_documents((Path(td) / source.name).read_text(encoding="utf-8")))
            for workload in zero_workers & set(rendered):
                self.assertIn("replicas: 0", rendered[workload])
                self.assertIn("MREADER_DEPLOYMENT_GENERATION", rendered[workload])

    def test_keda_postgres_contract_row_is_not_expected_to_be_a_deployment(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("keda-postgres", {row["workload"] for row in contract["workloads"]})
        docs = deployment_documents(USER_APPS.read_text()) | deployment_documents(ADMIN_APPS.read_text())
        self.assertNotIn("keda-postgres", docs)


class P094ManifestDeterminismTests(unittest.TestCase):
    def test_renderer_is_byte_stable_for_same_input_and_token(self):
        token = "p094-" + "c" * 64
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(0, render_generation_manifests(Path(a), token).returncode)
            self.assertEqual(0, render_generation_manifests(Path(b), token).returncode)
            for source in (USER_APPS, ADMIN_APPS):
                self.assertEqual((Path(a) / source.name).read_bytes(), (Path(b) / source.name).read_bytes())

    def test_renderer_changes_output_when_token_changes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(0, render_generation_manifests(Path(a), "p094-" + "d" * 64).returncode)
            self.assertEqual(0, render_generation_manifests(Path(b), "p094-" + "e" * 64).returncode)
            self.assertNotEqual((Path(a) / USER_APPS.name).read_bytes(), (Path(b) / USER_APPS.name).read_bytes())

    def test_renderer_does_not_modify_checked_in_manifests(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (USER_APPS, ADMIN_APPS)}
        with tempfile.TemporaryDirectory() as td:
            render_generation_manifests(Path(td), "p094-" + "f" * 64)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (USER_APPS, ADMIN_APPS)})


class P094DeployOrderingTests(unittest.TestCase):
    def test_deploy_sequence_is_fail_closed_until_autoscaling_restore(self):
        text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        sequence = (
            '"$ROOT/scripts/hybrid/stateful-up.sh" core',
            'p09-4-readiness.sh',
            'for workload in "${user_workloads[@]}"; do create_workload_secret',
            'render-generation-manifests.py',
            'kubectl apply -f "$GENERATION_MANIFEST_DIR/user-apps.yaml"',
            'for d in auth-service catalog-go reader-go progress-go social-ts frontend realtime-go user-gateway',
            'verify_all_db_workload_generations || exit $?',
            'install-autoscaling.sh',
            'kubectl apply -f deploy/docker-desktop-hybrid/user-hpa.yaml',
        )
        positions = [text.find(marker) for marker in sequence]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        readiness = positions[1]
        rollout = positions[5]
        for marker in ("install-autoscaling.sh", "user-hpa.yaml", "user-keda.yaml", "admin-keda.yaml"):
            autoscaler = text.find(marker)
            self.assertGreater(autoscaler, readiness)
            self.assertGreater(autoscaler, rollout)
        self.assertGreater(text.rfind("keda_metric_connectivity_check"), text.find("install-autoscaling.sh"))

    def test_stateful_core_still_orders_migration_before_reconcile(self):
        text = STATEFUL_SCRIPT.read_text(encoding="utf-8")
        migration = text.find("--profile migration run --rm migrate")
        reconcile = text.find("reconcile-postgres-roles.sh")
        self.assertGreaterEqual(migration, 0)
        self.assertGreater(reconcile, migration)
        self.assertIn("application resume still requires P09.4 deploy.sh readiness", text)


class P094RestoreResumeTests(unittest.TestCase):
    def test_restore_rejoins_canonical_deploy_gate_without_direct_resume(self):
        text = RESTORE_SCRIPT.read_text(encoding="utf-8")
        direct_resume_markers = (
            "kubectl apply -f deploy/docker-desktop-hybrid/user-apps.yaml",
            "kubectl apply -f deploy/docker-desktop-hybrid/admin-apps.yaml",
            "kubectl apply -f deploy/docker-desktop-hybrid/user-hpa.yaml",
            "kubectl apply -f deploy/docker-desktop-hybrid/user-keda.yaml",
            "kubectl apply -f deploy/docker-desktop-hybrid/admin-keda.yaml",
            "--profile migration run --rm migrate",
        )
        for marker in direct_resume_markers:
            self.assertNotIn(marker, text)
        restore = text.index('restore-public-id "$PUBLIC_ID"')
        deploy = text.index('"$ROOT/scripts/hybrid/deploy.sh"')
        self.assertGreater(deploy, restore)
        self.assertIn("application remains quiesced", text)



class P094RuntimeGateContractTests(unittest.TestCase):
    def test_runtime_and_static_validation_contracts_are_fail_closed(self):
        self.assertTrue(RUNTIME_GATE.is_file(), f"missing {RUNTIME_GATE.relative_to(ROOT)}")
        unauthorized = subprocess.run(
            [str(RUNTIME_GATE)], cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(2, unauthorized.returncode)
        self.assertIn("P09.4 RUNTIME GATE BLOCKED", unauthorized.stderr)

        runtime = RUNTIME_GATE.read_text(encoding="utf-8")
        required = (
            "MREADER_P09_4_RUNTIME_CONFIRM", "current-hybrid",
            "MREADER_P09_4_EXPECT_PREVIOUS_GENERATION", "docker info",
            "kubectl config current-context", "p09-4-readiness.sh",
            "quiesce-before-migration.sh", "MISMATCH_GENERATION",
            "get hpa", "get scaledobject", "scripts/hybrid/deploy.sh",
            "MREADER_DEPLOYMENT_GENERATION", "P09.4 RUNTIME GATE PASSED",
        )
        lookaheads = "".join(f"(?=.*{re.escape(marker)})" for marker in required)
        self.assertRegex(runtime, re.compile(lookaheads, re.DOTALL))
        self.assertLess(runtime.index("MREADER_P09_4_RUNTIME_CONFIRM"), runtime.index("quiesce-before-migration.sh"))
        self.assertIsNone(re.search(r"advance_restore_generation|UPDATE database_restore_state", runtime))
        self.assertIn('for cmd in docker kubectl; do require_command "$cmd"; done', runtime)
        self.assertNotIn('for cmd in docker kubectl jq python', runtime)
        self.assertNotRegex(runtime, re.compile(r"(?m)^\s*jq\s"))
        self.assertIn('PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"', runtime)
        self.assertIn('json.load', runtime)

        validation = VALIDATE_SCRIPT.read_text(encoding="utf-8")
        self.assertRegex(
            validation,
            r'python-runtime\.sh" -m unittest tests\.regression\.test_p09_4_readiness_generation -v',
        )
        self.assertNotIn("p09-4-runtime-gate.sh", validation)


class P094ReadinessShellContractTests(unittest.TestCase):
    def test_wrapper_fails_closed_before_database_checks_and_reuses_p09_3_verifier(self):
        self.assertTrue(WRAPPER.is_file(), f"missing {WRAPPER.relative_to(ROOT)}")
        text = WRAPPER.read_text(encoding="utf-8")
        required = (
            "resolve-db-protection-root.sh",
            "restore-cutover-*.json",
            "P09_4_READINESS=restore-state-ambiguous",
            "scripts/run-postgres-role-audit.sh",
            "render-postgres-role-sql.py",
            "--mode verify",
            "p09-4-readiness.py",
            "docker compose --env-file",
            "psql -X -v ON_ERROR_STOP=1",
            "P09_4_READINESS=grants-not-ready",
            "P09_4_READINESS=schema-not-ready",
            "P09_4_READINESS=generation-not-ready",
            "P09_4_READINESS=credentials-not-ready",
        )
        for marker in required:
            self.assertIn(marker, text)
        self.assertLess(text.index("restore-cutover-*.json"), text.index("scripts/run-postgres-role-audit.sh"))
        self.assertNotIn("reconcile-postgres-roles.sh", text)
        self.assertNotIn("advance_restore_generation", text)
        self.assertNotIn("commit_restored_generation", text)

    def test_wrapper_prints_token_only_after_grant_and_generation_checks(self):
        text = WRAPPER.read_text(encoding="utf-8")
        token_print = "printf '%s\\n' \"$TOKEN\""
        self.assertIn(token_print, text)
        self.assertLess(text.index("--mode verify"), text.rindex(token_print))
        self.assertLess(text.index("--installation-fingerprint"), text.rindex(token_print))


if __name__ == "__main__":
    unittest.main()
