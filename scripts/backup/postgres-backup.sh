#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
ENV_FILE="${MREADER_ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "ERROR: application environment file is required." >&2; exit 2; }
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")"
export MREADER_DB_PROTECTION_ROOT
bash "$ROOT/scripts/env/migrate-known-settings.sh" "$ENV_FILE"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml)

scheduler_running(){
  "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -Fxq backup_agent
}

run_with_scheduler_paused(){
  local was_running=false rc=0
  if scheduler_running; then
    was_running=true
    "${COMPOSE[@]}" stop backup_agent >/dev/null
  fi
  # The one-shot container shares the same host-local recovery root but is now the only
  # backup process, preventing CLI/manual/snapshot work from racing the daemon.
  "${COMPOSE[@]}" run --rm --build backup_agent "$@" || rc=$?
  if $was_running; then
    "${COMPOSE[@]}" up -d --build backup_agent >/dev/null
  fi
  return "$rc"
}

cmd="${1:-status}"; shift || true
case "$cmd" in
  repair-replication)
    "${COMPOSE[@]}" up -d --wait db
    "${COMPOSE[@]}" stop backup_agent >/dev/null 2>&1 || true
    "$ROOT/scripts/backup/configure-replication.sh" "$ENV_FILE"
    "${COMPOSE[@]}" run --rm --build backup_agent self-test
    "${COMPOSE[@]}" up -d --build backup_agent
    echo "PostgreSQL replication backup access repaired and backup scheduler restarted."
    ;;
  self-test)
    "${COMPOSE[@]}" up -d --wait db
    "$ROOT/scripts/backup/configure-replication.sh" "$ENV_FILE"
    "${COMPOSE[@]}" run --rm --build backup_agent self-test
    ;;
  snapshot)
    "${COMPOSE[@]}" up -d --wait db
    "$ROOT/scripts/backup/configure-replication.sh" "$ENV_FILE"
    run_with_scheduler_paused snapshot "$@"
    ;;
  daily|manual|pre-upgrade|pre-restore|verify-restore-latest)
    run_with_scheduler_paused "$cmd" "$@"
    ;;
  check-storage)
    # Run the owner's validation without configuring roles, starting dependencies,
    # stopping the daemon or creating a backup. Self-test uses a disposable local
    # write probe and reads PostgreSQL/replication state.
    "${COMPOSE[@]}" run --rm --no-deps --build backup_agent self-test
    ;;
  status|list)
    "${COMPOSE[@]}" run --rm --build backup_agent "$cmd" "$@"
    ;;
  logs)
    "${COMPOSE[@]}" logs -f --tail=200 backup_agent
    ;;
  diagnose)
    echo '== backup_agent container =='
    "${COMPOSE[@]}" ps backup_agent || true
    echo
    echo '== recent backup_agent logs =='
    "${COMPOSE[@]}" logs --tail=200 backup_agent || true
    echo
    echo '== destructive-free backup self-test =='
    "${COMPOSE[@]}" run --rm --build backup_agent self-test
    ;;
  *)
    cat >&2 <<'USAGE'
Usage: ./db-backup.sh {status|list|check-storage|repair-replication|self-test|daily|manual [label]|snapshot|pre-upgrade [label]|pre-restore [label]|verify-restore-latest|logs|diagnose}
USAGE
    exit 2
    ;;
esac
