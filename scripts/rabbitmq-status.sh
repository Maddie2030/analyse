#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose/docker-compose.hybrid-stateful.yml}"
if docker compose -f "$COMPOSE_FILE" config --services | grep -qx rabbitmq; then
  docker compose -f "$COMPOSE_FILE" exec -T rabbitmq rabbitmq-diagnostics -q ping
  docker compose -f "$COMPOSE_FILE" exec -T rabbitmq rabbitmqctl -q list_queues -p "${RABBITMQ_VHOST:-mreader}" name type messages_ready messages_unacknowledged consumers
else
  echo 'RabbitMQ is external for this deployment mode.'
  docker compose -f "$COMPOSE_FILE" exec -T scraper_service python - <<'PY'
import asyncio, os, aio_pika
async def main():
    c=await aio_pika.connect_robust(os.environ['RABBITMQ_URL'], timeout=8); await c.close(); print('RabbitMQ connection: PASS')
asyncio.run(main())
PY
fi
