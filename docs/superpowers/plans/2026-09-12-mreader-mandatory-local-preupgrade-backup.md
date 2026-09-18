# MReader mandatory local pre-upgrade backup implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify a complete local PostgreSQL pre-upgrade recovery bundle, and prevent migration execution when that capture fails.

**Architecture:** A host-side Bash command asks the running PostgreSQL container to create a custom-format dump and cluster globals, copies both into an operation-scoped staging directory under the already resolved recovery root, writes a versioned manifest and checksums, verifies them, and atomically publishes the bundle. `stateful-up.sh` invokes this guard for every core startup before the migration container, independently of NAS availability and `POSTGRES_BACKUP_ENABLED`.

**Tech Stack:** Bash, Docker Compose v2, PostgreSQL 16 `pg_dump`, `pg_dumpall`, `pg_restore`, SHA-256 tools, existing environment-path module; Python standard-library `unittest` for portable boundary tests.

**Spec:** `docs/superpowers/specs/2026-09-11-mreader-rc485-ownership-consolidation-design.md`, sections 8.1–8.3 and 9.1; gates PATH-01 and DBP-01.

## Global Constraints

- Preserve existing data, configuration, and authoritative volume selections.
- A failed mandatory safety capture blocks destructive schema steps even if automatic backups are disabled or NAS proof is unavailable.
- Logical bundles contain a full custom-format dump of the configured MReader database, cluster globals, manifest, and checksums.
- The recovery root is the literal `MREADER_DB_PROTECTION_ROOT` persisted by the preceding path-contract patch; never use container `$HOME` or the release extraction directory.
- Do not mount the whole host home or the Docker socket into application pods.
- This slice does not change retention, restore behavior, database roles, reading migrations, or NAS media.
- Tests use disposable directories and fake external command boundaries. An actual PostgreSQL capture remains a separate runtime gate.

---

## File and responsibility map

| File | Responsibility |
| --- | --- |
| Create `scripts/hybrid/create-local-preupgrade-backup.sh` | Capture, verify, and atomically publish one local logical recovery bundle |
| Create `tests/regression/test_local_preupgrade_backup.py` | Execute success/failure paths against a deterministic fake Docker boundary |
| Modify `scripts/hybrid/stateful-up.sh` | Require the local verified bundle before the migration profile runs |
| Modify `tests/regression/test_local_preupgrade_backup.py` | Exercise stateful startup ordering and fail-closed behavior |

## Task 1: Verified local recovery bundle

**Files:**

- Create: `scripts/hybrid/create-local-preupgrade-backup.sh`
- Create: `tests/regression/test_local_preupgrade_backup.py`

**Interfaces:**

- Consumes: optional `.env` path; persisted `MREADER_DB_PROTECTION_ROOT`; a running Compose service named `db`.
- Produces: `<root>/dumps/pre-upgrade/<recovery-id>/database.dump`, `globals.sql`, `manifest.json`, and `checksums.sha256`; stdout prints the final bundle path only after verification.
- The script exits 2 for configuration/dependency errors, 3 when PostgreSQL is not running, 4 for capture/copy/format verification errors, and 5 when no SHA-256 implementation exists. No final bundle exists on failure.

- [ ] **Step 1: Write the fake-Docker success and failure tests.**

