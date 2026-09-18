#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-status}"
case "$action" in
  enable|disable|status) exec "$ROOT/scripts/hybrid/browser.sh" "$action" ;;
  purge)
    "$ROOT/scripts/hybrid/browser.sh" disable
    docker image rm mreader/scraper-browser:v1.3.0-rc4.84 2>/dev/null || true
    ;;
  *) echo "Usage: $0 {enable|disable|purge|status}" >&2; exit 2 ;;
esac
