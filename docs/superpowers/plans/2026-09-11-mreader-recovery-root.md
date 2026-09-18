# MReader canonical recovery-root implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one literal, persistent host recovery-root setting before changing backup storage or retiring tables.

**Architecture:** A small shared Bash module resolves and validates the path; a CLI persists it using the existing bounded environment helpers. All three startup entry points call that CLI. This patch does not create recovery directories, move backups, change retention, run migrations, or change the restore engine.

**Tech Stack:** Bash, existing `env-lib.sh`, Python standard-library `unittest` for portable subprocess tests; no new production dependency.

**Spec:** `docs/superpowers/specs/2026-09-11-mreader-rc485-ownership-consolidation-design.md`, especially sections 8.1, 9.1 and PATH-01. The user's “continue” approves the written specification, including section 4.4's local-first reading contract.

## Global Constraints

- Preserve existing data, configuration, and authoritative volume selections. Removing duplicate code is not authority to reset storage.
- No live production restore or destructive migration is executed merely to test this release. Use isolated fixtures and explicit operator procedures.
- Keep the public gateway separate from the private admin gateway. Preserve both configured development-edge options; expose only the gateway.
- Retain KEDA/HPA and the existing resource limits. Browser scraping remains on demand. Do not introduce Azure deployment changes in this release.
- Use `MREADER_DB_PROTECTION_ROOT`, resolved once by bootstrap from the actual host user's home and persisted explicitly. Never derive it from the backup container's home or the current ZIP extraction directory.
- An explicit existing configuration takes precedence. If the intended host user cannot be resolved reliably, stop setup with a clear path requirement.
- Static checks and runtime tests have separate result categories.

---

## Scope and sequence

This is **implementation slice 1A**, not an implementation plan for the entire RC4.85 release. It produces an independently testable configuration contract. Do not label PATH-01 or DB Protection fully passed because these unit tests pass.

| Subsequent slice | Required result before completion |
| --- | --- |
| 1B — upgrade protection | Preserve installation identity; detect PostgreSQL-major/volume ambiguity; quiesce writers; produce a verified full local dump plus globals before schema changes; failed capture blocks migration independently of NAS proof/automatic-backup settings |
| 1C — migration continuity | Ordered pre-047/048 evidence preservation plus forward repair using the actual migration runner; no guessed lost history or invented completion |
| 2A — Progress | One PostgreSQL transaction for ledger/checkpoint/outbox; revision/session/sequence ordering; one `reading_state_v1`; no Redis write-behind acknowledgement |
| 2B — Web and Android | One account/origin-scoped snapshot and pending-command repository; immediate local display, conditional acknowledgement, bounded background retry; one Library response and restored Recently Opened |
| 3 — DB Protection | Validated home-root mounts/ACLs, complete recovery bundles, inventory/opaque IDs, 4-day dump and 2-day snapshot retention, one operation queue, actual dump/snapshot drill and interruption-safe restore rehearsal |
| 4 — publishing/lifecycle | Catalog-only production writes, idempotency receipts, ingestion status ownership, exact-object cleanup and cancellation reconciliation |
| 5 — qualification | Enforced database roles, route/client contracts, real builds/runtime tests, constrained resources, capability checklist, release packaging |

The details of those slices belong in their own reviewed plans before implementation. No deletion of legacy tables is authorized by completion of slice 1A. The approved spec remains the coverage ledger for the entire release.

### Source and working-tree rules

- Start a new isolated source workspace from the supplied r5 tree; preserve `audit/` and the original ZIPs unchanged.
- r5 archive SHA-256: `ab48e524e80c803913a992a3c46f2e936a4bcf238c43ada3975de79227885376`.
- Copy this plan and its spec into the source workspace so an executor does not need the prior conversation.
- Record baseline commit and execute the targeted baseline tests before edits. Keep this an unreleased patch; do not relabel all RC4.84 references as RC4.85 yet.
- Tests may create disposable files through their fixtures. They must not change the real host user's home, `.env`, Docker volumes, or database.

