#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
[[ -f .env ]] || { echo "ERROR: .env is required (copy .env.example and fill secrets/NAS settings)." >&2; exit 2; }
backup_enabled="$(awk -F= '$1=="POSTGRES_BACKUP_ENABLED"{print $2; exit}' .env | tr -d '\r' | xargs 2>/dev/null || true)"
backup_enabled="${backup_enabled:-true}"
saved_skip_preupgrade="$(awk -F= '$1=="MREADER_SKIP_PREUPGRADE_BACKUP"{print $2; exit}' .env | tr -d '\r' | xargs 2>/dev/null || true)"
skip_preupgrade="${MREADER_SKIP_PREUPGRADE_BACKUP:-${saved_skip_preupgrade:-false}}"
case "$skip_preupgrade" in
  true|false) ;;
  *) echo "ERROR: MREADER_SKIP_PREUPGRADE_BACKUP must be true or false." >&2; exit 2 ;;
esac
if [[ "$backup_enabled" == "true" ]]; then
  "$ROOT/scripts/hybrid/ensure-private-transport-secrets.sh" .env
fi
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT

phase="${1:-core}"
case "$phase" in
  core)
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml up -d --wait db redis redis_cache rabbitmq
    # Stop an older backup scheduler before repairing replication access so an
    # RC4.26/27 agent cannot keep retrying with stale credentials in parallel.
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml stop backup_agent >/dev/null 2>&1 || true
    echo "Quiescing old Kubernetes mutation workloads and draining legacy Progress work..."
    "$ROOT/scripts/hybrid/quiesce-before-migration.sh"
    "$ROOT/scripts/backup/configure-replication.sh"
    if [[ "$skip_preupgrade" == "true" ]]; then
      echo "WARNING: MREADER_SKIP_PREUPGRADE_BACKUP=true; Skipping mandatory local pre-upgrade PostgreSQL recovery bundle for this initialization run." >&2
    else
      echo "Creating verified local pre-upgrade PostgreSQL recovery bundle..."
      set +e
      "$ROOT/scripts/hybrid/create-local-preupgrade-backup.sh" .env
      local_preupgrade_rc=$?
      set -e
      if [[ "$local_preupgrade_rc" -ne 0 ]]; then
        echo "ERROR: mandatory local pre-upgrade recovery capture failed (exit=$local_preupgrade_rc); migrations were not run." >&2
        exit "$local_preupgrade_rc"
      fi
    fi
    backup_ready=false
    if [[ "$backup_enabled" == "true" ]]; then
      echo "Validating PostgreSQL backup agent, replication permission and host-local recovery root..."
      set +e
      docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm --build backup_agent self-test
      backup_rc=$?
      set -e
      if [[ "$backup_rc" -eq 0 ]]; then
        backup_ready=true
      else
        echo "ERROR: PostgreSQL backup self-test failed (exit=$backup_rc); refusing to run migrations with an invalid local recovery/replication configuration." >&2
        exit "$backup_rc"
      fi
    else
      echo "WARNING: POSTGRES_BACKUP_ENABLED=false; scheduled protection is disabled. The mandatory local pre-upgrade bundle was still created." >&2
    fi
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml --profile migration run --rm migrate
    echo "Reconciling restrictive PostgreSQL runtime roles..."
    "$ROOT/scripts/hybrid/reconcile-postgres-roles.sh" .env
    echo "Initializing/verifying PostgreSQL restore-generation mirror..."
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm --build backup_agent initialize-restore-state >/dev/null
    if [[ "$backup_enabled" == "true" ]]; then
      # The operation engine rebuilds its browser-safe catalog projection from
      # the verified host-local manifests after migrations.
      docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml up -d --build backup_agent
    else
      docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml stop backup_agent >/dev/null 2>&1 || true
    fi
    echo "Hybrid stateful core is healthy/migrated/reconciled: PostgreSQL + Valkey + RabbitMQ; application resume still requires P09.4 deploy.sh readiness."
    if [[ "$backup_enabled" == "true" && "$backup_ready" == "true" ]]; then
      echo "Database protection engine is running with full backup/snapshot/restore capability."
    fi
    ;;
  edge)
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml up -d image_edge
    echo "Hybrid Docker image edge started."
    ;;
  all)
    "$0" core
    "$0" edge
    ;;
  *)
    echo "Usage: $0 [core|edge|all]" >&2
    exit 2
    ;;
esac
