#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
cd "$ROOT"
ENV_FILE="${MREADER_P09_4_ENV_FILE:-.env}"
CONTRACT="${MREADER_POSTGRES_ROLE_CONTRACT:-$ROOT/contracts/ownership/postgres-roles.v1.json}"
COMPOSE_FILE="${MREADER_STATEFUL_COMPOSE_FILE:-$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml}"
CONFIRM="${MREADER_P09_4_RUNTIME_CONFIRM:-}"
EXPECTED_PREVIOUS_GENERATION="${MREADER_P09_4_EXPECT_PREVIOUS_GENERATION:-}"
METADATA_FILE=""
MISMATCH_SQL_FILE=""
MISMATCH_OUTPUT=""

cleanup(){
  [[ -z "$METADATA_FILE" ]] || rm -f "$METADATA_FILE"
  [[ -z "$MISMATCH_SQL_FILE" ]] || rm -f "$MISMATCH_SQL_FILE"
  [[ -z "$MISMATCH_OUTPUT" ]] || rm -f "$MISMATCH_OUTPUT"
}
trap cleanup EXIT HUP INT TERM

fail(){
  echo "P09.4 RUNTIME GATE FAILED: $*" >&2
  exit 1
}

blocked(){
  echo "P09.4 RUNTIME GATE BLOCKED: $*" >&2
  exit 2
}

require_command(){
  command -v "$1" >/dev/null 2>&1 || blocked "$1 is required"
}

[[ "$CONFIRM" == "current-hybrid" ]] \
  || blocked "set MREADER_P09_4_RUNTIME_CONFIRM=current-hybrid only for the authorized Docker Desktop hybrid target"

for cmd in docker kubectl; do require_command "$cmd"; done
docker info >/dev/null 2>&1 || blocked "Docker daemon is unavailable"
KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
[[ "$KUBE_CONTEXT" == "docker-desktop" ]] || blocked "kubectl context must be docker-desktop (got '${KUBE_CONTEXT:-none}')"
[[ -f "$ENV_FILE" ]] || blocked "$ENV_FILE is unavailable"
[[ "$EXPECTED_PREVIOUS_GENERATION" =~ ^[0-9]+$ && "$EXPECTED_PREVIOUS_GENERATION" -ge 1 ]] \
  || blocked "MREADER_P09_4_EXPECT_PREVIOUS_GENERATION must identify the generation immediately before an actual P08.8 restore"

source "$ROOT/scripts/env/env-lib.sh"
env_ensure_healthy "$ENV_FILE" "$ROOT/.env.example" || blocked "environment validation failed"
PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")" \
  || blocked "database protection root is unavailable"
CONTROL_FILE="$PROTECTION_ROOT/control/restore-control.json"
[[ -f "$CONTROL_FILE" ]] || blocked "restore control is unavailable"

CONTROL_FIELDS_RAW="$("$PYTHON_RUNTIME" - "$CONTROL_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
print(payload.get("installation_fingerprint") or "")
print(payload.get("restore_generation") or "")
PY
)" || blocked "restore control could not be parsed"
mapfile -t CONTROL_FIELDS <<<"$CONTROL_FIELDS_RAW"
INSTALLATION_FINGERPRINT="${CONTROL_FIELDS[0]:-}"
RESTORE_GENERATION="${CONTROL_FIELDS[1]:-}"
[[ "$INSTALLATION_FINGERPRINT" =~ ^inst_[0-9a-f]{16}$ && "$RESTORE_GENERATION" =~ ^[0-9]+$ ]] \
  || blocked "restore control is malformed"
(( RESTORE_GENERATION == EXPECTED_PREVIOUS_GENERATION + 1 )) \
  || blocked "current generation $RESTORE_GENERATION is not the expected P08.8 N+1 from $EXPECTED_PREVIOUS_GENERATION"

POSTGRES_USER="$(env_get "$ENV_FILE" POSTGRES_USER)"
POSTGRES_DB="$(env_get "$ENV_FILE" POSTGRES_DB)"; POSTGRES_DB="${POSTGRES_DB:-manhwa}"
[[ -n "$POSTGRES_USER" ]] || blocked "host PostgreSQL bootstrap user is unavailable"

