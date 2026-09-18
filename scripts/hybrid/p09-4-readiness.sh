#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
# shellcheck source=../env/env-lib.sh
source "$ROOT/scripts/env/env-lib.sh"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"

ENV_FILE=".env"
PRINT_TOKEN=0
for arg in "$@"; do
  case "$arg" in
    --print-token) PRINT_TOKEN=1 ;;
    -*) echo "ERROR: usage: p09-4-readiness.sh [ENV_FILE] --print-token" >&2; exit 2 ;;
    *) ENV_FILE="$arg" ;;
  esac
done
(( PRINT_TOKEN == 1 )) || { echo "ERROR: usage: p09-4-readiness.sh [ENV_FILE] --print-token" >&2; exit 2; }

fail_readiness(){
  local category="$1"; shift
  printf 'P09_4_READINESS=%s %s\n' "$category" "$*" >&2
  exit 1
}
# Keep the full finite failure vocabulary visible to operators/static qualification.
: "P09_4_READINESS=schema-not-ready"
: "P09_4_READINESS=grants-not-ready"
: "P09_4_READINESS=credentials-not-ready"
: "P09_4_READINESS=generation-not-ready"
: "P09_4_READINESS=restore-state-ambiguous"

env_ensure_healthy "$ENV_FILE" "$ROOT/.env.example"
CONTRACT="${MREADER_POSTGRES_ROLE_CONTRACT:-$ROOT/contracts/ownership/postgres-roles.v1.json}"
COMPOSE_FILE="${MREADER_STATEFUL_COMPOSE_FILE:-$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml}"

if ! PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")"; then
  fail_readiness generation-not-ready "database protection root is unavailable"
fi
CONTROL_FILE="$PROTECTION_ROOT/control/restore-control.json"

shopt -s nullglob
cutover_markers=("$PROTECTION_ROOT"/control/restore-cutover-*.json)
shopt -u nullglob
if (( ${#cutover_markers[@]} > 0 )); then
  fail_readiness restore-state-ambiguous "unresolved restore cutover journal exists"
fi

if ! "$ROOT/scripts/run-postgres-role-audit.sh" --contract "$CONTRACT" 1>&2; then
  fail_readiness grants-not-ready "same-tree PostgreSQL role audit failed"
fi

POSTGRES_USER="$(env_get "$ENV_FILE" POSTGRES_USER)"
POSTGRES_DB="$(env_get "$ENV_FILE" POSTGRES_DB)"; POSTGRES_DB="${POSTGRES_DB:-manhwa}"
[[ -n "$POSTGRES_USER" ]] || fail_readiness credentials-not-ready "host bootstrap PostgreSQL user is unavailable"

mkdir -p "$ROOT/.runtime"
metadata_file="$(mktemp "$ROOT/.runtime/p09-4-metadata.XXXXXX")"
sql_file="$(mktemp "$ROOT/.runtime/p09-4-sql.XXXXXX")"
db_output="$(mktemp "$ROOT/.runtime/p09-4-db-output.XXXXXX")"
cleanup(){ rm -f "$metadata_file" "$sql_file" "$db_output"; }
trap cleanup EXIT

if ! "$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/p09-4-readiness.py" metadata \
  --contract "$CONTRACT" \
  --env-file "$ENV_FILE" \
  --root "$ROOT" \
  --control-file "$CONTROL_FILE" \
  --migrations-dir "$ROOT/db/migrations" >"$metadata_file"; then
  exit 1
fi

json_field(){
  "$PYTHON_RUNTIME" - "$metadata_file" "$1" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8') as handle:
    value=json.load(handle)[sys.argv[2]]
print(value)
PY
}
TOKEN="$(json_field token)"
LATEST_MIGRATION="$(json_field latest_migration)"
INSTALLATION_FINGERPRINT="$(json_field installation_fingerprint)"
RESTORE_GENERATION="$(json_field restore_generation)"

if ! "$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-postgres-role-sql.py" \
  --contract "$CONTRACT" --database "$POSTGRES_DB" --mode verify \
| docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
    psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" >/dev/null; then
  fail_readiness grants-not-ready "effective PostgreSQL grant verification failed"
fi

"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/p09-4-readiness.py" sql \
  --database "$POSTGRES_DB" \
  --migration "$LATEST_MIGRATION" \
  --installation-fingerprint "$INSTALLATION_FINGERPRINT" \
  --generation "$RESTORE_GENERATION" >"$sql_file" \
  || fail_readiness generation-not-ready "could not render readiness SQL"

if ! docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
    psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      -v latest_migration="$LATEST_MIGRATION" \
      -v installation_fingerprint="$INSTALLATION_FINGERPRINT" \
      -v restore_generation="$RESTORE_GENERATION" \
      -v database_name="$POSTGRES_DB" \
      -f - <"$sql_file" >"$db_output" 2>&1; then
  cat "$db_output" >&2
  if grep -q 'P09.4 schema-not-ready' "$db_output"; then
    fail_readiness schema-not-ready "live PostgreSQL schema is not current"
  fi
  if grep -q 'P09.4 generation-not-ready' "$db_output"; then
    fail_readiness generation-not-ready "host/database restore generation is inconsistent"
  fi
  fail_readiness schema-not-ready "live PostgreSQL readiness query failed"
fi

printf '%s\n' "$TOKEN"
