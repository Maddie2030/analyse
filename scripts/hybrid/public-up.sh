#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

env_ensure_healthy .env .env.example
./scripts/env/repair-env.sh .env >/dev/null

EDGES="${1:-$(env_get .env HYBRID_PUBLIC_EDGES)}"
EDGES="${EDGES:-both}"
case "$EDGES" in both|tailscale|cloudflare|none) ;; *) echo "ERROR: edge mode must be both, tailscale, cloudflare, or none" >&2; exit 2;; esac
if [[ "$EDGES" == "none" ]]; then
  exec "$ROOT/scripts/hybrid/public-down.sh"
fi

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required" >&2; exit 2; }
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required" >&2; exit 2; }

ctx="$(kubectl config current-context 2>/dev/null || true)"
[[ "$ctx" == "docker-desktop" ]] || { echo "ERROR: kubectl context must be docker-desktop (current: ${ctx:-<none>})" >&2; exit 2; }

GATEWAY_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; GATEWAY_PORT="${GATEWAY_PORT:-8080}"
ADMIN_GATEWAY_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_GATEWAY_PORT="${ADMIN_GATEWAY_PORT:-8081}"
[[ "$GATEWAY_PORT" =~ ^[0-9]+$ && "$ADMIN_GATEWAY_PORT" =~ ^[0-9]+$ ]] || { echo "ERROR: gateway ports must be numeric" >&2; exit 2; }
[[ "$GATEWAY_PORT" != "$ADMIN_GATEWAY_PORT" ]] || { echo "ERROR: public user gateway port must differ from private admin gateway port" >&2; exit 2; }
[[ "$GATEWAY_PORT" == "8080" ]] || { echo "ERROR: HYBRID_GATEWAY_PORT must be 8080 for this twin-plane manifest" >&2; exit 2; }
[[ "$ADMIN_GATEWAY_PORT" == "8081" ]] || { echo "ERROR: HYBRID_ADMIN_GATEWAY_PORT must be 8081 for this twin-plane manifest" >&2; exit 2; }
LOCAL_GATEWAY="http://127.0.0.1:${GATEWAY_PORT}"
if ! curl -fsS --retry 20 --retry-all-errors --retry-delay 1 --connect-timeout 2 --max-time 5 "$LOCAL_GATEWAY/healthz" >/dev/null; then
  echo "ERROR: hybrid user gateway is not healthy at $LOCAL_GATEWAY/healthz" >&2
  kubectl -n mreader-user get pods,svc -o wide >&2 || true
  kubectl -n mreader-user logs deployment/user-gateway --tail=120 >&2 || true
  exit 3
fi

mkdir -p .runtime
CF_COMPOSE=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml)

TAILSCALE_BIN="${TAILSCALE_BIN:-}"
if [[ -z "$TAILSCALE_BIN" ]]; then
  if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_BIN="$(command -v tailscale)"
  elif [[ -x "/c/Program Files/Tailscale/tailscale.exe" ]]; then
    TAILSCALE_BIN="/c/Program Files/Tailscale/tailscale.exe"
  fi
fi

cf_stop() { "${CF_COMPOSE[@]}" rm -sf cloudflare_quick >/dev/null 2>&1 || true; }
cf_logs() { "${CF_COMPOSE[@]}" logs --no-color --tail 240 cloudflare_quick 2>&1 || true; }
cf_running() {
  local id
  id="$("${CF_COMPOSE[@]}" ps -a -q cloudflare_quick 2>/dev/null || true)"
  [[ -n "$id" ]] || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "$id" 2>/dev/null || true)" == "true" ]]
}

want_ts=false; want_cf=false
[[ "$EDGES" == "both" || "$EDGES" == "tailscale" ]] && want_ts=true
[[ "$EDGES" == "both" || "$EDGES" == "cloudflare" ]] && want_cf=true

# Exact selection semantics: disabled edges are stopped and removed from CORS.
if ! $want_cf; then cf_stop; env_set .env CLOUDFLARE_QUICK_PUBLIC_URL ""; fi
if ! $want_ts; then
  off_port="$(env_get .env TAILSCALE_FUNNEL_HTTPS_PORT)"; off_port="${off_port:-443}"
  [[ -n "$TAILSCALE_BIN" ]] && "$TAILSCALE_BIN" funnel --https="$off_port" off >/dev/null 2>&1 || true
  env_set .env TAILSCALE_PUBLIC_URL ""