## File and responsibility map

| File | Responsibility |
| --- | --- |
| Create `scripts/env/db-protection-root.sh` | Pure path normalization plus literal config selection/persistence |
| Create `scripts/env/resolve-db-protection-root.sh` | Actual host-platform detection and CLI boundary |
| Modify `scripts/bootstrap.sh` | Resolve after `.env` exists, before volume adoption |
| Modify `scripts/hybrid-up.sh` | Resolve after existing environment preparation, before Docker work |
| Modify `scripts/hybrid/stateful-up.sh` | Resolve before direct stateful startup can bypass higher-level launchers |
| Modify `.env.example` | Declare blank root; explain host defaults and existing-storage limitation |
| Create `tests/regression/test_db_protection_root.py` | Exercise functions/CLI in disposable fixtures without Docker |
| Modify `tests/regression/bootstrap-fresh-env.sh` | Supply the new dependency and assert the root is persisted |

## Task 1: Deterministic, side-effect-free path normalization

**Files:**

- Create: `scripts/env/db-protection-root.sh`
- Create: `tests/regression/test_db_protection_root.py`

**Interfaces:**

- Consumes: `platform` equal to `linux` or `windows`, host-home string, Windows user-profile string, optional configured-path string.
- Produces: `dbp_normalize_root(platform, host_home, user_profile, configured_root)` as a Bash function: exactly one normalized path on stdout and exit 0; safe message on stderr and exit 2 on invalid input. It performs no filesystem writes and does not use `eval` or source environment files.
- Linux paths are absolute POSIX paths. Windows paths are drive-qualified paths normalized to forward slashes. UNC/device paths and shell/dotenv interpolation are explicitly unsupported and rejected, not guessed.

- [ ] **Step 1: Add executable failing tests.**

```python
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/env/db-protection-root.sh"
CLI = ROOT / "scripts/env/resolve-db-protection-root.sh"


class RootTests(unittest.TestCase):
    def normalize(self, platform, home, profile="", configured=""):
        return subprocess.run(
            ["bash", "-c", 'source "$1"\ndbp_normalize_root "$2" "$3" "$4" "$5"',
             "dbp-test", str(MODULE), platform, home, profile, configured],
            text=True, capture_output=True, check=False,
        )

    def test_linux_home_with_spaces(self):
        result = self.normalize("linux", "/home/Reader One")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/home/Reader One/.mreader/database-protection")

    def test_windows_profile_not_git_bash_home(self):
        result = self.normalize("windows", "/c/git-bash-home", r"C:\Users\Reader One")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "C:/Users/Reader One/.mreader/database-protection")

    def test_existing_path_is_not_rederived(self):
        result = self.normalize("linux", "/home/new-user", configured="/srv/mreader recovery/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/srv/mreader recovery")

    def test_quoted_literal_is_supported(self):
        result = self.normalize("linux", "/home/a", configured="'/srv/reader backups'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/srv/reader backups")

    def test_unsafe_or_ambiguous_paths_fail(self):
        values = ["relative/backups", "/", "/home/a", "/srv/../etc", "/srv/./data",
                  "/srv//data", "$HOME/backups", "$(touch /tmp/no)", "/srv/a#b",
                  "/srv/a\nb", "/srv/a\tb", "/srv/a`id`", r"/srv/a\b", "https://example/backups"]
        for value in values:
            with self.subTest(value=value):
                result = self.normalize("linux", "/home/a", configured=value)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_windows_requires_profile_and_drive(self):
        for profile, configured in [("", ""), (r"C:\Users\a", "C:/"),
                                     (r"C:\Users\a", "//server/share"),
                                     (r"C:\Users\a", "/c/backups")]:
            with self.subTest(profile=profile, configured=configured):
                result = self.normalize("windows", "/c/a", profile, configured)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_windows_whole_home_is_rejected_case_insensitively(self):
        result = self.normalize("windows", "/c/git-home", r"c:\Users\Reader", "C:/users/reader")
        self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Demonstrate the missing-contract failure.**

Run `python3 tests/regression/test_db_protection_root.py -v`.
Expected: nonzero; the normalization function/module does not exist. Do not turn the missing implementation into a skipped test.

- [ ] **Step 3: Implement the pure normalizer.**

```bash
#!/usr/bin/env bash
# Sourced by the CLI and portable tests; never source the user's .env.

