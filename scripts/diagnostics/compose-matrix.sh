#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
files=(deploy/compose/docker-compose.hybrid-stateful.yml deploy/compose/docker-compose.hybrid-build.yml deploy/compose/docker-compose.hybrid-public-edge.yml)
for file in "${files[@]}"; do
  [[ -f "$file" ]] || { echo "ERROR: missing canonical Compose file: $file" >&2; exit 1; }
  echo "==> docker compose config: $file"
  if [[ -f .env ]]; then docker compose --env-file .env -f "$file" config >/dev/null; else docker compose -f "$file" config >/dev/null; fi
done
echo 'Canonical hybrid Compose validation PASSED'
