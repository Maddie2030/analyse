#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

env_ensure_healthy .env .env.example
STOP_ONLY=false
[[ "${1:-}" == "--stop-only" ]] && STOP_ONLY=true

TAILSCALE_BIN="${TAILSCALE_BIN:-}"
if [[ -z "$TAILSCALE_BIN" ]]; then
  if command -v tailscale >/dev/null 2>&1; then TAILSCALE_BIN="$(command -v tailscale)"
  elif [[ -x "/c/Program Files/Tailscale/tailscale.exe" ]]; then TAILSCALE_BIN="/c/Program Files/Tailscale/tailscale.exe"; fi
fi
https_port="$(env_get .env TAILSCALE_FUNNEL_HTTPS_PORT)"; https_port="${https_port:-443}"
[[ -n "$TAILSCALE_BIN" ]] && "$TAILSCALE_BIN" funnel --https="$https_port" off >/dev/null 2>&1 || true

docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml rm -sf cloudflare_quick >/dev/null 2>&1 || true

echo "Public connectors stopped."

env_set .env TAILSCALE_PUBLIC_URL ""
env_set .env CLOUDFLARE_QUICK_PUBLIC_URL ""
env_rebuild_allowed_origin .env ""
env_set .env COOKIE_SECURE false
$STOP_ONLY && { rm -f .runtime/hybrid-public-edge.env 2>/dev/null || true; exit 0; }

if kubectl get namespace mreader-user >/dev/null 2>&1; then
  "$ROOT/scripts/hybrid/sync-public-edge-secret.sh"
fi
rm -f .runtime/hybrid-public-edge.env 2>/dev/null || true

echo "Public URLs removed from .env/CORS. User gateway remains local at http://127.0.0.1:$(env_get .env HYBRID_GATEWAY_PORT || echo 8080)."
