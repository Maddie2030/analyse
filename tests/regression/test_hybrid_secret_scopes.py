import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "docker-desktop-hybrid"
SCOPE_DIR = DEPLOY / "env-scopes"
RENDERER = ROOT / "scripts" / "hybrid" / "render-workload-env.sh"


def deployment_secret_refs(path: Path):
    out = {}
    for raw_doc in path.read_text().split("\n---"):
        if not re.search(r"(?m)^kind:\s*Deployment\s*$", raw_doc):
            continue
        name_match = re.search(
            r"(?ms)^metadata:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+name:\s*([^\s#]+)",
            raw_doc,
        )
        if not name_match:
            continue
        name = name_match.group(1)
        refs = re.findall(
            r"(?ms)^[ \t]+- secretRef:\s*\n[ \t]+name:\s*([^\s#]+)",
            raw_doc,
        )
        out[name] = refs
    return out


class HybridSecretScopeTests(unittest.TestCase):
    def test_renderer_copies_only_allowlisted_keys_and_preserves_values(self):
        self.assertTrue(RENDERER.is_file(), "workload env renderer must exist")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / ".env"
            keys = td / "scope.keys"
            output = td / "selected.env"
            source.write_text(
                "DATABASE_URL=postgresql://u:p@db:5432/app?x=1&y=2\n"
                "RABBITMQ_PASSWORD=p@ss/with:punctuation\n"
                "CATALOG_INTERNAL_TOKEN=future-private-catalog-token\n"
                "RECOVERY_BRIDGE_TOKEN=future-private-recovery-token\n"
                "UNRELATED_SECRET=must-not-leak\n"
                "EMPTY_ALLOWED=\n"
            )
            keys.write_text(
                "# exact key allowlist\n"
                "DATABASE_URL\n"
                "RABBITMQ_PASSWORD\n"
                "EMPTY_ALLOWED\n"
            )
            subprocess.run(
                ["bash", str(RENDERER), str(source), str(keys), str(output)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                output.read_text().splitlines(),
                [
                    "DATABASE_URL=postgresql://u:p@db:5432/app?x=1&y=2",
                    "RABBITMQ_PASSWORD=p@ss/with:punctuation",
                    "EMPTY_ALLOWED=",
                ],
            )

    def test_renderer_rejects_invalid_or_duplicate_scope_keys(self):
        self.assertTrue(RENDERER.is_file(), "workload env renderer must exist")
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / ".env"
            source.write_text("DATABASE_URL=x\n")
            for payload in ("DATABASE_URL\nDATABASE_URL\n", "DATABASE_URL\nBAD-KEY\n"):
                keys = td / "scope.keys"
                output = td / "selected.env"
                keys.write_text(payload)
                result = subprocess.run(
                    ["bash", str(RENDERER), str(source), str(keys), str(output)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_every_secret_consuming_deployment_uses_its_own_scope(self):
        refs = {}
        refs.update(deployment_secret_refs(DEPLOY / "user-apps.yaml"))
        refs.update(deployment_secret_refs(DEPLOY / "admin-apps.yaml"))
        self.assertTrue(refs)
        for workload, secret_refs in refs.items():
            if workload in {"user-gateway", "admin-gateway"}:
                self.assertEqual(secret_refs, [])
                continue
            expected = f"mreader-env-{workload}"
            self.assertEqual(
                secret_refs,
                [expected],
                f"{workload} must consume only its workload-scoped secret",
            )
            self.assertTrue(
                (SCOPE_DIR / f"{workload}.keys").is_file(),
                f"missing scope file for {workload}",
            )

    def test_frontends_and_browser_do_not_receive_backend_credentials(self):
        forbidden = {
            "DATABASE_URL",
            "POSTGRES_PASSWORD",
            "RABBITMQ_URL",
            "RABBITMQ_PASSWORD",
            "TOKEN_SECRET",
            "TURNSTILE_SECRET",
            "CLOUDFLARE_API_TOKEN",
            "GCORE_API_TOKEN",
            "POSTGRES_BACKUP_REPLICATION_PASSWORD",
            "CATALOG_INTERNAL_TOKEN",
            "RECOVERY_BRIDGE_TOKEN",
        }
        for workload in ("frontend", "admin-frontend", "scraper-browser"):
            scope = SCOPE_DIR / f"{workload}.keys"
            self.assertTrue(scope.is_file())
            keys = {
                line.strip()
                for line in scope.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
            self.assertFalse(keys & forbidden, f"{workload} leaks {sorted(keys & forbidden)}")

    def test_keda_target_scopes_contain_every_from_env_key(self):
        for filename in ("user-keda.yaml", "admin-keda.yaml"):
            path = DEPLOY / filename
            for raw_doc in path.read_text().split("\n---"):
                if not re.search(r"(?m)^kind:\s*ScaledObject\s*$", raw_doc):
                    continue
                target_match = re.search(
                    r"(?ms)^  scaleTargetRef:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+name:\s*([^\s#]+)",
                    raw_doc,
                )
                self.assertIsNotNone(target_match, f"missing scaleTargetRef in {filename}")
                target = target_match.group(1)
                required = set(re.findall(r"(?m)^\s+(?:host|username|password|connection)FromEnv:\s*([^\s#]+)", raw_doc))
                scope = SCOPE_DIR / f"{target}.keys"
                self.assertTrue(scope.is_file(), f"missing KEDA target scope {scope.name}")
                keys = {
                    line.strip()
                    for line in scope.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                }
                self.assertTrue(
                    required <= keys,
                    f"{target} KEDA env missing from scope: {sorted(required - keys)}",
                )


    def test_legacy_namespace_wide_secret_is_removed_after_scoped_rollout(self):
        text = (ROOT / "scripts" / "hybrid" / "deploy.sh").read_text()
        self.assertIn('kubectl -n mreader-user delete secret mreader-env --ignore-not-found', text)
        self.assertIn('kubectl -n mreader-admin delete secret mreader-env --ignore-not-found', text)

    def test_deploy_no_longer_copies_the_whole_dotenv(self):
        text = (ROOT / "scripts" / "hybrid" / "deploy.sh").read_text()
        forbidden_literals = ('cp .env "$user_env"', 'cp .env "$admin_env"')
        violations = [item for item in forbidden_literals if item in text]
        if re.search(r"--from-env-file=\"\$(?:user_env|admin_env)\"", text):
            violations.append("namespace-wide --from-env-file")
        if "render-workload-env.sh" not in text:
            violations.append("missing workload renderer")
        self.assertEqual(violations, [])


class P093HybridDatabaseScopeTests(unittest.TestCase):
    def test_deploy_projects_role_specific_dsns_and_dedicated_keda_identity(self):
        text = (ROOT / "scripts" / "hybrid" / "deploy.sh").read_text(encoding="utf-8")
        required = (
            "MREADER_DB_DSN_",
            "postgres-roles.v1.json",
            'set_if_scoped "$file" "$scope" "$dsn_env" "$workload_db_dsn"',
            "MREADER_DB_DSN_MREADER_KEDA_METRICS",
            'set_if_scoped "$file" "$scope" KEDA_POSTGRES_URL "$keda_pg"',
        )
        missing = [marker for marker in required if marker not in text]
        self.assertEqual([], missing)
        self.assertNotIn('DATABASE_URL="$(dotenv_get DATABASE_URL)"', text)
        self.assertNotRegex(text, r'keda_pg=.*\$DATABASE_URL')


if __name__ == "__main__":
    unittest.main()
