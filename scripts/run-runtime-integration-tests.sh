#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
source "$ROOT/scripts/tests/test-runner-common.sh"

for cmd in docker kubectl curl awk grep; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == "docker-desktop" ]] || { echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$ROOT/test-results/runtime-integration/$RUN_ID"; mkdir -p "$OUT"
COMPOSE=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml)
PGUSER="$(env_get .env POSTGRES_USER)"; PGUSER="${PGUSER:-mreader}"
PGDB="$(env_get .env POSTGRES_DB)"; PGDB="${PGDB:-mreader}"
USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
TEMP_RELAY=0; EVENT_ID=""
psql_scalar(){ "${COMPOSE[@]}" exec -T db psql -X -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" -Atc "$1" | tr -d '\r' | tail -n1; }
cleanup(){
  local rc=$?
  if [[ -n "$EVENT_ID" ]]; then psql_scalar "DELETE FROM event_outbox WHERE event_id='$EVENT_ID'::uuid RETURNING 1;" >/dev/null 2>&1 || true; fi
  if (( TEMP_RELAY )); then kubectl -n mreader-admin scale deployment/outbox-relay --replicas=0 >/dev/null 2>&1 || true; fi
  exit "$rc"
}
trap cleanup EXIT

exec > >(tee "$OUT/runtime-integration.log") 2>&1
test_section "Current twin-plane runtime integration"
"${COMPOSE[@]}" exec -T db pg_isready -U "$PGUSER" -d "$PGDB"
"${COMPOSE[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping
curl -fsS --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz" >/dev/null
curl -fsS --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null

test_section "Transactional outbox -> RabbitMQ publisher-confirm path"
EVENT_ID="$(psql_scalar "SELECT enqueue_event_outbox_v1('audit.created','test.runtime.integration',1,'test','runtime-$RUN_ID','runtime-$RUN_ID','test-harness',jsonb_build_object('run_id','$RUN_ID'));" )"
[[ "$EVENT_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "FAIL: did not receive outbox event UUID: $EVENT_ID" >&2; exit 1; }
echo "Inserted probe event $EVENT_ID"

# KEDA normally wakes the zero-replica relay. In intentionally KEDA-less hybrid
# profiles, temporarily scale the real relay deployment so this integration path
# remains testable without requiring another runtime component.
if ! kubectl -n mreader-admin get scaledobject outbox-relay >/dev/null 2>&1; then
  echo "KEDA outbox-relay ScaledObject absent; temporarily scaling relay to one replica for this probe."
  kubectl -n mreader-admin scale deployment/outbox-relay --replicas=1 >/dev/null
  TEMP_RELAY=1
fi

published=""
for i in $(seq 1 36); do
  published="$(psql_scalar "SELECT COALESCE(published_at::text,'') FROM event_outbox WHERE event_id='$EVENT_ID'::uuid;")"
  [[ -n "$published" ]] && break
  if (( i % 6 == 0 )); then
    kubectl -n mreader-admin get deployment/outbox-relay,pod -l app=outbox-relay -o wide 2>/dev/null || true
  fi
  sleep 5
done
if [[ -z "$published" ]]; then
  echo "FAIL: outbox relay did not receive RabbitMQ publisher confirmation within 180s" >&2
  kubectl -n mreader-admin logs deployment/outbox-relay --tail=200 2>/dev/null || true
  exit 1
fi
echo "PASS: outbox event published_at=$published"

attempts="$(psql_scalar "SELECT attempt_count FROM event_outbox WHERE event_id='$EVENT_ID'::uuid;")"
last_error="$(psql_scalar "SELECT COALESCE(last_error,'') FROM event_outbox WHERE event_id='$EVENT_ID'::uuid;")"
echo -e "event_id\tpublished_at\tattempt_count\tlast_error" > "$OUT/results.tsv"
echo -e "$EVENT_ID\t$published\t$attempts\t${last_error//$'\t'/ }" >> "$OUT/results.tsv"
[[ -z "$last_error" ]] || { echo "FAIL: probe published but retained last_error=$last_error" >&2; exit 1; }

echo "MReader runtime integration: PASS" > "$OUT/SUMMARY.txt"
echo "Run: $RUN_ID" >> "$OUT/SUMMARY.txt"
echo "Event: $EVENT_ID" >> "$OUT/SUMMARY.txt"
echo "Published: $published" >> "$OUT/SUMMARY.txt"
cat "$OUT/SUMMARY.txt"
