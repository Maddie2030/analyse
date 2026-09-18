#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
COMPOSE=deploy/compose/docker-compose.hybrid-stateful.yml
fail(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "$COMPOSE" ]] || fail "canonical hybrid stateful Compose file missing"
[[ -x scripts/hybrid/adopt-existing-stateful-volumes.sh ]] || fail "one-time stateful volume adoption helper missing"

for spec in \
  'pgdata|HYBRID_PGDATA_VOLUME_NAME|mreader_pgdata' \
  'redis_data|HYBRID_REDIS_VOLUME_NAME|mreader_redis_data' \
  'rabbitmq_data|HYBRID_RABBITMQ_VOLUME_NAME|mreader_rabbitmq_data' \
  'image_cache|HYBRID_IMAGE_CACHE_VOLUME_NAME|mreader_image_cache'; do
  IFS='|' read -r key envkey fallback <<<"$spec"
  grep -Fq "name: \${${envkey}:-${fallback}}" "$COMPOSE" || fail "missing selectable volume mapping $key -> $envkey/$fallback"
done

grep -Fq '${MREADER_DB_PROTECTION_ROOT:?MREADER_DB_PROTECTION_ROOT is required}:/mreader-db-protection' "$COMPOSE" || fail "host-local PostgreSQL recovery mount is missing"
! grep -Fq 'select_volume HYBRID_BACKUP_SPOOL_VOLUME_NAME' scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "retired backup spool is still adopted as a runtime owner"

grep -Fq 'mreader-hybrid-stateful_pgdata' scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "legacy PostgreSQL volume is not recognized by upgrade adoption"
grep -Fq 'MREADER_PREFER_LEGACY_STATEFUL_VOLUMES' scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "legacy-first adoption policy control missing"
grep -Fq "preferring legacy volume" scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "populated legacy state is not preferred during upgrade"
grep -Fq 'postgres_volume_valid' scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "PostgreSQL adoption does not validate PGDATA contents"

echo "hybrid explicit volume ownership/adoption regression PASSED"
