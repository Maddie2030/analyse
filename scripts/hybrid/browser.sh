#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
action="${1:-status}"
case "$action" in
  enable)
    docker build -f services/scraper_service/Dockerfile.browser -t mreader/scraper-browser:v1.3.0-rc4.84 .
    kubectl -n mreader-admin scale deployment/scraper-browser --replicas=1
    kubectl -n mreader-admin set env deployment/scraper-service deployment/scraper-batch-worker deployment/scraper-series-worker SCRAPER_BROWSER_FALLBACK_ENABLED=true SCRAPER_BROWSER_REMOTE_URL=http://scraper-browser:8010
    kubectl -n mreader-admin rollout status deployment/scraper-browser --timeout=240s
    ;;
  disable)
    kubectl -n mreader-admin set env deployment/scraper-service deployment/scraper-batch-worker deployment/scraper-series-worker SCRAPER_BROWSER_FALLBACK_ENABLED=false SCRAPER_BROWSER_REMOTE_URL-
    kubectl -n mreader-admin scale deployment/scraper-browser --replicas=0
    ;;
  status) kubectl -n mreader-admin get deployment scraper-browser scraper-service scraper-batch-worker scraper-series-worker ;;
  *) echo "usage: $0 {enable|disable|status}" >&2; exit 2;;
esac