```python
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hybrid/create-local-preupgrade-backup.sh"


class LocalPreupgradeBackupTests(unittest.TestCase):
    def run_capture(self, fail=False):
        temporary = tempfile.TemporaryDirectory(prefix="mreader-preupgrade-")
        fixture = Path(temporary.name)
        binary = fixture / "bin"
        container = fixture / "container"
        recovery = fixture / "recovery root"
        binary.mkdir()
        container.mkdir()
        env_file = fixture / ".env"
        env_file.write_text(f"MREADER_DB_PROTECTION_ROOT={recovery}\n")
        docker = binary / "docker"
        docker.write_text((ROOT / "tests/regression/fixtures/fake-preupgrade-docker.sh").read_text())
        docker.chmod(0o755)
        environment = dict(
            os.environ,
            PATH=f"{binary}:{os.environ['PATH']}",
            MREADER_DB_PROTECTION_ROOT=str(recovery),
            DBP_FAKE_CONTAINER=str(container),
            DBP_FAKE_CAPTURE_FAIL="true" if fail else "false",
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
            self.assertTrue((bundle / "globals.sql").read_text().startswith("-- PostgreSQL globals"))
            manifest = json.loads((bundle / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["type"], "logical")
            self.assertEqual(manifest["purpose"], "pre-upgrade")
            self.assertEqual(manifest["scope"], "mreader_database_plus_globals")
            self.assertEqual(manifest["verification"], "verified")
            self.assertEqual(list((recovery / "staging").iterdir()), [])

    def test_failed_capture_never_publishes_a_bundle(self):
        temporary, recovery, result = self.run_capture(fail=True)
        with temporary:
            self.assertNotEqual(result.returncode, 0)
            published = recovery / "dumps/pre-upgrade"
            self.assertEqual(list(published.iterdir()) if published.exists() else [], [])
            staging = recovery / "staging"
            self.assertEqual(list(staging.iterdir()) if staging.exists() else [], [])
```

Create `tests/regression/fixtures/fake-preupgrade-docker.sh` in this same step:

```bash
#!/usr/bin/env bash
set -euo pipefail
container="${DBP_FAKE_CONTAINER:?}"
if [[ "$1" == compose && "${*: -3}" == "ps -q db" ]]; then
  printf 'fixture-db\n'
  exit 0
fi
if [[ "$1" == exec && "$2" == fixture-db && "$3" == sh ]]; then
  [[ "${DBP_FAKE_CAPTURE_FAIL:-false}" != true ]] || exit 41
  dump="${@: -3:1}"; globals="${@: -2:1}"; metadata="${@: -1:1}"
  printf 'PGDMP-fixture\n' > "$container/$(basename "$dump")"
  printf '%s\n' '-- PostgreSQL globals fixture' > "$container/$(basename "$globals")"
  printf '%s\n' '160010' 'mreader' > "$container/$(basename "$metadata")"
  exit 0
fi
if [[ "$1" == cp ]]; then
  source_path="${2#fixture-db:}"
  cp "$container/$(basename "$source_path")" "$3"
  exit 0
fi
if [[ "$1" == exec && "$2" == fixture-db && "$3" == rm ]]; then
  shift 3
  for path in "$@"; do rm -f "$container/$(basename "$path")"; done
  exit 0
fi
exit 64
```

- [ ] **Step 2: Run the tests and observe the missing-script failure.**

Run `python3 tests/regression/test_local_preupgrade_backup.py -v`.
Expected: both tests fail because the capture script does not exist; the failure test must not pass merely because nothing was attempted.

- [ ] **Step 3: Implement the capture script.**

The script must use `set -euo pipefail`, `umask 077`, the shared resolver, an operation-specific staging directory, container-side `pg_dump -Fc`, `pg_dumpall --globals-only`, and `pg_restore --list`. It must copy the three container outputs, require `PGDMP` magic, validate the metadata as `<server_version_num>` plus `<database_name>`, write this exact manifest shape, hash all three artifacts, verify the hash file, then rename staging to final:

```json
{
  "schema_version": 1,
  "recovery_id": "preupgrade-<UTC timestamp>-<pid>",
  "type": "logical",
  "purpose": "pre-upgrade",
  "scope": "mreader_database_plus_globals",
  "database": "<validated database name>",
  "postgres_major": 16,
  "mreader_version": "<VERSION or unknown>",
  "created_at": "<RFC3339 UTC>",
  "verification": "verified",
  "files": ["database.dump", "globals.sql"],
  "checksums_file": "checksums.sha256"
}
```

Use a trap to delete only the explicit operation staging directory and operation-owned `/tmp/<recovery-id>.*` container files. Never recursively delete the recovery root. Final publication is `mv "$staging" "$final"` within the same filesystem and must fail if `$final` already exists.

- [ ] **Step 4: Verify portable behavior.**