dbp_error() {
  printf 'ERROR: %s\n' "$1" >&2
  return 2
}

dbp_normalize_root() {
  local platform="$1" host_home="$2" profile="$3" value="${4:-}"
  local default_home compare_value compare_home
  case "$platform" in
    linux) default_home="$host_home" ;;
    windows) default_home="${profile//\\//}" ;;
    *) dbp_error 'Unsupported host platform; use Linux or Windows/Git Bash.'; return 2 ;;
  esac
  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]] ||
       [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  if [[ -z "$value" ]]; then
    [[ -n "$default_home" ]] || { dbp_error 'Host home is unknown; set MREADER_DB_PROTECTION_ROOT explicitly.'; return 2; }
    value="${default_home%/}/.mreader/database-protection"
  fi
  [[ "$platform" != windows ]] || value="${value//\\//}"
  if [[ ${#value} -gt 4096 || "$value" =~ [[:cntrl:]] ||
        "$value" == *'$'* || "$value" == *'`'* || "$value" == *'#'* ||
        "$value" == *"'"* || "$value" == *'"'* || "$value" == *'\'* ||
        "$value" == ' '* || "$value" == *' ' ]]; then
    dbp_error 'Recovery root must be a bounded literal path without interpolation or control characters.'
    return 2
  fi
  [[ "$value" == / ]] || value="${value%/}"
  if [[ "$value" == *'//'* || "/$value/" == *'/../'* || "/$value/" == *'/./'* ]]; then
    dbp_error 'Recovery root must not contain traversal, repeated separators, or UNC syntax.'
    return 2
  fi
  if [[ "$platform" == windows ]]; then
    [[ "$value" =~ ^[A-Za-z]:/[^:]+$ ]] || { dbp_error 'Use an absolute Windows drive path, such as C:/Users/name/.mreader/database-protection.'; return 2; }
    value="$(printf '%s' "${value:0:1}" | tr '[:lower:]' '[:upper:]')${value:1}"
  else
    [[ "$value" == /* && "$value" != *:* ]] || { dbp_error 'Use an absolute Linux recovery path.'; return 2; }
  fi
  case "$value" in
    /|/home|/root|/Users|/tmp|/var|/srv|[A-Za-z]:/[Uu][Ss][Ee][Rr][Ss])
      dbp_error 'Choose a dedicated recovery directory, not a broad system directory.'; return 2 ;;
  esac
  compare_value="$value"
  compare_home="${default_home%/}"
  if [[ "$platform" == windows ]]; then
    compare_value="$(printf '%s' "$compare_value" | tr '[:upper:]' '[:lower:]')"
    compare_home="$(printf '%s' "$compare_home" | tr '[:upper:]' '[:lower:]')"
  fi
  if [[ "$compare_value" == "$compare_home" || "$value" == "${host_home%/}" ]]; then
    dbp_error 'Choose a dedicated recovery directory, not the entire user home.'
    return 2
  fi
  printf '%s\n' "$value"
}
```

The string checks are deliberate constraints for this literal `.env` contract. Do not add shell expansion to support rejected paths. Filesystem permissions, symlink containment and actual Docker path conversion are slice 1B/3 checks, not established by normalization.

- [ ] **Step 4: Run the unit tests and shell syntax check.**

```bash
python3 tests/regression/test_db_protection_root.py -v
bash -n scripts/env/db-protection-root.sh
```

Expected: 7 passing tests and shell exit 0. Add a regression for any additional edge case discovered while implementing; never hide a failing assertion by weakening path safety.

- [ ] **Step 5: Commit only this task's files.**

```bash
git add scripts/env/db-protection-root.sh tests/regression/test_db_protection_root.py
git commit -m "feat: define literal host recovery-root contract"
```

## Task 2: Persistent selection and CLI

**Files:**

- Modify: `scripts/env/db-protection-root.sh`
- Create: `scripts/env/resolve-db-protection-root.sh`
- Modify: `tests/regression/test_db_protection_root.py`

**Interfaces:**

- Consumes: `dbp_normalize_root` from task 1; `_env_size`, `env_get`, `env_set`, `MREADER_ENV_MAX_BYTES` from existing `scripts/env/env-lib.sh`.
- Produces: `dbp_resolve_env(env_file, platform, host_home, user_profile, environment_override)`, which returns/persists the chosen literal path or exits 2 without changing the file. Existing nonblank config wins; a conflicting process override is an error, since Compose would otherwise override the persisted value silently.
- Produces: `bash scripts/env/resolve-db-protection-root.sh [ENV_FILE]`, default `.env`; stdout is only the resulting root. No recovery directories are created by this command.

- [ ] **Step 1: Extend the test module before implementation.**

Insert this class before the `unittest.main()` guard:

```python
class PersistenceTests(unittest.TestCase):
    def resolve(self, env_file, home="/home/Reader One", override=""):
        script = ('source "$1/scripts/env/env-lib.sh"\n'
                  'source "$1/scripts/env/db-protection-root.sh"\n'
                  'dbp_resolve_env "$2" linux "$3" "" "$4"')
        return subprocess.run(
            ["bash", "-c", script, "dbp-test", str(ROOT), str(env_file), home, override],
            text=True, capture_output=True, check=False,
        )

    def test_persists_once_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            path.write_text("TOKEN_SECRET=fixture-not-a-real-secret\nMREADER_DB_PROTECTION_ROOT=\n")
            first = self.resolve(path)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = path.read_bytes()
            second = self.resolve(path, home="/home/different")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout, first.stdout)
            self.assertEqual(path.read_bytes(), saved)
            self.assertIn(b"TOKEN_SECRET=fixture-not-a-real-secret\n", saved)
            self.assertEqual(saved.count(b"MREADER_DB_PROTECTION_ROOT="), 1)

    def test_override_cannot_silently_replace_existing_root(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = b"MREADER_DB_PROTECTION_ROOT=/srv/reader-backups\n"
            path.write_bytes(original)
            result = self.resolve(path, override="/srv/other-backups")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_config_is_not_replaced_with_a_default(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = b"MREADER_DB_PROTECTION_ROOT=relative/unsafe\n"
            path.write_bytes(original)
            result = self.resolve(path)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_roots_require_explicit_resolution(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = (b"MREADER_DB_PROTECTION_ROOT=/srv/first\n"
                        b"MREADER_DB_PROTECTION_ROOT=/srv/second\n")
            path.write_bytes(original)
            result = self.resolve(path)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_cli_uses_explicit_temp_root_without_creating_directories(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            recovery = Path(directory) / "recovery with spaces"
            path.write_text("TOKEN_SECRET=fixture\n")
            child_env = dict(os.environ, MREADER_DB_PROTECTION_ROOT=str(recovery))
            result = subprocess.run(["bash", str(CLI), str(path)], env=child_env,
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(recovery))
            self.assertFalse(recovery.exists())
```

- [ ] **Step 2: Run the new failure cases.**

Run `python3 tests/regression/test_db_protection_root.py PersistenceTests -v`.
Expected: missing `dbp_resolve_env`/CLI failures. Existing task 1 tests must still pass.

- [ ] **Step 3: Append persistent selection to the module.**

```bash
dbp_resolve_env() {
  local file="$1" platform="$2" host_home="$3" profile="$4" override="${5:-}"
  local size assignments configured selected normalized_override
  [[ -f "$file" && ! -L "$file" ]] || { dbp_error 'A regular, non-symlink environment file is required.'; return 2; }
  size="$(_env_size "$file")" || return 2
  [[ "$size" =~ ^[0-9]+$ && "$size" -le "$MREADER_ENV_MAX_BYTES" ]] || {
    dbp_error 'Environment file exceeds the supported size; repair it before configuring recovery.'; return 2;
  }
  assignments="$(awk '/^MREADER_DB_PROTECTION_ROOT=/{n++} END{print n+0}' "$file")"
  [[ "$assignments" -le 1 ]] || { dbp_error 'Resolve duplicate MREADER_DB_PROTECTION_ROOT assignments explicitly.'; return 2; }
  configured="$(env_get "$file" MREADER_DB_PROTECTION_ROOT)"
  if [[ -n "$configured" ]]; then
    selected="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$configured")" || return 2
    if [[ -n "$override" ]]; then
      normalized_override="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$override")" || return 2
      [[ "$selected" == "$normalized_override" ]] || {
        dbp_error 'Process and saved recovery roots disagree; reconcile configuration before startup.'; return 2;
      }
    fi
  else
    selected="$(dbp_normalize_root "$platform" "$host_home" "$profile" "$override")" || return 2
  fi
  if [[ "$configured" != "$selected" ]]; then
    (umask 077; env_set "$file" MREADER_DB_PROTECTION_ROOT "$selected") || return 2
  fi
  printf '%s\n' "$selected"
}
```

Create the CLI:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env-lib.sh"
source "$SCRIPT_DIR/db-protection-root.sh"
[[ $# -le 1 ]] || { dbp_error 'Usage: resolve-db-protection-root.sh [ENV_FILE]'; exit 2; }
env_file="${1:-.env}"
case "$(uname -s)" in
  Linux) platform=linux ;;
  MINGW*|MSYS*|CYGWIN*) platform=windows ;;
  *) dbp_error 'Unsupported host platform; use Linux or Windows/Git Bash.'; exit 2 ;;
esac
if [[ -n "${SUDO_USER:-}" && -z "${MREADER_DB_PROTECTION_ROOT:-}" &&
      -z "$(env_get "$env_file" MREADER_DB_PROTECTION_ROOT)" ]]; then
  dbp_error 'Run setup as the host user, or set an explicit recovery root before using sudo.'
  exit 2
fi
dbp_resolve_env "$env_file" "$platform" "${HOME:-}" "${USERPROFILE:-}" "${MREADER_DB_PROTECTION_ROOT:-}"
```

`HOME` and `USERPROFILE` are read only. Tests pass a host-home argument rather than changing these system variables. Quoted `.env` values are unwrapped as literals; no shell expansion is performed.

- [ ] **Step 4: Verify the complete contract.**

```bash
python3 tests/regression/test_db_protection_root.py -v
bash -n scripts/env/db-protection-root.sh scripts/env/resolve-db-protection-root.sh
```

Expected: 12 passing tests and shell exit 0. Existing invalid configuration must never silently become a new default. An empty quoted value denotes an unset setting; CRLF is normalized by the existing `env_get` contract.

- [ ] **Step 5: Commit.**

```bash
git add scripts/env/db-protection-root.sh scripts/env/resolve-db-protection-root.sh tests/regression/test_db_protection_root.py
git commit -m "feat: persist one recovery-root configuration without shell evaluation"
```

## Task 3: Startup integration without changing backup behavior

**Files:**

- Modify: `scripts/bootstrap.sh`
- Modify: `scripts/hybrid-up.sh`
- Modify: `scripts/hybrid/stateful-up.sh`
- Modify: `.env.example`
- Modify: `tests/regression/bootstrap-fresh-env.sh`
- Modify: `tests/regression/test_db_protection_root.py`

**Interfaces:**

- Consumes: CLI from task 2.
- Produces: all startup paths persist and export the same normalized `MREADER_DB_PROTECTION_ROOT` before their first stateful resource mutation. Resolver failure stops that entry point because these scripts use `set -euo pipefail`.
- This task does not yet bind this path into backup_agent: doing so before implementing its storage/ACL contract would falsely imply artifacts were already local.

- [ ] **Step 1: Extend startup tests first.**

Add this method to `PersistenceTests` (execution review replaced the initial source-order check with a behavioral failure-path check):

```python
    def test_startup_entry_points_resolve_before_stateful_mutation(self):
        for entry in ["scripts/bootstrap.sh", "scripts/hybrid-up.sh", "scripts/hybrid/stateful-up.sh"]:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory(prefix="mreader-startup-") as directory:
                fixture = Path(directory)
                shutil.copytree(ROOT / "scripts", fixture / "scripts")
                shutil.copy(ROOT / ".env.example", fixture / ".env.example")
                (fixture / ".env").write_text((ROOT / ".env.example").read_text().replace(
                    "MREADER_DB_PROTECTION_ROOT=\n", "MREADER_DB_PROTECTION_ROOT=relative/unsafe\n"
                ) + ("" if "MREADER_DB_PROTECTION_ROOT=" in (ROOT / ".env.example").read_text()
                     else "\nMREADER_DB_PROTECTION_ROOT=relative/unsafe\n"))
                binary = fixture / "bin"
                binary.mkdir()
                marker = fixture / "resource-work.log"
                docker = binary / "docker"
                docker.write_text('#!/usr/bin/env bash\n'
                                  'if [[ "$1" == info || ( "$1" == compose && "${2:-}" == version ) ]]; then exit 0; fi\n'
                                  'printf "%s\\n" "$*" >> "$DBP_TEST_RESOURCE_LOG"\nexit 77\n')
                docker.chmod(0o755)
                kubectl = binary / "kubectl"
                kubectl.write_text("#!/usr/bin/env bash\nexit 77\n")
                kubectl.chmod(0o755)
                child_env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}",
                                 MREADER_DB_PROTECTION_ROOT="", DBP_TEST_RESOURCE_LOG=str(marker))
                result = subprocess.run(["bash", str(fixture / entry)], cwd=fixture,
                                        env=child_env, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("absolute Linux recovery path", result.stderr)
                self.assertFalse(marker.exists(), result.stdout + result.stderr)
```

In `tests/regression/bootstrap-fresh-env.sh`, copy both new dependencies after its existing `env-lib.sh` copy:

```bash
cp "$ROOT/scripts/env/db-protection-root.sh" "$TMP/app/scripts/env/db-protection-root.sh"
cp "$ROOT/scripts/env/resolve-db-protection-root.sh" "$TMP/app/scripts/env/resolve-db-protection-root.sh"
```

Change its existing bootstrap execution line to:

```bash
TERM=dumb PATH="$TMP/bin:$PATH" MREADER_DB_PROTECTION_ROOT="$TMP/recovery with spaces" ./scripts/bootstrap.sh >"$TMP/bootstrap.log" 2>&1
```

Add before its final PASS message:

```bash
grep -Fxq "MREADER_DB_PROTECTION_ROOT=$TMP/recovery with spaces" "$TMP/app/.env" || {
  echo 'bootstrap did not persist the explicit recovery root' >&2
  exit 1
}
```

These tests execute the actual scripts with external Docker/Kubernetes commands replaced by explicit boundary doubles. They establish configuration and early-stop behavior, not a real deployment. Actual Windows filesystem/Docker path conversion remains unrun.

- [ ] **Step 2: Confirm failures before wiring the calls.**

```bash
python3 tests/regression/test_db_protection_root.py PersistenceTests.test_startup_entry_points_resolve_before_stateful_mutation -v
bash tests/regression/bootstrap-fresh-env.sh
```

Expected: invalid paths are not rejected before resource work / bootstrap does not persist the root.

- [ ] **Step 3: Wire the shared resolver into all three entry points.**

In `scripts/bootstrap.sh`, immediately after the initial `.env` creation block:

```bash
MREADER_DB_PROTECTION_ROOT="$(bash ./scripts/env/resolve-db-protection-root.sh .env)"
export MREADER_DB_PROTECTION_ROOT
```

In `scripts/hybrid-up.sh`, immediately after `migrate-known-settings.sh`:

```bash
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT
```

In `scripts/hybrid/stateful-up.sh`, immediately after the `.env` presence guard:

```bash
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT
```

Add to `.env.example` immediately before `POSTGRES_BACKUP_ENABLED`:

```dotenv
# Host recovery-root contract. Startup persists an absolute literal path here.
# Default: host home/.mreader/database-protection (Windows: USERPROFILE).
# An existing value is preserved. Do not use $HOME, ~ or shell substitutions.
# Configuration preparation only: storage migration is a separate upgrade step.
MREADER_DB_PROTECTION_ROOT=
```

Do not change the existing 7/14-day backup-agent defaults in this slice: retention migration, old-artifact import and pins must move together in slice 3. The approved final defaults remain 4/2 days.

- [ ] **Step 4: Run the complete focused suite.**

```bash
python3 tests/regression/test_db_protection_root.py -v
bash tests/regression/bootstrap-fresh-env.sh
bash -n scripts/env/db-protection-root.sh scripts/env/resolve-db-protection-root.sh scripts/bootstrap.sh scripts/hybrid-up.sh scripts/hybrid/stateful-up.sh tests/regression/bootstrap-fresh-env.sh
git diff --check
```

Expected: 13 passing Python tests, bootstrap regression PASS, syntax and whitespace exit 0. Report any additional tests introduced during implementation with their actual count. Also inspect `git diff --stat` and confirm there are no backup-agent, migration, application-state or version-bump changes.

- [ ] **Step 5: Commit and record the checkpoint.**

```bash
git add scripts/bootstrap.sh scripts/hybrid-up.sh scripts/hybrid/stateful-up.sh .env.example tests/regression/bootstrap-fresh-env.sh tests/regression/test_db_protection_root.py
git commit -m "fix: resolve the same recovery root from every startup entry point"
```

## Checkpoint acceptance and exclusions

At handoff, provide exact commit IDs and command results; persist the source patch and plan. State clearly that this is an **unreleased path-configuration patch**, not a full RC4.85 release or a verified restore.

This slice covers the resolver/configuration portion of PATH-01 and prerequisites for DBP-01. It does not establish filesystem ACLs, symlink containment, Docker bind conversion, local backup completeness, runtime migrations, retention, restore correctness, or reading synchronization. Those are explicit remaining gates, not passed tests.

Next implement slice 1B before any schema retirement; then proceed through the sequence above. The Progress/UI follow-up remains mandatory: local pending state makes display fast, while one committed PostgreSQL reading transaction makes confirmed state agree across services. Neither replaces the other.

## Plan self-review

- Scope is bounded to a shared path contract; every in-scope requirement maps to tasks 1–3.
- Producer/consumer names agree: `dbp_normalize_root`, `dbp_resolve_env`, CLI, `MREADER_DB_PROTECTION_ROOT`.
- Every code step includes concrete code and a runnable check; failures must be observed before implementation.
- No extra service, database, broker, runtime dependency, resource increase, live mutation or legacy table removal is included.
- Actual Windows filesystem/Docker verification and all backup/restore/runtime reading gates are explicitly outside this patch's acceptance evidence.