fi

env_set .env HYBRID_GATEWAY_PORT "$GATEWAY_PORT"
env_set .env LOCAL_GATEWAY_PORT "$GATEWAY_PORT"
[[ -n "$(env_get .env TAILSCALE_FUNNEL_HTTPS_PORT)" ]] || env_set .env TAILSCALE_FUNNEL_HTTPS_PORT 443
[[ -n "$(env_get .env CLOUDFLARED_PROTOCOL)" ]] || env_set .env CLOUDFLARED_PROTOCOL http2
[[ -n "$(env_get .env CLOUDFLARE_QUICK_STARTUP_TIMEOUT_SECONDS)" ]] || env_set .env CLOUDFLARE_QUICK_STARTUP_TIMEOUT_SECONDS 120
[[ -n "$(env_get .env CLOUDFLARE_QUICK_PUBLIC_PROBE_SECONDS)" ]] || env_set .env CLOUDFLARE_QUICK_PUBLIC_PROBE_SECONDS 90

# Rebuild from strict, known local origins before discovering public hostnames.
env_rebuild_allowed_origin .env ""
env_set .env TAILSCALE_PUBLIC_URL ""
env_set .env CLOUDFLARE_QUICK_PUBLIC_URL ""

origins=(); warnings=(); tailscale_url=""; cloudflare_url=""; cloudflare_probe="not-requested"

if $want_ts; then
  if [[ -z "$TAILSCALE_BIN" ]]; then
    warnings+=("Tailscale CLI not found (checked PATH and /c/Program Files/Tailscale/tailscale.exe)")
  else
    status_json="$("$TAILSCALE_BIN" status --json 2>/dev/null || true)"
    dns_name="$(printf '%s\n' "$status_json" | grep -o '"DNSName"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | cut -d'"' -f4 | sed 's/\.$//' || true)"
    if [[ -z "$dns_name" ]]; then
      warnings+=("Tailscale is not connected or MagicDNS hostname is unavailable")
    else
      candidate="https://${dns_name}"
      if ! env_public_url_valid "$candidate"; then
        warnings+=("Tailscale returned an invalid public hostname")
      else
        https_port="$(env_get .env TAILSCALE_FUNNEL_HTTPS_PORT)"; https_port="${https_port:-443}"
        echo "==> Enabling Tailscale Funnel: $candidate"
        if "$TAILSCALE_BIN" funnel --bg --https="$https_port" "$LOCAL_GATEWAY"; then
          tailscale_url="$candidate"
          origins+=("$candidate")
          env_set .env TAILSCALE_PUBLIC_URL "$candidate"
        else
          warnings+=("Tailscale Funnel failed; verify HTTPS certificates/Funnel permission")
        fi
      fi
    fi
  fi
fi

