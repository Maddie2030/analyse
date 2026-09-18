#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

env_ensure_healthy .env .env.example
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required" >&2; exit 2; }

allowed="$(env_get .env ALLOWED_ORIGIN)"
[[ -n "$allowed" ]] || allowed="$MREADER_LOCAL_ORIGINS"
cookie_secure="$(env_get .env COOKIE_SECURE)"
[[ "$cookie_secure" == "true" || "$cookie_secure" == "false" ]] || cookie_secure=false
public_allowed="$(env_get .env PUBLIC_ALLOWED_ORIGINS)"
public_base="$(env_get .env PUBLIC_BASE_URLS)"
tailscale_url="$(env_get .env TAILSCALE_PUBLIC_URL)"
cloudflare_url="$(env_get .env CLOUDFLARE_QUICK_PUBLIC_URL)"

kubectl get namespace mreader-user >/dev/null 2>&1 || { echo "ERROR: mreader-user namespace does not exist" >&2; exit 2; }

kubectl -n mreader-user create secret generic mreader-public-edge \
  --from-literal=ALLOWED_ORIGIN="$allowed" \
  --from-literal=COOKIE_SECURE="$cookie_secure" \
  --from-literal=PUBLIC_ALLOWED_ORIGINS="$public_allowed" \
  --from-literal=PUBLIC_BASE_URLS="$public_base" \
  --from-literal=TAILSCALE_PUBLIC_URL="$tailscale_url" \
  --from-literal=CLOUDFLARE_QUICK_PUBLIC_URL="$cloudflare_url" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "Synced mreader-public-edge secret."

if [[ "${1:-}" != "--no-rollout" ]]; then
  kubectl -n mreader-user rollout restart deployment/auth-service deployment/reader-go >/dev/null
  kubectl -n mreader-user rollout status deployment/auth-service --timeout=180s
  kubectl -n mreader-user rollout status deployment/reader-go --timeout=180s
fi
