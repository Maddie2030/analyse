#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }
file=scripts/hybrid/stateful-up.sh
[[ -f "$file" ]] || fail "stateful-up.sh missing"
backup_line="$(grep -n 'create-local-preupgrade-backup.sh' "$file" | head -1 | cut -d: -f1)"
migrate_line="$(grep -n -- '--profile migration run --rm migrate' "$file" | head -1 | cut -d: -f1)"
[[ -n "$backup_line" ]] || fail "pre-upgrade PostgreSQL extraction/backup missing"
[[ -n "$migrate_line" ]] || fail "migration invocation missing"
(( backup_line < migrate_line )) || fail "migrations run before pre-upgrade backup extraction"
[[ "$(grep -c 'create-local-preupgrade-backup.sh' "$file")" == 1 ]] || fail "pre-upgrade capture has duplicate startup paths"
! grep -q 'backup_agent pre-upgrade' "$file" || fail "legacy NAS pre-upgrade capture remains"
grep -Fq 'Stateful volume ownership' scripts/hybrid/adopt-existing-stateful-volumes.sh || true
printf 'hybrid pre-upgrade backup ordering regression PASSED (backup line %s < migration line %s)\n' "$backup_line" "$migrate_line"