CURRENT_TOKEN="$(bash "$ROOT/scripts/hybrid/p09-4-readiness.sh" "$ENV_FILE" --print-token)" \
  || fail "current P09.4 readiness failed before the runtime probe"
[[ "$CURRENT_TOKEN" =~ ^p094-[0-9a-f]{64}$ ]] || fail "readiness returned an invalid generation token"

workloads(){
  "$PYTHON_RUNTIME" - "$CONTRACT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
for row in payload.get("workloads", []):
    workload = row.get("workload")
    if workload and workload != "keda-postgres":
        print(workload)
PY
}

deployment_namespace(){
  local workload="$1" found="" ns
  for ns in mreader-user mreader-admin; do
    if kubectl -n "$ns" get deployment "$workload" >/dev/null 2>&1; then
      [[ -z "$found" ]] || fail "database workload $workload exists in more than one namespace"
      found="$ns"
    fi
  done
  [[ -n "$found" ]] || fail "database workload deployment is missing: $workload"
  printf '%s\n' "$found"
}

live_generation(){
  local ns="$1" workload="$2"
  kubectl -n "$ns" get deployment "$workload" \
    -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MREADER_DEPLOYMENT_GENERATION")].value}'
}

verify_live_generations(){
  local expected="$1" workload ns actual
  while IFS= read -r workload; do
    [[ -n "$workload" ]] || continue
    ns="$(deployment_namespace "$workload")"
    actual="$(live_generation "$ns" "$workload")"
    [[ "$actual" == "$expected" ]] || fail "$ns/$workload has stale MREADER_DEPLOYMENT_GENERATION"
  done < <(workloads)
}

verify_live_secret_scopes(){
  local workload ns secret_json forbidden
  while IFS= read -r workload; do
    [[ -n "$workload" ]] || continue
    ns="$(deployment_namespace "$workload")"
    secret_json="$(kubectl -n "$ns" get secret "mreader-env-${workload}" -o json 2>/dev/null)" \
      || fail "$ns/mreader-env-${workload} is missing"
    for forbidden in POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL POSTGRES_URL; do
      if "$PYTHON_RUNTIME" - "$secret_json" "$forbidden" <<'PY' >/dev/null 2>&1
import json
import sys

payload = json.loads(sys.argv[1])
raise SystemExit(0 if sys.argv[2] in (payload.get("data") or {}) else 1)
PY
      then
        fail "$ns/mreader-env-${workload} exposes bootstrap database key $forbidden"
      fi
    done
  done < <(workloads)
}

assert_autoscaling_absent(){
  local ns
  [[ -z "$(kubectl -n mreader-user get hpa -o name 2>/dev/null || true)" ]] \
    || fail "HPA authority returned before readiness/rollout proof"
  if kubectl api-resources --api-group=keda.sh -o name 2>/dev/null | grep -Fxq 'scaledobjects.keda.sh'; then
    for ns in mreader-user mreader-admin; do
      [[ -z "$(kubectl -n "$ns" get scaledobject -o name 2>/dev/null || true)" ]] \
        || fail "$ns ScaledObject authority returned before readiness/rollout proof"
    done
  fi
}

assert_autoscaling_restored(){
  [[ -n "$(kubectl -n mreader-user get hpa -o name 2>/dev/null || true)" ]] \
    || fail "user HPA was not restored"
  local ns
  for ns in mreader-user mreader-admin; do
    [[ -n "$(kubectl -n "$ns" get scaledobject -o name 2>/dev/null || true)" ]] \
      || fail "$ns ScaledObjects were not restored"
  done
}

