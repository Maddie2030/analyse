#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
MODE="${1:-${MREADER_MODE:-dev}}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/compose/docker-compose.${MODE}.yml}"
[[ -f "$COMPOSE_FILE" ]] || { echo "ERROR: missing $COMPOSE_FILE" >&2; exit 2; }
DB_USER="${POSTGRES_USER:-manhwa}"
DB_NAME="${POSTGRES_DB:-manhwa}"
docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -P pager=off -c '
  SELECT version, applied_at
  FROM schema_migrations
  ORDER BY version;
'
