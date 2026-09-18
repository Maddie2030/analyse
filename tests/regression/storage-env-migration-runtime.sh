#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ENVF="$TMP/.env"
cat > "$ENVF" <<'ENV'
NAS_SEAWEEDFS_HOST=192.168.1.50
NAS_SEAWEEDFS_PORT=8888
POSTGRES_BACKUP_NAS_PATH=backups/mreader/postgres
POSTGRES_BACKUP_EXPECTED_PHYSICAL_ROOT=/srv/mreader-seaweed/hdd/volume
POSTGRES_BACKUP_DAILY_RETENTION_DAYS=7
POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=14
SECRET_SHOULD_STAY=keep-me
ENV

"$ROOT/scripts/env/migrate-known-settings.sh" "$ENVF" >"$TMP/out.log"
grep -Fxq 'POSTGRES_BACKUP_EXPECTED_PHYSICAL_ROOT=/srv/mreader-seaweed/hdd/volume' "$ENVF"
! grep -q '^POSTGRES_BACKUP_REQUIRE_STORAGE_PROOF=' "$ENVF"
grep -Fxq 'POSTGRES_BACKUP_DAILY_RETENTION_DAYS=4' "$ENVF"
grep -Fxq 'POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS=2' "$ENVF"
grep -Fxq 'MREADER_DB_PROTECTION_CONFIG_VERSION=1' "$ENVF"
grep -Fxq 'SECRET_SHOULD_STAY=keep-me' "$ENVF"
[[ -f "$ENVF.before-rc485-local-recovery" ]]
grep -Fxq 'POSTGRES_BACKUP_DAILY_RETENTION_DAYS=7' "$ENVF.before-rc485-local-recovery"
cp "$ENVF" "$TMP/once"
"$ROOT/scripts/env/migrate-known-settings.sh" "$ENVF" >>"$TMP/out.log"
cmp "$ENVF" "$TMP/once"

echo 'storage env migration runtime regression PASS'
