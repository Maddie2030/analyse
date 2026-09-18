#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
CONTRACT="$ROOT/contracts/ownership/postgres-roles.v1.json"
DSN="${MREADER_P09_3_POSTGRES_DSN:-}"
ALLOW_DSN="${MREADER_P09_3_ALLOW_DISPOSABLE_DSN:-0}"
POSTGRES_IMAGE="${MREADER_P09_3_POSTGRES_IMAGE:-postgres:16.10-alpine3.22}"
POSTGRES_USER="mreader_p09_3"
POSTGRES_DB="mreader_p09_3"
POSTGRES_PASSWORD="mreader_p09_3_${RANDOM}_$$"
DOCKER_CONTAINER=""
MIGRATION_SCRIPT=""
MODE=""

cleanup() {
  [[ -z "$MIGRATION_SCRIPT" ]] || rm -f "$MIGRATION_SCRIPT"
  if [[ -n "$DOCKER_CONTAINER" ]] && command -v docker >/dev/null 2>&1; then
    docker rm -f "$DOCKER_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT HUP INT TERM

fail() {
  echo "P09.3 POSTGRES GRANTS GATE FAILED" >&2
  [[ $# -eq 0 ]] || echo "reason: $*" >&2
  exit 1
}

blocked() {
  echo "P09.3 POSTGRES GRANTS GATE BLOCKED: $*" >&2
  exit 2
}

run_psql() {
  if [[ "$MODE" == "dsn" ]]; then
    psql -X "$DSN" "$@"
  else
    docker exec -i -e "PGPASSWORD=$POSTGRES_PASSWORD" "$DOCKER_CONTAINER" \
      psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
  fi
}

role_connection_uri() {
  local role="$1" password="$2"
  "$PYTHON_RUNTIME" - "$DSN" "$role" "$password" <<'PY'
import sys
from urllib.parse import quote, urlsplit, urlunsplit

dsn, role, password = sys.argv[1:]
parts = urlsplit(dsn)
if parts.scheme not in {"postgres", "postgresql"} or not parts.hostname:
    raise SystemExit(2)
host = parts.hostname
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{host}"
if parts.port is not None:
    netloc += f":{parts.port}"
print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
}

run_as_workload() {
  local role="$1"
  shift
  local password="p093_${role}_test_password"
  if [[ "$MODE" == "dsn" ]]; then
    local role_uri
    role_uri="$(role_connection_uri "$role" "$password")" \
      || fail "MREADER_P09_3_POSTGRES_DSN must be a postgres:// or postgresql:// URI for workload-login probes"
    PGCONNECT_TIMEOUT=5 psql -X "$role_uri" "$@"
  else
    docker exec -i -e "PGPASSWORD=$password" "$DOCKER_CONTAINER" \
      psql -X -h 127.0.0.1 -U "$role" -d "$POSTGRES_DB" "$@"
  fi
}

expect_role_success() {
  local role="$1" sql="$2"
  run_as_workload "$role" -v ON_ERROR_STOP=1 -q -c "$sql" >/dev/null 2>&1 \
    || fail "expected success for role=$role sql=$sql"
}

expect_role_failure() {
  local role="$1" sql="$2" label="${3:-permission denial}"
  if run_as_workload "$role" -v ON_ERROR_STOP=1 -q -c "$sql" >/dev/null 2>&1; then
    fail "$label unexpectedly succeeded for role=$role sql=$sql"
  fi
}

check_table_privilege() {
  local role="$1" table="$2" privilege="$3" expected="$4" label="$5" actual
  actual="$(run_psql -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT has_table_privilege('$role','public.$table','$privilege');" 2>/dev/null | tr -d '[:space:]')" \
    || fail "could not inspect $label"
  [[ "$actual" == "$expected" ]] || fail "$label expected=$expected actual=${actual:-empty}"
}

if [[ -n "$DSN" ]]; then
  [[ "$ALLOW_DSN" == "1" ]] || blocked "set MREADER_P09_3_ALLOW_DISPOSABLE_DSN=1 only for an isolated disposable database"
  command -v psql >/dev/null 2>&1 || blocked "psql is required for MREADER_P09_3_POSTGRES_DSN mode"
  MODE="dsn"
  POSTGRES_DB="$(run_psql -Atq -v ON_ERROR_STOP=1 -c 'SELECT current_database();' 2>/dev/null | tr -d '[:space:]')" \
    || blocked "could not inspect the explicitly allowed disposable DSN"
  [[ -n "$POSTGRES_DB" ]] || blocked "disposable DSN did not report a current database"
else
  command -v docker >/dev/null 2>&1 || blocked "Docker unavailable and no explicitly allowed disposable DSN provided"
  MODE="docker"
  DOCKER_CONTAINER="mreader-p09-3-${RANDOM}-$$"
  docker run -d --rm \
    --name "$DOCKER_CONTAINER" \
    --tmpfs /var/lib/postgresql/data:rw \
    -e "POSTGRES_USER=$POSTGRES_USER" \
    -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    -e "POSTGRES_DB=$POSTGRES_DB" \
    "$POSTGRES_IMAGE" >/dev/null || fail "could not start disposable PostgreSQL 16 container"
  ready=false
  for _ in $(seq 1 60); do
    if docker exec "$DOCKER_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done
  [[ "$ready" == true ]] || fail "disposable PostgreSQL container did not become ready"
fi

"$ROOT/scripts/run-postgres-role-audit.sh" --contract "$CONTRACT" >/dev/null \
  || fail "P09.3 role contract audit failed"

MIGRATION_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/mreader-p09-3-migrations.XXXXXXXX")" || fail "mktemp failed"
sh "$ROOT/ops/migrate/render.sh" \
  "$ROOT/db/migrations" \
  "$ROOT/db/upgrade/preserve-reading-evidence.sql" >"$MIGRATION_SCRIPT" \
  || fail "migration render failed"
run_psql -v ON_ERROR_STOP=1 <"$MIGRATION_SCRIPT" >/dev/null \
  || fail "migrations failed on disposable database"

# Give the renderer deterministic test-only role passwords. The SQL is piped
# directly to psql and never printed.
while IFS= read -r role; do
  role_upper="$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')"
  export "MREADER_DB_ROLE_PASSWORD_${role_upper}=p093_${role}_test_password"
done < <("$PYTHON_RUNTIME" - "$CONTRACT" <<'PY'
import json, sys
contract=json.load(open(sys.argv[1], encoding='utf-8'))
for row in contract['workloads']:
    print(row['role'])
PY
)

"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-postgres-role-sql.py" \
  --contract "$CONTRACT" --database "$POSTGRES_DB" \
| run_psql -v ON_ERROR_STOP=1 >/dev/null \
  || fail "runtime-role reconciliation failed on disposable database"

# Created by bootstrap *after* role reconciliation. Runtime roles must not gain
# access through default privileges or broad future-object grants.
run_psql -v ON_ERROR_STOP=1 -q -c \
  "CREATE TABLE public.p093_new_table(id int);" >/dev/null \
  || fail "could not create post-reconciliation bootstrap table"
run_psql -v ON_ERROR_STOP=1 -q -c \
  "CREATE FUNCTION public.p093_new_function() RETURNS integer LANGUAGE sql AS 'SELECT 1';" >/dev/null \
  || fail "could not create post-reconciliation bootstrap function"

# Every workload login authenticates with its own password and proves a real
# required SELECT from its declared capability. It also receives the same
# security-baseline denials plus representative forbidden cross-domain INSERT,
# UPDATE and DELETE probes chosen from current contract-managed tables.
while IFS='|' read -r role required_read forbidden_insert forbidden_update forbidden_delete; do
  expect_role_success "$role" "SELECT 1 FROM public.\"$required_read\" LIMIT 0;" \
    || fail "required SELECT failed for role=$role table=$required_read"
  expect_role_failure "$role" "CREATE ROLE p093_forbidden;"
  expect_role_failure "$role" "CREATE DATABASE p093_forbidden;"
  expect_role_failure "$role" "CREATE TABLE public.p093_forbidden_${role}(id int);"
  expect_role_failure "$role" "SELECT * FROM public.p093_new_table;"
  expect_role_failure "$role" "SELECT public.p093_new_function();"

  check_table_privilege "$role" "$forbidden_insert" INSERT f "forbidden cross-domain INSERT"
  expect_role_failure "$role" "INSERT INTO public.\"$forbidden_insert\" DEFAULT VALUES;" \
    "forbidden cross-domain INSERT"

  check_table_privilege "$role" "$forbidden_update" UPDATE f "forbidden cross-domain UPDATE"
  update_column="$(run_psql -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='$forbidden_update' ORDER BY ordinal_position LIMIT 1;" 2>/dev/null | tr -d '[:space:]')" \
    || fail "could not choose update column for $forbidden_update"
  [[ -n "$update_column" ]] || fail "no update column found for $forbidden_update"
  expect_role_failure "$role" \
    "UPDATE public.\"$forbidden_update\" SET \"$update_column\" = \"$update_column\" WHERE false;" \
    "forbidden cross-domain UPDATE"

  check_table_privilege "$role" "$forbidden_delete" DELETE f "forbidden cross-domain DELETE"
  expect_role_failure "$role" "DELETE FROM public.\"$forbidden_delete\" WHERE false;" \
    "forbidden cross-domain DELETE"
done < <("$PYTHON_RUNTIME" - "$CONTRACT" <<'PY'
import json, sys
contract=json.load(open(sys.argv[1], encoding='utf-8'))
capabilities={row['name']: row for row in contract['capabilities']}
all_tables=sorted({
    grant['resource']
    for capability in contract['capabilities']
    for grant in capability.get('grants', [])
    if grant['object_type'] == 'table'
})
for row in contract['workloads']:
    effective={}
    for capability_name in row['capabilities']:
        for grant in capabilities[capability_name].get('grants', []):
            if grant['object_type'] != 'table':
                continue
            effective.setdefault(grant['resource'], set()).update(grant['privileges'])
    readable=next((table for table in all_tables if 'select' in effective.get(table, set())), None)
    denied=[]
    for privilege in ('insert', 'update', 'delete'):
        table=next((table for table in all_tables if privilege not in effective.get(table, set())), None)
        denied.append(table)
    if readable is None or any(table is None for table in denied):
        raise SystemExit(f"could not derive positive/negative probes for {row['workload']}")
    print('|'.join([row['role'], readable, *denied]))
PY
)

# notification creation/read-state
check_table_privilege mreader_notification_worker notifications INSERT t "notification worker creates notifications"
check_table_privilege mreader_social_ts notifications INSERT f "social cannot create notifications"
check_table_privilege mreader_social_ts notifications UPDATE t "social owns notification read-state"

# outbox producer/relay
check_table_privilege mreader_catalog_go event_outbox INSERT t "catalog may append outbox events"
check_table_privilege mreader_outbox_relay event_outbox INSERT f "relay cannot produce outbox events"
check_table_privilege mreader_outbox_relay event_outbox UPDATE t "relay owns outbox delivery state"

# lifecycle enqueue/execute
check_table_privilege mreader_catalog_go lifecycle_cleanup_jobs INSERT t "catalog may enqueue lifecycle work"
check_table_privilege mreader_catalog_go lifecycle_cleanup_jobs DELETE f "catalog cannot execute/delete lifecycle work"
check_table_privilege mreader_lifecycle_worker lifecycle_cleanup_jobs DELETE t "lifecycle worker executes cleanup"

# catalog parent-delete vs direct child delete
check_table_privilege mreader_catalog_go series DELETE t "catalog may delete canonical series parent"
check_table_privilege mreader_catalog_go bookmarks DELETE f "catalog cannot directly delete social child rows"

# reader trending write
check_table_privilege mreader_reader_go series_trending_hourly UPDATE t "reader owns trending projection writes"

# keda select-only
check_table_privilege mreader_keda_metrics event_outbox SELECT t "keda may read queue metrics"
check_table_privilege mreader_keda_metrics event_outbox UPDATE f "keda cannot mutate queue state"

echo "P09.3 POSTGRES GRANTS GATE PASSED"
