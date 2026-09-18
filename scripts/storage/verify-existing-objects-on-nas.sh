#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
SAMPLE_COUNT="${1:-30}"
[[ "$SAMPLE_COUNT" =~ ^[0-9]+$ ]] || { echo "sample count must be numeric" >&2; exit 2; }
[[ -f .env ]] || { echo "Missing .env" >&2; exit 1; }
source "$ROOT_DIR/scripts/env/env-lib.sh"
HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"
PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; PORT="${PORT:-8888}"
POSTGRES_USER_VALUE="$(env_get .env POSTGRES_USER)"; POSTGRES_USER_VALUE="${POSTGRES_USER_VALUE:-manhwa}"
POSTGRES_DB_VALUE="$(env_get .env POSTGRES_DB)"; POSTGRES_DB_VALUE="${POSTGRES_DB_VALUE:-manhwa}"
[[ -n "$HOST" ]] || { echo "Set NAS_SEAWEEDFS_HOST in .env" >&2; exit 1; }
BASE="http://$HOST:$PORT"
mapfile -t paths < <(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml exec -T db psql -U "$POSTGRES_USER_VALUE" -d "$POSTGRES_DB_VALUE" -At -c "SELECT image_path FROM pages WHERE image_path IS NOT NULL UNION ALL SELECT responsive_image_path FROM pages WHERE responsive_image_path IS NOT NULL UNION ALL SELECT cover_image_path FROM series WHERE cover_image_path IS NOT NULL LIMIT ${SAMPLE_COUNT};" | sed '/^$/d')
((${#paths[@]} > 0)) || { echo "No stored object paths found in PostgreSQL; nothing to sample." >&2; exit 1; }
ok=0; failed=0
for path in "${paths[@]}"; do
  path="${path#/}"
  if curl -fsS --connect-timeout 5 --max-time 30 -o /dev/null "$BASE/$path"; then printf 'PASS %s
' "$path"; ((ok+=1)); else printf 'FAIL %s
' "$path" >&2; ((failed+=1)); fi
done
echo "Verified objects: ok=$ok failed=$failed sampled=${#paths[@]}"
((failed == 0))
