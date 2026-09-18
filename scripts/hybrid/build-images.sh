#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
services=(auth_service catalog_go reader_go progress_go social_ts scraper_service image_service frontend outbox_relay notification_worker realtime_go)
compose=(docker compose -f deploy/compose/docker-compose.hybrid-build.yml)
[[ -f .env ]] && compose=(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-build.yml)
"${compose[@]}" build "${services[@]}"
echo "Local Docker Desktop Kubernetes images built for v1.3.0-rc4.84."