```bash
python3 tests/regression/test_local_preupgrade_backup.py -v
bash -n scripts/hybrid/create-local-preupgrade-backup.sh tests/regression/fixtures/fake-preupgrade-docker.sh
git diff --check
```

Expected: 2 tests pass; syntax and whitespace checks exit 0.

- [ ] **Step 5: Commit task 1.**

```bash
git add scripts/hybrid/create-local-preupgrade-backup.sh tests/regression/test_local_preupgrade_backup.py tests/regression/fixtures/fake-preupgrade-docker.sh
git commit -m "feat: create verified local pre-upgrade recovery bundle"
```

## Task 2: Fail-closed migration ordering

**Files:**

- Modify: `scripts/hybrid/stateful-up.sh`
- Modify: `tests/regression/test_local_preupgrade_backup.py`

**Interfaces:**

- Consumes: task 1 capture command.
- Produces: core startup runs capture after PostgreSQL/replication setup and before any `--profile migration` command. Capture failure returns the same nonzero status and migration is not invoked. The guard is unconditional with respect to NAS and `POSTGRES_BACKUP_ENABLED`.

- [ ] **Step 1: Add behavioral ordering tests.**

```python
    def test_stateful_startup_captures_before_migration_even_when_automatic_backup_disabled(self):
        result, actions = run_stateful_fixture(capture_status=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(actions.index("local-capture"), actions.index("migration"))

    def test_stateful_startup_blocks_migration_when_capture_fails(self):
        result, actions = run_stateful_fixture(capture_status=42)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn("local-capture", actions)
        self.assertNotIn("migration", actions)
```

`run_stateful_fixture` copies `stateful-up.sh` plus the environment helpers into a disposable app; supplies `.env` with `POSTGRES_BACKUP_ENABLED=false`; replaces `configure-replication.sh` and `create-local-preupgrade-backup.sh` with boundary scripts that append `replication`/`local-capture`; and supplies a fake `docker` that appends `migration` only when its arguments contain `--profile migration`.

- [ ] **Step 2: Observe the ordering failure.**

Run `python3 tests/regression/test_local_preupgrade_backup.py -v`.
Expected: the two new tests fail because `stateful-up.sh` does not call the local capture command.

- [ ] **Step 3: Add the mandatory guard immediately after replication setup.**

```bash
echo "Creating verified local pre-upgrade PostgreSQL recovery bundle..."
set +e
"$ROOT/scripts/hybrid/create-local-preupgrade-backup.sh" .env
local_preupgrade_rc=$?
set -e
if [[ "$local_preupgrade_rc" -ne 0 ]]; then
  echo "ERROR: mandatory local pre-upgrade recovery capture failed (exit=$local_preupgrade_rc); migrations were not run." >&2
  exit "$local_preupgrade_rc"
fi
```

This block precedes `backup_enabled` evaluation and every NAS self-test/pre-upgrade request. It does not replace optional NAS protection; it guarantees a local recovery point before migration.

- [ ] **Step 4: Run the focused and existing ordering suites.**

```bash
python3 tests/regression/test_local_preupgrade_backup.py -v
bash tests/regression/hybrid-preupgrade-backup-order.sh
bash tests/regression/bootstrap-fresh-env.sh
bash -n scripts/hybrid/stateful-up.sh scripts/hybrid/create-local-preupgrade-backup.sh
git diff --check
```

Expected: 4 tests and both existing shell regressions pass; syntax and whitespace exit 0. These portable tests do not qualify DBP-01's actual PostgreSQL capture.

- [ ] **Step 5: Commit task 2.**

```bash
git add scripts/hybrid/stateful-up.sh tests/regression/test_local_preupgrade_backup.py
git commit -m "fix: block migrations when local recovery capture fails"
```

## Self-review and execution choice

- The plan covers the local pre-upgrade bundle and fail-closed ordering only.
- Function/file names and paths are consistent across both tasks.
- Incomplete bundles remain in operation-owned staging only during execution and are removed on failure; final bundles are published only after verification.
- No retention deletion, restore action, schema change, live backup, NAS modification, or broad filesystem deletion is included.
- Inline execution was already selected for the parent RC4.85 work; continue inline with the required execution and TDD skills.