verify_replica_zero_templates(){
  # Derive the zero-replica DB workers from generation-neutral checked-in manifests,
  # then verify their live pod templates carry the current token even before KEDA starts them.
  local workload ns actual count=0
  while IFS= read -r workload; do
    [[ -n "$workload" ]] || continue
    count=$((count + 1))
    ns="$(deployment_namespace "$workload")"
    actual="$(live_generation "$ns" "$workload")"
    [[ "$actual" == "$CURRENT_TOKEN" ]] || fail "$ns/$workload replica-zero template is stale"
  done < <("$PYTHON_RUNTIME" - "$CONTRACT" "$ROOT/deploy/docker-desktop-hybrid/user-apps.yaml" "$ROOT/deploy/docker-desktop-hybrid/admin-apps.yaml" <<'PY'
import json, re, sys
from pathlib import Path
expected={r['workload'] for r in json.load(open(sys.argv[1], encoding='utf-8'))['workloads'] if r['workload'] != 'keda-postgres'}
for path in map(Path, sys.argv[2:]):
    for doc in re.split(r'(?m)^---\s*$', path.read_text(encoding='utf-8')):
        name=re.search(r'(?m)^metadata:\s*$\n(?:(?:  [^\n]*)\n)*?  name:\s*([^\s#]+)', doc)
        if name and name.group(1) in expected and re.search(r'(?m)^  replicas:\s*0\s*$', doc):
            print(name.group(1))
PY
)
  (( count > 0 )) || fail "no contract-backed replica-zero worker template was found"
}

# First prove the actual N+1 deployment is internally consistent.
verify_live_generations "$CURRENT_TOKEN"
verify_live_secret_scopes
verify_replica_zero_templates

# Quiescence removes HPA/KEDA authority before the controlled mismatch probe.
bash "$ROOT/scripts/hybrid/quiesce-before-migration.sh" \
  || fail "could not quiesce workloads for the controlled mismatch probe"
assert_autoscaling_absent
verify_replica_zero_templates

METADATA_FILE="$(mktemp)" || fail "mktemp failed"
"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/p09-4-readiness.py" metadata \
  --contract "$CONTRACT" --env-file "$ENV_FILE" --root "$ROOT" \
  --control-file "$CONTROL_FILE" --migrations-dir "$ROOT/db/migrations" >"$METADATA_FILE" \
  || fail "could not derive current readiness metadata"
LATEST_MIGRATION="$("$PYTHON_RUNTIME" - "$METADATA_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
print(payload.get("latest_migration") or "")
PY
)" || fail "could not parse readiness metadata"
[[ -n "$LATEST_MIGRATION" ]] || fail "readiness metadata omitted latest_migration"

# This is a read-only mismatched expectation. It never modifies the P08.8 host
# control file or database_restore_state authority.
MISMATCH_GENERATION=$((RESTORE_GENERATION + 1))
MISMATCH_SQL_FILE="$(mktemp)" || fail "mktemp failed"
MISMATCH_OUTPUT="$(mktemp)" || fail "mktemp failed"
"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/p09-4-readiness.py" sql \
  --database "$POSTGRES_DB" --migration "$LATEST_MIGRATION" \
  --installation-fingerprint "$INSTALLATION_FINGERPRINT" \
  --generation "$MISMATCH_GENERATION" >"$MISMATCH_SQL_FILE" \
  || fail "could not render mismatch readiness SQL"

if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
  psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v latest_migration="$LATEST_MIGRATION" \
    -v installation_fingerprint="$INSTALLATION_FINGERPRINT" \
    -v restore_generation="$MISMATCH_GENERATION" \
    -v database_name="$POSTGRES_DB" -f - <"$MISMATCH_SQL_FILE" >"$MISMATCH_OUTPUT" 2>&1; then
  fail "controlled generation mismatch unexpectedly passed readiness"
fi
grep -q 'P09.4 generation-not-ready' "$MISMATCH_OUTPUT" \
  || fail "controlled mismatch failed for an unexpected reason"
assert_autoscaling_absent

# Resume only through the same canonical path used after a real P08.8 restore.
bash "$ROOT/scripts/hybrid/deploy.sh" \
  || fail "canonical deploy failed; workloads/autoscaling remain fail-closed"
POST_TOKEN="$(bash "$ROOT/scripts/hybrid/p09-4-readiness.sh" "$ENV_FILE" --print-token)" \
  || fail "post-rollout readiness failed"
[[ "$POST_TOKEN" == "$CURRENT_TOKEN" ]] || fail "generation token changed without a P08.8 generation transition"
verify_live_generations "$CURRENT_TOKEN"
verify_live_secret_scopes
verify_replica_zero_templates
assert_autoscaling_restored

# p09-4-readiness.py metadata has already revalidated every workload secret
# scope and rejects bootstrap database credentials in application scopes.
echo "P09.4 RUNTIME GATE PASSED"