if $want_cf; then
  echo "==> Starting Cloudflare Quick Tunnel to Docker Desktop Kubernetes gateway (transport: $(env_get .env CLOUDFLARED_PROTOCOL))"
  cf_stop
  if "${CF_COMPOSE[@]}" up -d --force-recreate cloudflare_quick; then
    startup_seconds="$(env_get .env CLOUDFLARE_QUICK_STARTUP_TIMEOUT_SECONDS)"
    [[ "$startup_seconds" =~ ^[0-9]+$ ]] || startup_seconds=120
    loops=$(( startup_seconds * 2 )); (( loops < 2 )) && loops=2
    for ((i=0; i<loops; i++)); do
      candidate="$(cf_logs | grep -Eo 'https://[A-Za-z0-9-]+\.trycloudflare\.com' | head -n1 || true)"
      if [[ -n "$candidate" ]] && env_public_url_valid "$candidate"; then cloudflare_url="$candidate"; break; fi
      if ! cf_running; then break; fi
      sleep 0.5
    done
    cf_logs > .runtime/cloudflare-hybrid.log || true
    if [[ -n "$cloudflare_url" ]] && cf_running; then
      env_set .env CLOUDFLARE_QUICK_PUBLIC_URL "$cloudflare_url"
      origins+=("$cloudflare_url")
      probe_seconds="$(env_get .env CLOUDFLARE_QUICK_PUBLIC_PROBE_SECONDS)"
      [[ "$probe_seconds" =~ ^[0-9]+$ ]] || probe_seconds=90
      deadline=$((SECONDS + probe_seconds)); cloudflare_probe="degraded"
      while (( SECONDS < deadline )); do
        if curl -fsS --connect-timeout 5 --max-time 10 "$cloudflare_url/healthz" >/dev/null 2>&1; then cloudflare_probe="ok"; break; fi
        sleep 2
      done
      if [[ "$cloudflare_probe" != "ok" ]]; then
        warnings+=("Cloudflare Quick Tunnel is running and added to CORS, but its external /healthz probe is still degraded; see .runtime/cloudflare-hybrid.log")
      fi
    elif [[ -n "$cloudflare_url" ]]; then
      env_set .env CLOUDFLARE_QUICK_PUBLIC_URL ""
      cloudflare_url=""
      warnings+=("Cloudflare Quick Tunnel emitted a URL but the connector exited; see .runtime/cloudflare-hybrid.log")
    else
      warnings+=("Cloudflare Quick Tunnel did not emit a valid trycloudflare.com URL; see .runtime/cloudflare-hybrid.log")
      cf_stop
    fi
  else
    warnings+=("Cloudflare Quick Tunnel container failed to start")
  fi
fi

if (( ${#origins[@]} == 0 )); then
  env_rebuild_allowed_origin .env ""
  env_set .env COOKIE_SECURE false
  "$ROOT/scripts/hybrid/sync-public-edge-secret.sh" || true
  echo "ERROR: no requested public edge started; local hybrid deployment remains available at $LOCAL_GATEWAY" >&2
  (( ${#warnings[@]} > 0 )) && printf '  - %s\n' "${warnings[@]}" >&2
  exit 1
fi

public_csv=""
for origin in "${origins[@]}"; do
  [[ ",$public_csv," == *",$origin,"* ]] && continue
  public_csv="${public_csv:+$public_csv,}$origin"
done
env_rebuild_allowed_origin .env "$public_csv"
env_set .env COOKIE_SECURE true

# Only auth-service (Secure session cookie) and reader-go (origin allow-list)
# need a rollout. The main mreader-env secret and NAS wiring remain untouched.
"$ROOT/scripts/hybrid/sync-public-edge-secret.sh"

{
  printf 'PUBLIC_ALLOWED_ORIGINS=%s\n' "$public_csv"
  printf 'ALLOWED_ORIGIN=%s\n' "$(env_get .env ALLOWED_ORIGIN)"
  printf 'COOKIE_SECURE=%s\n' "$(env_get .env COOKIE_SECURE)"
  printf 'TAILSCALE_PUBLIC_URL=%s\n' "$(env_get .env TAILSCALE_PUBLIC_URL)"
  printf 'CLOUDFLARE_QUICK_PUBLIC_URL=%s\n' "$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"
  printf 'CLOUDFLARE_QUICK_PROBE=%s\n' "$cloudflare_probe"
} > .runtime/hybrid-public-edge.env

echo
echo "MReader hybrid public development edges are configured."
echo "Local user gateway: $LOCAL_GATEWAY"
if [[ -n "$tailscale_url" ]]; then echo "Tailscale Funnel: $tailscale_url"; else echo "Tailscale Funnel: not active"; fi
if [[ -n "$cloudflare_url" ]]; then echo "Cloudflare Quick Tunnel: $cloudflare_url"; else echo "Cloudflare Quick Tunnel: not active"; fi
echo "CORS ALLOWED_ORIGIN: $(env_get .env ALLOWED_ORIGIN)"
echo "Session COOKIE_SECURE: $(env_get .env COOKIE_SECURE)"
[[ -n "$cloudflare_url" ]] && echo "Cloudflare public probe: $cloudflare_probe"
if (( ${#warnings[@]} > 0 )); then
  echo "WARNING: one edge may be degraded/unavailable; any successful edge remains usable." >&2
  printf '  - %s\n' "${warnings[@]}" >&2
fi
