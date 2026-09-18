#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose/docker-compose.hybrid-stateful.yml}"
if ! docker compose -f "$COMPOSE_FILE" config --services | grep -qx rabbitmq; then
  echo 'RabbitMQ is external in this mode; refusing to stop it.'; exit 0
fi
docker compose -f "$COMPOSE_FILE" stop rabbitmq
