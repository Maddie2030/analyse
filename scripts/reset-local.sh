#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE=dev
YES=0
DELETE_STAGING=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:?mode required}"; shift 2 ;;
    --yes) YES=1; shift ;;
    --including-staging) DELETE_STAGING=1; shift ;;
    -h|--help)
      echo 'Usage: ./scripts/reset-local.sh [--mode dev] [--yes] [--including-staging]'
      echo 'Default: remove disposable Compose volumes while preserving scraper staging.'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
CF="deploy/compose/docker-compose.${MODE}.yml"
[[ -f "$CF" ]] || { echo "Missing $CF" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo 'ERROR: Docker is required.' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo 'ERROR: Docker Compose v2 is required.' >&2; exit 1; }
STAGING_VOLUME="$(sed -n 's/^SCRAPER_STAGING_VOLUME_NAME=//p' .env 2>/dev/null | tail -n1 | tr -d '\r')"
STAGING_VOLUME="${STAGING_VOLUME:-mreader_scraper_staging}"

if (( DELETE_STAGING )); then
  echo 'DANGER: this removes all selected-mode volumes INCLUDING unpublished scraper staging.'
else
  echo "This removes disposable '$MODE' Compose volumes but preserves scraper staging volume '$STAGING_VOLUME'."
fi
if (( ! YES )); then
  read -r -p 'Type RESET to continue: ' answer
  [[ "$answer" == RESET ]] || { echo 'Cancelled.'; exit 0; }
fi

# Stop containers first, but do not ask Compose to delete every named volume.
docker compose -f "$CF" down --remove-orphans

project="$(sed -n 's/^name:[[:space:]]*//p' "$CF" | head -n1 | tr -d '\r\"' | xargs)"
project="${project:-mreader}"
mapfile -t ids < <(docker volume ls -q --filter "label=com.docker.compose.project=$project")
for id in "${ids[@]}"; do
  [[ -n "$id" ]] || continue
  if (( ! DELETE_STAGING )) && [[ "$id" == "$STAGING_VOLUME" ]]; then
    echo "PRESERVE $id"
    continue
  fi
  echo "REMOVE   $id"
  docker volume rm "$id" >/dev/null || true
done

# Explicitly named volumes can lose Compose labels after manual restoration.
if (( DELETE_STAGING )) && docker volume inspect "$STAGING_VOLUME" >/dev/null 2>&1; then
  docker volume rm "$STAGING_VOLUME" >/dev/null
fi
