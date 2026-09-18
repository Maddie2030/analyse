#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source ./scripts/env/env-lib.sh
env_ensure_healthy .env .env.example
port="$(env_get .env HYBRID_GATEWAY_PORT)"; port="${port:-8080}"
url="$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"
CF=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml)

echo 'Cloudflare Quick Tunnel diagnostics (Docker Desktop hybrid)'
printf 'Local Kubernetes gateway /healthz: '
if curl -fsS --max-time 5 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then echo OK; else echo FAILED; fi
echo "Configured URL: ${url:-<none>}"
echo "Transport: $(env_get .env CLOUDFLARED_PROTOCOL)"
id="$("${CF[@]}" ps -a -q cloudflare_quick 2>/dev/null || true)"
if [[ -n "$id" ]]; then docker inspect "$id" --format 'container={{.Name}} running={{.State.Running}} status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' || true
else echo 'cloudflare_quick container: absent'; fi
mkdir -p .runtime
"${CF[@]}" logs --no-color --tail 250 cloudflare_quick 2>&1 | tee .runtime/cloudflare-hybrid.log || true
if env_public_url_valid "$url"; then
  echo '--- public /healthz probe ---'
  curl -4 -v --connect-timeout 10 --max-time 20 "$url/healthz" || true
fi
