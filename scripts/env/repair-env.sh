#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh
ENV_FILE="${1:-.env}"
env_ensure_healthy "$ENV_FILE" .env.example

# Preserve only syntactically valid public HTTPS URLs and rebuild the concrete
# Reader origin allow-list. This prevents logs/CLI output from ever becoming CORS data.
public=()
for key in TAILSCALE_PUBLIC_URL CLOUDFLARE_QUICK_PUBLIC_URL; do
  v="$(env_get "$ENV_FILE" "$key")"
  if env_public_url_valid "$v"; then public+=("$v"); else [[ -z "$v" ]] || env_set "$ENV_FILE" "$key" ""; fi
done
csv="$(IFS=,; echo "${public[*]:-}")"
env_rebuild_allowed_origin "$ENV_FILE" "$csv"

echo "Environment repair complete."
echo "Size: $(_env_size "$ENV_FILE") bytes"
echo "ALLOWED_ORIGIN=$(env_get "$ENV_FILE" ALLOWED_ORIGIN)"
echo "PUBLIC_ALLOWED_ORIGINS=$(env_get "$ENV_FILE" PUBLIC_ALLOWED_ORIGINS)"
