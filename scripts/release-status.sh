#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "MReader v$(cat VERSION)"
echo 'Current route ownership:'
echo '  /api/auth/*           -> auth_service   (FastAPI)'
echo '  /api/catalog/*        -> catalog_go     (Go)'
echo '  /api/reader/*         -> reader_go      (Go)'
echo '  /api/progress/*       -> progress_go    (Go)'
echo '  /api/social/*         -> social_ts      (TypeScript/Fastify)'
echo '  /api/notifications/*  -> social_ts      (TypeScript/Fastify)'
echo '  /api/upload/*         -> image_service  (FastAPI)'
echo '  /api/scraper/*        -> scraper_service(FastAPI)'
echo '  staging               -> Docker volume mreader_scraper_staging'
echo '  final media           -> SeaweedFS / configured NAS'
