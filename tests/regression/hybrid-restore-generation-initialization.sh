#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }
file=scripts/hybrid/stateful-up.sh
migrate='docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml --profile migration run --rm migrate'
reconcile='"$ROOT/scripts/hybrid/reconcile-postgres-roles.sh" .env'
initialize='backup_agent initialize-restore-state'
grep -Fq "$initialize" "$file" || fail "stateful-up does not initialize restore generation after migration"
migrate_line="$(grep -nF "$migrate" "$file" | head -n1 | cut -d: -f1)"
reconcile_line="$(grep -nF "$reconcile" "$file" | head -n1 | cut -d: -f1)"
init_line="$(grep -nF "$initialize" "$file" | head -n1 | cut -d: -f1)"
[[ "$migrate_line" -lt "$reconcile_line" && "$reconcile_line" -lt "$init_line" ]] \
  || fail "restore generation initialization must follow migration and role reconciliation"
grep -Fq 'run --rm --build backup_agent initialize-restore-state' "$file" \
  || fail "restore generation initialization must be available even when scheduled backup is disabled"
echo "hybrid restore-generation initialization regression PASSED"
