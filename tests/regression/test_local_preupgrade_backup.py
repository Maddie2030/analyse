import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hybrid/create-local-preupgrade-backup.sh"


class LocalPreupgradeBackupTests(unittest.TestCase):
    def run_capture(
        self,
        fail=False,
        corrupt_copy=False,
        require_no_pathconv=False,
        no_host_jq=False,
        mingw_host_paths=False,
    ):
        temporary = tempfile.TemporaryDirectory(prefix="mreader-preupgrade-")
        fixture = Path(temporary.name)
        binary = fixture / "bin"
        container = fixture / "container"
        recovery = fixture / "recovery root"
        binary.mkdir()
        container.mkdir()
        host_path = os.environ["PATH"]
        if no_host_jq:
            hostbin = fixture / "hostbin"
            hostbin.mkdir()
            seen = set()
            for directory in [Path("/usr/bin"), Path("/bin")]:
                if not directory.is_dir():
                    continue
                for source in directory.iterdir():
                    if source.name == "jq" or source.name in seen or not os.access(source, os.X_OK):
                        continue
                    seen.add(source.name)
                    try:
                        (hostbin / source.name).symlink_to(source)
                    except FileExistsError:
                        pass
            host_path = str(hostbin)
        env_file = fixture / ".env"
        env_file.write_text(f"MREADER_DB_PROTECTION_ROOT={recovery}\n")
        docker = binary / "docker"
        docker.write_text(
            (ROOT / "tests/regression/fixtures/fake-preupgrade-docker.sh").read_text()
        )
        docker.chmod(0o755)
        if mingw_host_paths:
            cygpath = binary / "cygpath"
            cygpath.write_text(
                "#!/usr/bin/env bash\n"
                "[[ \"$1\" == -m ]] || exit 64\n"
                "value=\"$2\"\n"
                "printf 'C:/translated%s\\n' \"$value\"\n"
            )
            cygpath.chmod(0o755)
        environment = dict(
            os.environ,
            PATH=f"{binary}:{host_path}",
            MREADER_DB_PROTECTION_ROOT=str(recovery),
            DBP_FAKE_CONTAINER=str(container),
            DBP_FAKE_CAPTURE_FAIL="true" if fail else "false",
            DBP_FAKE_CORRUPT_COPY="true" if corrupt_copy else "false",
            DBP_FAKE_REQUIRE_NO_PATHCONV="true" if require_no_pathconv else "false",
            DBP_FAKE_REQUIRE_NATIVE_COMPOSE_PATHS="true" if mingw_host_paths else "false",
            MSYSTEM="MINGW64" if mingw_host_paths else os.environ.get("MSYSTEM", ""),
        )
        result = subprocess.run(
            ["bash", str(SCRIPT), str(env_file)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        return temporary, recovery, result

    def test_publishes_only_a_complete_verified_bundle(self):
        temporary, recovery, result = self.run_capture()
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)
            bundles = list((recovery / "dumps/pre-upgrade").iterdir())
            self.assertEqual(len(bundles), 1)
            bundle = bundles[0]
            self.assertEqual((bundle / "database.dump").read_bytes()[:5], b"PGDMP")
            self.assertTrue(
                (bundle / "globals.sql")
                .read_text()
                .startswith("-- PostgreSQL globals")
            )
            manifest = json.loads((bundle / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["type"], "logical")
            self.assertEqual(manifest["purpose"], "pre-upgrade")
            self.assertEqual(manifest["scope"], "mreader_database_plus_globals")
            self.assertEqual(manifest["database"], "mreader")
            self.assertEqual(manifest["postgres_major"], 16)
            self.assertEqual(manifest["verification"], "verified")
            self.assertEqual(list((recovery / "staging").iterdir()), [])
            verify = subprocess.run(
                ["sha256sum", "-c", "checksums.sha256"],
                cwd=bundle,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_failed_capture_never_publishes_a_bundle(self):
        temporary, recovery, result = self.run_capture(fail=True)
        with temporary:
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertIn("PostgreSQL capture failed", result.stderr)
            published = recovery / "dumps/pre-upgrade"
            self.assertEqual(list(published.iterdir()) if published.exists() else [], [])
            staging = recovery / "staging"
            self.assertEqual(list(staging.iterdir()) if staging.exists() else [], [])

    def test_copy_corruption_never_publishes_a_bundle(self):
        temporary, recovery, result = self.run_capture(corrupt_copy=True)
        with temporary:
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertIn("source checksum", result.stderr)
            published = recovery / "dumps/pre-upgrade"
            self.assertEqual(list(published.iterdir()) if published.exists() else [], [])

    def test_container_tmp_paths_disable_msys_argument_conversion(self):
        temporary, recovery, result = self.run_capture(require_no_pathconv=True)
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_host_jq_uses_backup_agent_recovery_store(self):
        temporary, recovery, result = self.run_capture(no_host_jq=True, require_no_pathconv=True)
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)
            bundles = list((recovery / "dumps/pre-upgrade").iterdir())
            self.assertEqual(len(bundles), 1)
            self.assertNotIn("required recovery-store tool is missing: jq", result.stderr)

    def test_mingw_fallback_preconverts_host_paths_while_preserving_container_paths(self):
        temporary, recovery, result = self.run_capture(
            no_host_jq=True,
            require_no_pathconv=True,
            mingw_host_paths=True,
        )
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)
            bundles = list((recovery / "dumps/pre-upgrade").iterdir())
            self.assertEqual(len(bundles), 1)


def run_stateful_fixture(capture_status):
    temporary = tempfile.TemporaryDirectory(prefix="mreader-stateful-")
    fixture = Path(temporary.name)
    app = fixture / "app"
    actions = fixture / "actions.log"
    (app / "scripts/hybrid").mkdir(parents=True)
    (app / "scripts/env").mkdir(parents=True)
    (fixture / "bin").mkdir()
    shutil.copy(ROOT / "scripts/hybrid/stateful-up.sh", app / "scripts/hybrid")
    shutil.copy(ROOT / "scripts/hybrid/quiesce-before-migration.sh", app / "scripts/hybrid")
    for name in [
        "env-lib.sh",
        "db-protection-root.sh",
        "resolve-db-protection-root.sh",
    ]:
        shutil.copy(ROOT / f"scripts/env/{name}", app / f"scripts/env/{name}")
    (app / ".env").write_text(
        f"MREADER_DB_PROTECTION_ROOT={fixture / 'recovery'}\n"
        "POSTGRES_BACKUP_ENABLED=false\n"
    )
    configure = app / "scripts/backup/configure-replication.sh"
    configure.parent.mkdir(parents=True)
    configure.write_text(
        "#!/usr/bin/env bash\n"
        'printf "replication\\n" >> "$DBP_TEST_ACTIONS"\n'
    )
    configure.chmod(0o755)
    capture = app / "scripts/hybrid/create-local-preupgrade-backup.sh"
    capture.write_text(
        "#!/usr/bin/env bash\n"
        'printf "local-capture\\n" >> "$DBP_TEST_ACTIONS"\n'
        f"exit {capture_status}\n"
    )
    capture.chmod(0o755)
    reconcile = app / "scripts/hybrid/reconcile-postgres-roles.sh"
    reconcile.write_text(
        "#!/usr/bin/env bash\n"
        'printf "role-reconcile\\n" >> "$DBP_TEST_ACTIONS"\n'
    )
    reconcile.chmod(0o755)
    docker = fixture / "bin/docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"--profile migration"* ]]; then '
        'printf "migration\\n" >> "$DBP_TEST_ACTIONS"; fi\n'
        "exit 0\n"
    )
    docker.chmod(0o755)
    kubectl = fixture / "bin/kubectl"
    kubectl.write_text(
        "#!/usr/bin/env bash\n"
        "# The stateful-ordering fixture represents a fresh install with no MReader namespaces.\n"
        "if [[ \"$1 $2 $3\" == \"get namespace mreader-user\" || \"$1 $2 $3\" == \"get namespace mreader-admin\" ]]; then exit 1; fi\n"
        "exit 0\n"
    )
    kubectl.chmod(0o755)
    environment = dict(
        os.environ,
        PATH=f"{fixture / 'bin'}:{os.environ['PATH']}",
        DBP_TEST_ACTIONS=str(actions),
        MREADER_DB_PROTECTION_ROOT="",
    )
    result = subprocess.run(
        ["bash", str(app / "scripts/hybrid/stateful-up.sh"), "core"],
        cwd=app,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    recorded = actions.read_text().splitlines() if actions.exists() else []
    return temporary, result, recorded


class StatefulOrderingTests(unittest.TestCase):
    def test_captures_before_migration_when_automatic_backup_is_disabled(self):
        temporary, result, actions = run_stateful_fixture(capture_status=0)
        with temporary:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(actions.index("local-capture"), actions.index("migration"))

    def test_capture_failure_blocks_migration(self):
        temporary, result, actions = run_stateful_fixture(capture_status=42)
        with temporary:
            self.assertEqual(result.returncode, 42, result.stderr)
            self.assertIn("local-capture", actions)
            self.assertNotIn("migration", actions)


if __name__ == "__main__":
    unittest.main()
