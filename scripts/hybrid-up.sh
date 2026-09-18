#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

banner(){ printf '\n==> %s\n' "$*"; }
fail(){ echo "ERROR: $*" >&2; exit 2; }

banner "MReader Docker Desktop hybrid bootstrap"

# Upgrade-friendly config reuse. Release archives intentionally never contain .env
# because it carries credentials and site-specific NAS/public-edge settings. When a
# newly extracted RC directory has no .env, import the newest sibling hybrid RC .env
# instead of silently falling back to .env.example. This keeps upgrades idempotent
# while still refusing to deploy with placeholder defaults when no prior config exists.
if [[ ! -f .env ]]; then
  parent_dir="$(dirname "$ROOT")"
  prior_env=""
  newest_mtime=0
  shopt -s nullglob
  prior_candidates=(
    "$parent_dir"/mreader-v1.3.0-rc4.*-docker-desktop-hybrid-dual-public-edge/.env
    "$parent_dir"/mreader-v1.3.0-rc4.*-docker-desktop-hybrid-twin-plane/.env
    "$parent_dir"/mreader-rc4*/.env
    "$parent_dir"/mreader-rc*/.env
  )
  shopt -u nullglob
  for candidate in "${prior_candidates[@]}"; do
    [[ "$candidate" != "$ROOT/.env" ]] || continue
    [[ -f "$candidate" ]] || continue
    candidate_size="$(_env_size "$candidate")"
    [[ "$candidate_size" =~ ^[0-9]+$ ]] || continue
    (( candidate_size > 0 && candidate_size <= MREADER_ENV_MAX_BYTES )) || continue
    candidate_mtime="$(stat -c '%Y' "$candidate" 2>/dev/null || echo 0)"
    [[ "$candidate_mtime" =~ ^[0-9]+$ ]] || candidate_mtime=0
    if (( candidate_mtime >= newest_mtime )); then
      newest_mtime="$candidate_mtime"
      prior_env="$candidate"
    fi
  done
  if [[ -n "$prior_env" ]]; then
    cp "$prior_env" .env
    chmod 600 .env 2>/dev/null || true
    echo "Imported existing hybrid configuration from: $prior_env"
  else
    fail ".env is missing and no prior sibling hybrid release .env was found. Copy your previous release .env into this directory (preferred), or copy .env.example to .env and configure all required secrets/NAS values."
  fi
fi
env_ensure_healthy .env .env.example
"$ROOT/scripts/env/migrate-known-settings.sh" .env
"$ROOT/scripts/hybrid/ensure-private-transport-secrets.sh" .env
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT
command -v docker >/dev/null 2>&1 || fail "docker CLI not found. Start/install Docker Desktop."
command -v kubectl >/dev/null 2>&1 || fail "kubectl not found. Enable Kubernetes in Docker Desktop."
docker info >/dev/null 2>&1 || fail "Docker Engine is not ready. Start Docker Desktop."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required."
"$ROOT/scripts/hybrid/adopt-existing-stateful-volumes.sh" .env

ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ "$ctx" != "docker-desktop" ]]; then
  if kubectl config get-contexts -o name 2>/dev/null | grep -Fxq docker-desktop; then
    banner "Switching kubectl context to docker-desktop"
    kubectl config use-context docker-desktop >/dev/null
  else
    fail "Docker Desktop Kubernetes context is unavailable. Enable Kubernetes in Docker Desktop first."
  fi
fi
kubectl get node docker-desktop >/dev/null 2>&1 || fail "Docker Desktop Kubernetes node is not Ready."

banner "Validating hybrid configuration"
"$ROOT/scripts/hybrid/validate.sh"

banner "Creating/reconciling Docker + Kubernetes resources"
"$ROOT/scripts/hybrid/deploy.sh"

public_edges="$(env_get .env HYBRID_PUBLIC_EDGES)"
public_edges="${public_edges:-both}"
if [[ "$public_edges" == "none" ]]; then
  banner "Keeping hybrid gateway local-only"
  "$ROOT/scripts/hybrid/public-down.sh" || true
else
  banner "Starting hybrid public development edges: $public_edges"
  if ! "$ROOT/scripts/hybrid/public-up.sh" "$public_edges"; then
    public_required="$(env_get .env HYBRID_PUBLIC_REQUIRED)"
    if [[ "$public_required" == "true" ]]; then
      fail "No requested public edge became available and HYBRID_PUBLIC_REQUIRED=true."
    fi
    echo "WARNING: public-edge startup failed; local hybrid deployment remains healthy at http://127.0.0.1:8080" >&2
  fi
fi

banner "Final status"
"$ROOT/scripts/hybrid/status.sh" || true

echo
echo "Hybrid deployment completed successfully."
echo "User gateway:  http://localhost:8080
Admin gateway: http://localhost:8081 (local/private only)"
echo "Public user edge mode: ${public_edges:-none}"

tailscale_public_url="$(env_get .env TAILSCALE_PUBLIC_URL)"
cloudflare_public_url="$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"
if env_public_url_valid "$tailscale_public_url"; then
  echo "Tailscale Funnel: $tailscale_public_url"
else
  echo "Tailscale Funnel: not active"
fi
if env_public_url_valid "$cloudflare_public_url"; then
  echo "Cloudflare Quick Tunnel: $cloudflare_public_url"
else
  echo "Cloudflare Quick Tunnel: not active"
fi

echo "Image edge (host-only): http://127.0.0.1:${HYBRID_IMAGE_EDGE_PORT:-18081}"
echo "Stateful host services: PostgreSQL, Valkey/Redis, RabbitMQ, Image Edge"
echo "Kubernetes: mreader-user serves readers; mreader-admin handles ingestion/publishing; browser scraper starts at 0 replicas"
echo "SeaweedFS: external/NAS"
echo "Reprint public URLs any time: ./scripts/hybrid/public-status.sh"
