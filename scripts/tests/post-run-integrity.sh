#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"

MODE="${1:-}"
SNAPSHOT="${2:-}"
if [[ "$MODE" != "--capture" && "$MODE" != "--verify" ]] || [[ -z "$SNAPSHOT" ]]; then
  echo "Usage: $0 --capture SNAPSHOT_DIR | --verify SNAPSHOT_DIR" >&2
  exit 2
fi
for cmd in docker kubectl awk grep sed; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == "docker-desktop" ]] || { echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2; }

COMPOSE=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml)
PGUSER="$(env_get .env POSTGRES_USER)"; PGUSER="${PGUSER:-mreader}"
PGDB="$(env_get .env POSTGRES_DB)"; PGDB="${PGDB:-mreader}"
mkdir -p "$SNAPSHOT"

psql_scalar(){
  "${COMPOSE[@]}" exec -T db psql -X -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" -Atc "$1" | tr -d '\r' | tail -n1
}

pod_snapshot(){
  kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.name}{":"}{.restartCount}{":"}{.state.waiting.reason}{":"}{.lastState.terminated.reason}{","}{end}{"\n"}{end}' 2>/dev/null | sort
}

metric_snapshot(){
  printf 'stale_outbox\t%s\n' "$(psql_scalar "SELECT count(*) FROM event_outbox WHERE published_at IS NULL AND created_at < now() - interval '5 minutes';")"
  printf 'failed_lifecycle\t%s\n' "$(psql_scalar "SELECT count(*) FROM lifecycle_cleanup_jobs WHERE status='failed';")"
  printf 'stale_lifecycle\t%s\n' "$(psql_scalar "SELECT count(*) FROM lifecycle_cleanup_jobs WHERE status='processing' AND updated_at < now() - interval '5 minutes';")"
  printf 'stale_media\t%s\n' "$(psql_scalar "SELECT count(*) FROM media_operations WHERE status IN ('queued','retry','processing') AND updated_at < now() - interval '5 minutes';")"
  printf 'stale_scraper_batches\t%s\n' "$(psql_scalar "SELECT count(*) FROM scraper_batch_uploads WHERE status IN ('queued','processing') AND updated_at < now() - interval '5 minutes';")"
  printf 'stale_database_operations\t%s\n' "$(psql_scalar "SELECT count(*) FROM database_operations WHERE status='running' AND coalesce(started_at, requested_at) < now() - interval '15 minutes';")"
  printf 'failed_database_operations\t%s\n' "$(psql_scalar "SELECT count(*) FROM database_operations WHERE status='failed';")"
  printf 'test_series\t%s\n' "$(psql_scalar "SELECT count(*) FROM series WHERE slug='mreader-k6-load-series' OR slug LIKE 'browser-reader-%' OR slug LIKE 'e2e-batch-%' OR slug LIKE 'journey-%' OR slug LIKE 'realtime-series-%' OR slug LIKE 'pytest-%' OR slug LIKE 'lifecycle-%';")"
}

rabbit_backlog(){
  local cid
  cid="$("${COMPOSE[@]}" ps -q rabbitmq 2>/dev/null || true)"
  if [[ -z "$cid" ]]; then echo -1; return; fi
  docker exec "$cid" rabbitmqctl -q list_queues name messages_ready messages_unacknowledged 2>/dev/null \
    | awk 'NF>=3 && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {sum += $2+$3} END{print sum+0}'
}

if [[ "$MODE" == "--capture" ]]; then
  "${COMPOSE[@]}" ps db rabbitmq >/dev/null
  pod_snapshot > "$SNAPSHOT/pods.tsv"
  metric_snapshot > "$SNAPSHOT/db-metrics.tsv"
  rabbit_backlog > "$SNAPSHOT/rabbit-backlog.txt"
  date -u +%FT%TZ > "$SNAPSHOT/captured-at.txt"
  echo "Integrity baseline captured: $SNAPSHOT"
  exit 0
fi

[[ -s "$SNAPSHOT/pods.tsv" && -s "$SNAPSHOT/db-metrics.tsv" && -s "$SNAPSHOT/rabbit-backlog.txt" ]] || { echo "ERROR: incomplete integrity baseline: $SNAPSHOT" >&2; exit 2; }
FAIL=0
CURRENT="$SNAPSHOT/current"
mkdir -p "$CURRENT"
pod_snapshot > "$CURRENT/pods.tsv"
metric_snapshot > "$CURRENT/db-metrics.tsv"
rabbit_backlog > "$CURRENT/rabbit-backlog.txt"

