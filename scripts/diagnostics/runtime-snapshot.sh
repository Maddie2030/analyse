#!/usr/bin/env bash
set -u
OUT="${1:?output directory required}"
mkdir -p "$OUT"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
{
  echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "version=$(cat VERSION 2>/dev/null || true)"
  docker version 2>&1 || true
  docker compose version 2>&1 || true
} > "$OUT/docker-version.txt"

docker compose ps -a > "$OUT/compose-ps.txt" 2>&1 || true
docker compose images > "$OUT/compose-images.txt" 2>&1 || true
PROJECT="$(docker compose config --format json 2>/dev/null | sed -n 's/.*"name":"\([^"]*\)".*/\1/p' | head -1)"
[[ -n "$PROJECT" ]] || PROJECT="mreader"
mapfile -t project_ids < <(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)
if [[ ${#project_ids[@]} -gt 0 ]]; then
  docker stats --no-stream "${project_ids[@]}" > "$OUT/docker-stats.txt" 2>&1 || true
else
  echo "No containers found for Compose project $PROJECT" > "$OUT/docker-stats.txt"
fi

echo -e 'service\tcontainer\tstatus\thealth\trestarts\toom_killed\texit_code\tstarted_at\tfinished_at' > "$OUT/container-state.tsv"
for id in "${project_ids[@]}"; do
  [[ -n "$id" ]] || continue
  service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id" 2>/dev/null || true)"
  docker inspect --format "${service}\t{{.Name}}\t{{.State.Status}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\t{{.RestartCount}}\t{{.State.OOMKilled}}\t{{.State.ExitCode}}\t{{.State.StartedAt}}\t{{.State.FinishedAt}}" "$id" >> "$OUT/container-state.tsv" 2>/dev/null || true
done

docker compose logs --no-color --tail=300 > "$OUT/compose-logs-tail.txt" 2>&1 || true

# Proxy syntax is valuable even when HTTP tests pass.
MSYS_NO_PATHCONV=1 docker compose exec -T gateway caddy validate --config /etc/caddy/Caddyfile > "$OUT/caddy-validate.txt" 2>&1 || true
docker compose exec -T image_edge nginx -t > "$OUT/nginx-validate.txt" 2>&1 || true

DB_USER="${POSTGRES_USER:-manhwa}"; DB_NAME="${POSTGRES_DB:-manhwa}"
{
  echo '--- schema_migrations ---'
  docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -F '|' -c "SELECT version,applied_at FROM schema_migrations ORDER BY version;" 2>&1 || true
  echo '--- outbox by type/state ---'
  docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -F '|' -c "SELECT event_type,CASE WHEN published_at IS NULL THEN 'pending' ELSE 'published' END,count(*) FROM event_outbox GROUP BY 1,2 ORDER BY 1,2;" 2>&1 || true
  echo '--- core row counts ---'
  docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -F '|' -c "SELECT 'users',count(*) FROM users UNION ALL SELECT 'series',count(*) FROM series UNION ALL SELECT 'chapters',count(*) FROM chapters UNION ALL SELECT 'pages',count(*) FROM pages UNION ALL SELECT 'reading_progress',count(*) FROM reading_progress UNION ALL SELECT 'notifications',count(*) FROM notifications UNION ALL SELECT 'notification_event_receipts',count(*) FROM notification_event_receipts;" 2>&1 || true
} > "$OUT/database.txt"

{
  echo '--- Valkey info memory ---'
  docker compose exec -T redis valkey-cli INFO memory 2>&1 | grep -E '^(used_memory_human|maxmemory_human|maxmemory_policy|mem_fragmentation_ratio):' || true
  echo '--- Valkey progress stream ---'
  typ="$(docker compose exec -T redis valkey-cli --raw TYPE progress:updates 2>/dev/null | tr -d '\r' || true)"
  if [[ "$typ" == "stream" ]]; then
    echo "progress:updates|$(docker compose exec -T redis valkey-cli --raw XLEN progress:updates 2>/dev/null | tr -d '\r' || true)"
  else
    echo 'progress:updates|0'
  fi
} > "$OUT/queues.txt"

{
  echo '--- RabbitMQ queues ---'
  if docker compose config --services 2>/dev/null | grep -qx rabbitmq; then
    docker compose exec -T rabbitmq rabbitmqctl -q list_queues -p "${RABBITMQ_VHOST:-mreader}" name type messages_ready messages_unacknowledged consumers 2>&1 || true
  else
    echo 'external RabbitMQ: queue introspection not collected by Docker diagnostics'
  fi
} > "$OUT/rabbitmq.txt"
