#!/usr/bin/env bash
# Explicit destructive resilience probe for the CURRENT Docker Desktop hybrid topology.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
source "$ROOT/scripts/tests/test-runner-common.sh"
[[ "${MREADER_ALLOW_DESTRUCTIVE_TESTS:-0}" == "1" ]] || { echo "ERROR: chaos testing stops RabbitMQ. Re-run with MREADER_ALLOW_DESTRUCTIVE_TESTS=1" >&2; exit 2; }
for cmd in docker kubectl awk grep; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == "docker-desktop" ]] || { echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; OUT="$ROOT/test-results/chaos/$RUN_ID"; mkdir -p "$OUT"
COMPOSE=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml)
PGUSER="$(env_get .env POSTGRES_USER)"; PGUSER="${PGUSER:-mreader}"
PGDB="$(env_get .env POSTGRES_DB)"; PGDB="${PGDB:-mreader}"
EVENT_ID=""; TEMP_RELAY=0
psql_scalar(){ "${COMPOSE[@]}" exec -T db psql -X -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" -Atc "$1" | tr -d '\r' | tail -n1; }
restore(){
  local rc=$?
  echo "Restoring RabbitMQ..."
  "${COMPOSE[@]}" up -d rabbitmq >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do "${COMPOSE[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1 && break; sleep 2; done
  if (( TEMP_RELAY )); then kubectl -n mreader-admin scale deployment/outbox-relay --replicas=0 >/dev/null 2>&1 || true; fi
  [[ -z "$EVENT_ID" ]] || psql_scalar "DELETE FROM event_outbox WHERE event_id='$EVENT_ID'::uuid RETURNING 1;" >/dev/null 2>&1 || true
  exit "$rc"
}
trap restore EXIT
exec > >(tee "$OUT/chaos.log") 2>&1

test_section "RabbitMQ outage: business outbox durability"
"${COMPOSE[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping
"${COMPOSE[@]}" stop rabbitmq
if "${COMPOSE[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; then echo "FAIL: RabbitMQ still reachable after stop" >&2; exit 1; fi
EVENT_ID="$(psql_scalar "SELECT enqueue_event_outbox_v1('audit.created','test.chaos.rabbitmq',1,'test','chaos-$RUN_ID','chaos-$RUN_ID','test-harness',jsonb_build_object('run_id','$RUN_ID'));" )"
[[ "$EVENT_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "FAIL: no outbox UUID" >&2; exit 1; }
sleep 15
published="$(psql_scalar "SELECT COALESCE(published_at::text,'') FROM event_outbox WHERE event_id='$EVENT_ID'::uuid;")"
[[ -z "$published" ]] || { echo "FAIL: event was marked published while RabbitMQ was down" >&2; exit 1; }
echo "PASS: business/outbox commit survived broker outage and remains unpublished"

test_section "RabbitMQ recovery: relay retries durable event"
"${COMPOSE[@]}" up -d rabbitmq
for i in $(seq 1 45); do
  "${COMPOSE[@]}" exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1 && break
  (( i == 45 )) && { echo "FAIL: RabbitMQ did not become healthy" >&2; exit 1; }
  sleep 2
done
if ! kubectl -n mreader-admin get scaledobject outbox-relay >/dev/null 2>&1; then
  kubectl -n mreader-admin scale deployment/outbox-relay --replicas=1 >/dev/null; TEMP_RELAY=1
fi
for i in $(seq 1 36); do
  published="$(psql_scalar "SELECT COALESCE(published_at::text,'') FROM event_outbox WHERE event_id='$EVENT_ID'::uuid;")"
  [[ -n "$published" ]] && break
  sleep 5
done
[[ -n "$published" ]] || { echo "FAIL: durable event did not publish after broker recovery" >&2; kubectl -n mreader-admin logs deployment/outbox-relay --tail=200 2>/dev/null || true; exit 1; }
echo "PASS: event published after broker recovery at $published"
echo -e "event_id\tstate\tpublished_at\n$EVENT_ID\tPASS\t$published" > "$OUT/results.tsv"
printf 'MReader chaos run: %s\nRabbitMQ durability/recovery: PASS\n' "$RUN_ID" > "$OUT/SUMMARY.txt"
cat "$OUT/SUMMARY.txt"
