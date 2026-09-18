#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/mreader-legacy-volume-priority.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
cp .env.example "$TMP/env"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
cmd="${1:-}"; shift || true
case "$cmd" in
  info) exit 0 ;;
  volume)
    [[ "${1:-}" == inspect ]] || exit 1
    name="${2:-}"
    if [[ "$name" == *backup_spool* ]]; then touch "$MREADER_TEST_BACKUP_VOLUME_TOUCHED"; fi
    case "$name" in
      mreader_pgdata|mreader-hybrid-stateful_pgdata|\
      mreader_redis_data|mreader-hybrid-stateful_redis_data|\
      mreader_rabbitmq_data|mreader-hybrid-stateful_rabbitmq_data|\
      mreader_image_cache|mreader-hybrid-stateful_image_cache|\
      mreader_backup_spool|mreader-hybrid-stateful_backup_spool) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  run)
    # Every canonical and legacy volume in this scenario contains data/valid PGDATA.
    exit 0
    ;;
  *) exit 1 ;;
esac
MOCK
chmod +x "$TMP/bin/docker"
cat > "$TMP/inspect.sh" <<'MOCK_INSPECT'
#!/usr/bin/env bash
for v in "$@"; do
  cat <<OUT
volume=$v
exists=yes
pgdata_valid=yes
catalog_state=contains_mreader_catalog
OUT
done
MOCK_INSPECT
chmod +x "$TMP/inspect.sh"

MREADER_TEST_BACKUP_VOLUME_TOUCHED="$TMP/backup-volume-touched" \
PATH="$TMP/bin:$PATH" MREADER_PG_VOLUME_INSPECTOR="$TMP/inspect.sh" \
  scripts/hybrid/adopt-existing-stateful-volumes.sh "$TMP/env" >/dev/null

for expected in \
  'HYBRID_PGDATA_VOLUME_NAME=mreader-hybrid-stateful_pgdata' \
  'HYBRID_REDIS_VOLUME_NAME=mreader-hybrid-stateful_redis_data' \
  'HYBRID_RABBITMQ_VOLUME_NAME=mreader-hybrid-stateful_rabbitmq_data' \
  'HYBRID_IMAGE_CACHE_VOLUME_NAME=mreader-hybrid-stateful_image_cache'; do
  grep -qx "$expected" "$TMP/env" || { echo "FAIL: legacy volume was not preferred: $expected" >&2; cat "$TMP/env" >&2; exit 1; }
done
[[ ! -e "$TMP/backup-volume-touched" ]] || { echo 'FAIL: runtime adoption touched a retired backup spool' >&2; exit 1; }
! grep -q '^HYBRID_BACKUP_SPOOL_VOLUME_NAME=' "$TMP/env"

echo 'hybrid legacy-volume priority regression PASSED'
