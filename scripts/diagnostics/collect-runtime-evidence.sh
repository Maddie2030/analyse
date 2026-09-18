#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
# env-lib enables errexit for ordinary operational scripts. Diagnostics is
# best-effort by design: collector failures belong in collector-errors.tsv.
set +e
PHASE="${1:?phase required (before|after)}"; RUN_DIR="${2:?run directory required}"
case "$PHASE" in before|after) ;; *) echo "ERROR: invalid diagnostics phase $PHASE" >&2; exit 2;; esac
SNAP="$RUN_DIR/snapshot/$PHASE"; POD_LOG_ROOT="$RUN_DIR/logs/pods/$PHASE"; ERRORS="$SNAP/collector-errors.tsv"
mkdir -p "$SNAP" "$POD_LOG_ROOT"; printf 'collector\texit_code\tmessage\n' > "$ERRORS"
record_error(){ local name="$1" rc="$2" message="$3"; printf '%s\t%s\t%s\n' "$name" "$rc" "${message//$'\t'/ }" >> "$ERRORS"; }
capture(){ local name="$1" outfile="$2"; shift 2; "$@" > "$outfile" 2>&1; local rc=$?; [[ $rc -eq 0 ]] || record_error "$name" "$rc" "see ${outfile#$RUN_DIR/}"; return 0; }

capture kubectl-nodes "$SNAP/nodes.txt" kubectl get nodes -o wide
capture kubectl-namespaces "$SNAP/namespaces.txt" kubectl get namespaces
capture kubectl-warning-events "$SNAP/warning-events.txt" kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
capture kubectl-events "$SNAP/events.txt" kubectl get events -A --sort-by=.lastTimestamp
for ns in mreader-user mreader-admin; do
  NSDIR="$SNAP/$ns"; mkdir -p "$NSDIR"
  capture "$ns-pods" "$NSDIR/pods.txt" kubectl -n "$ns" get pods -o wide
  capture "$ns-pods-json" "$NSDIR/pods.json" kubectl -n "$ns" get pods -o json
  capture "$ns-deployments" "$NSDIR/deployments.txt" kubectl -n "$ns" get deployments -o wide
  capture "$ns-services" "$NSDIR/services.txt" kubectl -n "$ns" get services -o wide
  capture "$ns-hpa" "$NSDIR/hpa.txt" kubectl -n "$ns" get hpa -o wide
  capture "$ns-scaledobjects" "$NSDIR/scaledobjects.txt" kubectl -n "$ns" get scaledobjects -o wide
  pods="$(kubectl -n "$ns" get pods -o name 2>/dev/null)"; pod_rc=$?
  if [[ $pod_rc -ne 0 ]]; then record_error "$ns-pod-enumeration" "$pod_rc" 'could not enumerate pods'; continue; fi
  while IFS= read -r podref; do
    [[ -n "$podref" ]] || continue; pod="${podref#pod/}"; PDIR="$POD_LOG_ROOT/$ns/$pod"; mkdir -p "$PDIR"
    capture "$ns-$pod-describe" "$PDIR/describe.txt" kubectl -n "$ns" describe pod "$pod"
    capture "$ns-$pod-current-log" "$PDIR/current.log" kubectl -n "$ns" logs "$pod" --all-containers=true --timestamps --tail="${MREADER_DIAGNOSTICS_LOG_TAIL:-2000}"
    kubectl -n "$ns" logs "$pod" --all-containers=true --previous --timestamps --tail="${MREADER_DIAGNOSTICS_LOG_TAIL:-2000}" > "$PDIR/previous.log" 2>&1; prev_rc=$?
    if [[ $prev_rc -ne 0 ]]; then printf 'previous log unavailable (kubectl exit %s)\n' "$prev_rc" >> "$PDIR/previous.log"; fi
  done <<< "$pods"
done
capture docker-ps "$SNAP/docker-ps.txt" docker ps -a
capture docker-stats "$SNAP/docker-stats.txt" docker stats --no-stream
capture docker-info "$SNAP/docker-info.txt" docker info
COMPOSE_FILE="$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml"
if [[ -f "$COMPOSE_FILE" && -f "$ROOT/.env" ]]; then
  capture compose-ps "$SNAP/compose-ps.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" ps -a
  capture compose-logs "$SNAP/compose-logs.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" logs --tail=250
fi
container_ids="$(docker ps -aq --filter 'name=mreader' 2>/dev/null)"
if [[ -n "$container_ids" ]]; then
  while IFS= read -r cid; do
    [[ -n "$cid" ]] || continue; name="$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##')"; [[ -n "$name" ]] || name="$cid"; safe="${name//[^A-Za-z0-9_.-]/_}"
    capture "docker-inspect-$safe" "$SNAP/docker-inspect-$safe.txt" docker inspect -f 'name={{.Name}} image={{.Config.Image}} restart_count={{.RestartCount}} state={{json .State}} memory_limit={{.HostConfig.Memory}} nano_cpus={{.HostConfig.NanoCpus}} networks={{json .NetworkSettings.Networks}}' "$cid"
  done <<< "$container_ids"
fi
if [[ -f "$COMPOSE_FILE" && -f "$ROOT/.env" ]]; then
  PG_USER="$(env_get "$ROOT/.env" POSTGRES_USER)"
  PG_DB="$(env_get "$ROOT/.env" POSTGRES_DB)"
  capture postgres-connectivity "$SNAP/postgres-connectivity.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT current_database(), current_user, version();"'
  capture postgres-schema-migrations "$SNAP/postgres-schema-migrations.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 30;"'
  capture postgres-runtime-counts "$SNAP/postgres-runtime-counts.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T db psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" -Atc "SELECT 'event_outbox'::text AS rel, count(*)::bigint AS cnt FROM event_outbox UNION ALL SELECT 'ingestion_operations', count(*)::bigint FROM ingestion_operations UNION ALL SELECT 'database_operations', count(*)::bigint FROM database_operations ORDER BY rel;"
  capture rabbitmq-health "$SNAP/rabbitmq-health.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T rabbitmq rabbitmq-diagnostics -q ping
  capture rabbitmq-queues "$SNAP/rabbitmq-queues.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers state
  capture valkey-primary-health "$SNAP/valkey-primary-health.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T redis valkey-cli ping
  capture valkey-primary-memory "$SNAP/valkey-primary-memory.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T redis valkey-cli info memory
  capture valkey-primary-dbsize "$SNAP/valkey-primary-dbsize.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T redis valkey-cli dbsize
  capture valkey-cache-health "$SNAP/valkey-cache-health.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T redis_cache valkey-cli ping
  capture valkey-cache-memory "$SNAP/valkey-cache-memory.txt" docker compose --env-file "$ROOT/.env" -f "$COMPOSE_FILE" exec -T redis_cache valkey-cli info memory
fi
USER_PORT="$(env_get "$ROOT/.env" HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get "$ROOT/.env" HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
NAS_HOST="$(env_get "$ROOT/.env" NAS_SEAWEEDFS_HOST)"; NAS_PORT="$(env_get "$ROOT/.env" NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
capture gateway-user-health "$SNAP/gateway-user-health.txt" curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz"
capture gateway-admin-health "$SNAP/gateway-admin-health.txt" curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz"
if [[ -n "$NAS_HOST" ]]; then capture seaweedfs-health "$SNAP/seaweedfs-health.txt" curl -fsS --connect-timeout 3 --max-time 8 "http://${NAS_HOST}:${NAS_PORT}/"; else record_error seaweedfs-health 2 'NAS_SEAWEEDFS_HOST is not configured'; fi
exit 0