# Any current crash state or OOM history is a release failure, regardless of whether
# KEDA created a new pod after the baseline was taken.
if grep -Eq ':(CrashLoopBackOff|Error|ImagePullBackOff|ErrImagePull):|:(OOMKilled|Error),' "$CURRENT/pods.tsv"; then
  echo "FAIL: unhealthy/OOM container state detected after tests" >&2
  grep -E 'CrashLoopBackOff|OOMKilled|ImagePullBackOff|ErrImagePull|:Error' "$CURRENT/pods.tsv" >&2 || true
  FAIL=1
fi

# Same-pod restart counters must never increase. New KEDA/HPA pods are allowed.
while IFS=$'\t' read -r ns pod statuses; do
  [[ -n "$ns" && -n "$pod" ]] || continue
  base_line="$(awk -F '\t' -v n="$ns" -v p="$pod" '$1==n && $2==p{print $3}' "$SNAPSHOT/pods.tsv")"
  [[ -n "$base_line" ]] || continue
  IFS=',' read -ra cur_parts <<< "$statuses"
  for cur in "${cur_parts[@]}"; do
    [[ -n "$cur" ]] || continue
    cname="${cur%%:*}"; rest="${cur#*:}"; cur_restart="${rest%%:*}"
    base_restart="$(printf '%s\n' "$base_line" | tr ',' '\n' | awk -F: -v c="$cname" '$1==c{print $2}')"
    if [[ "$cur_restart" =~ ^[0-9]+$ && "$base_restart" =~ ^[0-9]+$ ]] && (( cur_restart > base_restart )); then
      echo "FAIL: restart count increased for $ns/$pod/$cname: $base_restart -> $cur_restart" >&2
      FAIL=1
    fi
  done
done < "$CURRENT/pods.tsv"

metric_value(){ awk -F '\t' -v k="$1" '$1==k{print $2}' "$2"; }
for key in stale_outbox failed_lifecycle stale_lifecycle stale_media stale_scraper_batches stale_database_operations failed_database_operations test_series; do
  before="$(metric_value "$key" "$SNAPSHOT/db-metrics.tsv")"; after="$(metric_value "$key" "$CURRENT/db-metrics.tsv")"
  before="${before:-0}"; after="${after:-0}"
  if [[ "$before" =~ ^[0-9]+$ && "$after" =~ ^[0-9]+$ ]] && (( after > before )); then
    echo "FAIL: integrity metric $key grew: $before -> $after" >&2
    FAIL=1
  else
    echo "PASS: $key baseline=$before current=$after"
  fi
done

# Give broker consumers a bounded drain window before declaring queue accumulation.
base_q="$(tr -d '\r\n' < "$SNAPSHOT/rabbit-backlog.txt")"; cur_q="$(tr -d '\r\n' < "$CURRENT/rabbit-backlog.txt")"
if [[ "$base_q" =~ ^[0-9]+$ && "$cur_q" =~ ^[0-9]+$ ]] && (( cur_q > base_q )); then
  echo "RabbitMQ backlog $cur_q exceeds baseline $base_q; allowing up to 60s to drain..."
  for _ in 1 2 3 4 5 6; do
    sleep 10
    cur_q="$(rabbit_backlog)"
    (( cur_q <= base_q )) && break
  done
fi
printf '%s\n' "$cur_q" > "$CURRENT/rabbit-backlog.txt"
if [[ "$base_q" =~ ^[0-9]+$ && "$cur_q" =~ ^[0-9]+$ ]] && (( cur_q > base_q )); then
  echo "FAIL: RabbitMQ backlog did not recover: baseline=$base_q current=$cur_q" >&2
  FAIL=1
else
  echo "PASS: RabbitMQ backlog baseline=$base_q current=$cur_q"
fi

kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -100 > "$CURRENT/warning-events.txt" || true
if (( FAIL )); then
  echo "Post-run integrity FAILED. Evidence: $CURRENT" >&2
  exit 1
fi
echo "Post-run integrity PASS. Evidence: $CURRENT"
