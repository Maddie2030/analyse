from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/test/p06-3-postgres-gate.sh"


class P063PostgresGateScriptTests(unittest.TestCase):
    def test_gate_requires_explicit_disposable_database_confirmation(self):
        self.assertTrue(SCRIPT.is_file())
        text = SCRIPT.read_text()
        self.assertIn("MREADER_TEST_POSTGRES_DSN", text)
        self.assertIn("MREADER_TEST_POSTGRES_CONFIRM", text)
        self.assertIn("disposable", text)

    def test_gate_fails_closed_without_test_dsn(self):
        env = os.environ.copy()
        env.pop("MREADER_TEST_POSTGRES_DSN", None)
        env.pop("MREADER_TEST_POSTGRES_CONFIRM", None)
        result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MREADER_TEST_POSTGRES_DSN", result.stderr + result.stdout)

    def test_gate_allows_older_launcher_when_go_toolchain_is_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            log = tmp / "go.log"
            fake_go = tmp / "go"
            fake_go.write_text("""#!/usr/bin/env bash
set -eu
if [ "${1:-}" = env ] && [ "${2:-}" = GOVERSION ]; then echo go1.23.2; exit 0; fi
if [ "${1:-}" = env ] && [ "${2:-}" = GOTOOLCHAIN ]; then echo auto; exit 0; fi
printf '%s\n' "$*" >> "$FAKE_GO_LOG"
exit 0
""")
            fake_go.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp}:{env.get('PATH','')}",
                "FAKE_GO_LOG": str(log),
                "MREADER_TEST_POSTGRES_DSN": "postgres://fixture/test",
                "MREADER_TEST_POSTGRES_CONFIRM": "disposable",
            })
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("test ./internal/store", log.read_text())

    def test_gate_runs_only_catalog_publication_transaction_suite_with_go_125(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            log = tmp / "go.log"
            fake_go = tmp / "go"
            fake_go.write_text("""#!/usr/bin/env bash\nset -eu\nif [ \"${1:-}\" = env ] && [ \"${2:-}\" = GOVERSION ]; then echo go1.25.0; exit 0; fi\nprintf '%s\\n' \"$*\" >> \"$FAKE_GO_LOG\"\nexit 0\n""")
            fake_go.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp}:{env.get('PATH','')}",
                "FAKE_GO_LOG": str(log),
                "MREADER_TEST_POSTGRES_DSN": "postgres://fixture/test",
                "MREADER_TEST_POSTGRES_CONFIRM": "disposable",
            })
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            invocation = log.read_text()
            self.assertIn("test ./internal/store", invocation)
            self.assertIn("TestCommitPublication", invocation)
            self.assertIn("TestMediaCompletionEvidenceIsDatabaseImmutable", invocation)
            self.assertIn("-count=1", invocation)

    def test_gate_supports_explicit_ephemeral_docker_mode_without_external_dsn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docker_log = tmp / "docker.log"
            fake_docker = tmp / "docker"
            fake_docker.write_text("""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [ "${1:-}" = network ] && [ "${2:-}" = create ]; then echo fake-network-id; exit 0; fi
if [ "${1:-}" = network ] && [ "${2:-}" = rm ]; then exit 0; fi
case "${1:-}" in
  run) echo fake-container-id ;;
  exec)
    if printf '%s\n' "$*" | grep -q 'psql'; then cat >/dev/null; fi
    ;;
  rm) ;;
esac
""")
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env.pop("MREADER_TEST_POSTGRES_DSN", None)
            env.pop("MREADER_TEST_POSTGRES_CONFIRM", None)
            env.update({
                "PATH": f"{tmp}:/usr/bin:/bin",
                "FAKE_DOCKER_LOG": str(docker_log),
                "MREADER_TEST_POSTGRES_MODE": "docker",
            })
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            docker_calls = docker_log.read_text()
            self.assertIn("network create", docker_calls)
            self.assertIn("postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297", docker_calls)
            self.assertIn("golang:1.25.0-alpine3.22@sha256:f18a072054848d87a8077455f0ac8a25886f2397f88bfdd222d6fafbb5bba440", docker_calls)
            self.assertIn("--tmpfs /var/lib/postgresql/data:rw", docker_calls)
            self.assertIn("pg_isready", docker_calls)
            self.assertIn("psql -X -v ON_ERROR_STOP=1", docker_calls)
            self.assertIn("go test ./internal/store", docker_calls)
            self.assertIn("TestCommitPublication", docker_calls)
            self.assertIn("TestMediaCompletionEvidenceIsDatabaseImmutable", docker_calls)
            self.assertIn("rm -f", docker_calls)
            self.assertIn("network rm", docker_calls)

    def test_docker_mode_prepares_writable_catalog_module_before_go_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            docker_log = tmp / "docker.log"
            fake_docker = tmp / "docker"
            fake_docker.write_text("""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
if [ "${1:-}" = network ] && [ "${2:-}" = create ]; then echo fake-network-id; exit 0; fi
if [ "${1:-}" = network ] && [ "${2:-}" = rm ]; then exit 0; fi
case "${1:-}" in
  run) echo fake-container-id ;;
  exec)
    if printf '%s\\n' "$*" | grep -q 'psql'; then cat >/dev/null; fi
    ;;
  rm) ;;
esac
""")
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env.pop("MREADER_TEST_POSTGRES_DSN", None)
            env.pop("MREADER_TEST_POSTGRES_CONFIRM", None)
            env.update({
                "PATH": f"{tmp}:/usr/bin:/bin",
                "FAKE_DOCKER_LOG": str(docker_log),
                "MREADER_TEST_POSTGRES_MODE": "docker",
            })
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            docker_calls = docker_log.read_text()
            self.assertIn("cp -a /workspace/services/catalog_go /tmp/catalog_go", docker_calls)
            self.assertIn("cd /tmp/catalog_go", docker_calls)
            self.assertIn("go mod tidy", docker_calls)
            self.assertIn("go mod verify", docker_calls)
            self.assertIn("go test ./internal/store", docker_calls)


    def test_gate_also_compiles_notification_publication_consumer(self):
        text = SCRIPT.read_text()
        self.assertIn('services/notification_worker', text)
        self.assertIn('go test ./internal/events ./internal/store', text)
        self.assertIn('go mod download', text)

    def test_docker_mode_rejects_external_dsn_to_avoid_ambiguous_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_go = tmp / "go"
            fake_go.write_text("""#!/usr/bin/env bash
set -eu
if [ \"${1:-}\" = env ] && [ \"${2:-}\" = GOVERSION ]; then echo go1.25.0; exit 0; fi
if [ \"${1:-}\" = env ] && [ \"${2:-}\" = GOTOOLCHAIN ]; then echo auto; exit 0; fi
exit 0
""")
            fake_go.chmod(0o755)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp}:{env.get('PATH','')}",
                "MREADER_TEST_POSTGRES_MODE": "docker",
                "MREADER_TEST_POSTGRES_DSN": "postgres://not-used/production",
                "MREADER_TEST_POSTGRES_CONFIRM": "disposable",
            })
            result = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be unset in docker mode", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
