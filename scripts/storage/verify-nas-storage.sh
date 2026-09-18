#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] || { echo "Missing .env" >&2; exit 1; }
source "$ROOT_DIR/scripts/env/env-lib.sh"
HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"
PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; PORT="${PORT:-8888}"
[[ -n "$HOST" ]] || { echo "Set NAS_SEAWEEDFS_HOST in .env" >&2; exit 1; }
URL="http://$HOST:$PORT"
echo "Host -> NAS Filer: $URL"
curl -fsS --connect-timeout 5 "$URL/" >/dev/null
echo "PASS: host can reach NAS Filer"
if kubectl -n mreader-admin get deployment scraper-service >/dev/null 2>&1; then
  kubectl -n mreader-admin exec deploy/scraper-service -- python -c 'import os,urllib.request; u=os.environ["CHECK_URL"].rstrip("/")+"/"; r=urllib.request.urlopen(u,timeout=5); assert r.status < 400; print("PASS: Kubernetes scraper-service can reach NAS Filer")' --env="CHECK_URL=$URL" 2>/dev/null || {
    kubectl -n mreader-admin exec deploy/scraper-service -- python -c "import urllib.request; r=urllib.request.urlopen('$URL/',timeout=5); assert r.status < 400; print('PASS: Kubernetes scraper-service can reach NAS Filer')"
  }
else
  echo "INFO: mreader-admin/scraper-service is not running; Kubernetes path check skipped."
fi
