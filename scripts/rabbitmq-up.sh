#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose/docker-compose.hybrid-stateful.yml}"
if ! docker compose -f "$COMPOSE_FILE" config --services | grep -qx rabbitmq; then
  echo 'RabbitMQ is external in this mode; nothing to start locally.'; exit 0
fi
docker compose -f "$COMPOSE_FILE" up -d rabbitmq
for _ in $(seq 1 90); do
  if docker compose -f "$COMPOSE_FILE" exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; then echo 'RabbitMQ healthy'; exit 0; fi
  sleep 2
done
docker compose -f "$COMPOSE_FILE" logs --tail=200 rabbitmq
exit 1
