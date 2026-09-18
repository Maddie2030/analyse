#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

env_ensure_healthy .env .env.example
ADMIN_GATEWAY_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_GATEWAY_PORT="${ADMIN_GATEWAY_PORT:-8081}"
port="$(env_get .env HYBRID_GATEWAY_PORT)"; port="${port:-8080}"

echo '=== Hybrid public USER edge ==='
printf 'Local user gateway: http://127.0.0.1:%s/healthz -> ' "$port"
if curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then echo OK; else echo FAILED; fi

echo "TAILSCALE_PUBLIC_URL=$(env_get .env TAILSCALE_PUBLIC_URL)"
echo "CLOUDFLARE_QUICK_PUBLIC_URL=$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"
echo "PUBLIC_ALLOWED_ORIGINS=$(env_get .env PUBLIC_ALLOWED_ORIGINS)"
echo "ALLOWED_ORIGIN=$(env_get .env ALLOWED_ORIGIN)"
echo "COOKIE_SECURE=$(env_get .env COOKIE_SECURE)"

echo
echo '--- Tailscale Funnel ---'
if command -v tailscale >/dev/null 2>&1; then tailscale funnel status || true
elif [[ -x "/c/Program Files/Tailscale/tailscale.exe" ]]; then "/c/Program Files/Tailscale/tailscale.exe" funnel status || true
else echo 'Tailscale CLI not found'; fi

echo
echo '--- Cloudflare Quick Tunnel ---'
CF=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml)
"${CF[@]}" ps cloudflare_quick || true
url="$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"
if env_public_url_valid "$url"; then
  printf 'Public /healthz: '
  if curl -fsS --connect-timeout 5 --max-time 15 "$url/healthz" >/dev/null 2>&1; then echo OK; else echo DEGRADED; fi
fi

echo "Admin gateway (not tunneled): http://127.0.0.1:${ADMIN_GATEWAY_PORT}"
