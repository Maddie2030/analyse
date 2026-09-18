#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Validating Caddy configuration..."
MSYS_NO_PATHCONV=1 docker compose exec -T gateway \
  caddy validate --config /etc/caddy/Caddyfile

echo "Reloading Caddy..."
MSYS_NO_PATHCONV=1 docker compose exec -T gateway \
  caddy reload --config /etc/caddy/Caddyfile

echo "Caddy reload completed."
