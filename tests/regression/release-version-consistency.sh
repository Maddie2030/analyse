#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

version="$(tr -d '\r\n' < VERSION)"
[[ "$version" =~ ^1\.3\.0-rc4\.[0-9]+$ ]] || { echo "FAIL: unexpected VERSION=$version" >&2; exit 1; }
tag="v${version}"

require() { grep -Fq -- "$2" "$1" || { echo "FAIL: $1 missing $2" >&2; exit 1; }; }
require frontend/package.json "\"version\": \"${version}\""
require services/social_ts/package.json "\"version\": \"${version}\""
require deploy/compose/docker-compose.hybrid-stateful.yml "MREADER_VERSION: ${tag}"

for file in deploy/compose/docker-compose.hybrid-build.yml deploy/docker-desktop-hybrid/user-apps.yaml deploy/docker-desktop-hybrid/admin-apps.yaml; do
  stale="$(grep -Eo 'mreader/[A-Za-z0-9._-]+:v1\.3\.0-rc4\.[0-9]+' "$file" | grep -Fv ":${tag}" || true)"
  [[ -z "$stale" ]] || { echo "FAIL: stale MReader image tags in $file:" >&2; printf '%s\n' "$stale" >&2; exit 1; }
done

# Exact forms differ slightly between one-line and multiline FastAPI declarations.
grep -Fq "version=\"${version}\"" services/thumbnail_transformer/app/main.py
grep -Fq "version=\"${version}\"" services/scraper_service/app/browser_service.py
grep -Fq "version=\"${version}\"" services/scraper_service/app/main.py
grep -Fq "version=\"${version}\"" services/image_service/app/main.py

echo "release version consistency PASS: ${version}"
