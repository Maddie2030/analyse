#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }
file=scripts/hybrid/stateful-up.sh
[[ -f "$file" ]] || fail "stateful-up.sh missing"
grep -q '^MREADER_SKIP_PREUPGRADE_BACKUP=false$' .env.example || fail "safe default for pre-upgrade backup skip is missing"
grep -q 'MREADER_SKIP_PREUPGRADE_BACKUP' "$file" || fail "stateful-up does not read initialization skip flag"
grep -q 'Skipping mandatory local pre-upgrade PostgreSQL recovery bundle' "$file" || fail "stateful-up does not emit explicit skip warning"
grep -q 'create-local-preupgrade-backup.sh' "$file" || fail "normal pre-upgrade backup path was removed"
printf 'hybrid initialization pre-upgrade backup bypass contract PASSED\n'
