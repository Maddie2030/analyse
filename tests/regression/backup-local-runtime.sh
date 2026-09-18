#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/recovery"

make_fake() {
  local name="$1"
  shift
  printf '#!/usr/bin/env bash\n%s\n' "$*" > "$TMP/bin/$name"
  chmod 0755 "$TMP/bin/$name"
}

make_fake pg_isready 'exit 0'
make_fake pg_dump 'printf "PGDMP-local-backup-data"'
make_fake pg_dumpall 'printf "%s\n" "-- PostgreSQL globals" "CREATE ROLE mreader;"'
make_fake pg_restore 'exit 0'
make_fake pg_basebackup '
destination=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-D" ]]; then shift; destination="$1"; fi
  shift || true
done
mkdir -p "$destination"
printf "base" > "$destination/base.tar.gz"
printf "wal" > "$destination/pg_wal.tar.gz"'
make_fake psql '
args="$*"
input="$(cat || true)"
if [[ "$args" == *"server_version_num"* ]]; then printf "160010\n"
elif [[ "$args" == *"show server_version"* ]]; then printf "16.10\n"
elif [[ "$args" == *"schema_migrations"* ]]; then printf "049_database_recovery_points.sql\n"
elif [[ "$args" == *"count(*) from series"* ]]; then printf "1,2,3\n"
fi
exit 0'
make_fake curl 'printf "%s\n" "$*" >> "$DBP_CURL_LOG"; exit 99'
make_fake mreader-recovery-bridge '[[ "${1:-}" == "healthcheck" ]] || exit 2; exit 0'

PATH="$TMP/bin:$PATH" \
POSTGRES_HOST=db \
POSTGRES_PORT=5432 \
POSTGRES_USER=mreader \
POSTGRES_PASSWORD=secret \
POSTGRES_DB=mreader \
POSTGRES_BACKUP_LOCAL_ROOT="$TMP/recovery" \
POSTGRES_BACKUP_SPOOL="$TMP/recovery/staging/backup-agent" \
MREADER_LOCAL_RECOVERY_STORE="$ROOT/scripts/backup/local-recovery-store.sh" \
MREADER_SYNC_RECOVERY_CATALOG="$ROOT/scripts/backup/sync-local-recovery-catalog.sh" \
DBP_CURL_LOG="$TMP/curl.log" \
MREADER_VERSION=v1.3.0-rc4.85 \
bash "$ROOT/scripts/backup/backup-agent.sh" manual runtime-test > "$TMP/output.log"

mapfile -t bundles < <(find "$TMP/recovery/dumps/manual" -mindepth 1 -maxdepth 1 -type d -print)
[[ ${#bundles[@]} -eq 1 ]] || { echo "expected one local manual recovery bundle" >&2; exit 1; }
bundle="${bundles[0]}"
[[ -s "$bundle/database.dump" ]] || { echo "local database dump missing" >&2; exit 1; }
[[ -s "$bundle/globals.sql" ]] || { echo "PostgreSQL globals missing" >&2; exit 1; }
"$ROOT/scripts/backup/local-recovery-store.sh" verify-bundle "$bundle" >/dev/null
manual_public_id="$(jq -r '.public_id // empty' "$TMP/recovery/staging/backup-agent/state/latest-daily.json")"
[[ "$manual_public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || { echo "manual operation handoff is missing the catalog public id" >&2; exit 1; }

PATH="$TMP/bin:$PATH" \
POSTGRES_HOST=db \
POSTGRES_PORT=5432 \
POSTGRES_USER=mreader \
POSTGRES_PASSWORD=secret \
POSTGRES_DB=mreader \
POSTGRES_REPLICATION_USER=mreader_backup \
POSTGRES_REPLICATION_PASSWORD=secret \
POSTGRES_BACKUP_LOCAL_ROOT="$TMP/recovery" \
POSTGRES_BACKUP_SPOOL="$TMP/recovery/staging/backup-agent" \
MREADER_LOCAL_RECOVERY_STORE="$ROOT/scripts/backup/local-recovery-store.sh" \
MREADER_SYNC_RECOVERY_CATALOG="$ROOT/scripts/backup/sync-local-recovery-catalog.sh" \
DBP_CURL_LOG="$TMP/curl.log" \
MREADER_VERSION=v1.3.0-rc4.85 \
bash "$ROOT/scripts/backup/backup-agent.sh" snapshot > "$TMP/snapshot-output.log"

mapfile -t snapshots < <(find "$TMP/recovery/snapshots" -mindepth 1 -maxdepth 1 -type d -print)
[[ ${#snapshots[@]} -eq 1 ]] || { echo "expected one local physical snapshot bundle" >&2; exit 1; }
"$ROOT/scripts/backup/local-recovery-store.sh" verify-bundle "${snapshots[0]}" >/dev/null
snapshot_public_id="$(jq -r '.public_id // empty' "$TMP/recovery/staging/backup-agent/state/latest-snapshots.json")"
[[ "$snapshot_public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || { echo "snapshot operation handoff is missing the catalog public id" >&2; exit 1; }
[[ ! -s "$TMP/curl.log" ]] || { cat "$TMP/curl.log" >&2; echo "local backup contacted NAS" >&2; exit 1; }

PATH="$TMP/bin:$PATH" \
POSTGRES_HOST=db \
POSTGRES_PORT=5432 \
POSTGRES_USER=mreader \
POSTGRES_PASSWORD=secret \
POSTGRES_DB=mreader \
POSTGRES_BACKUP_LOCAL_ROOT="$TMP/recovery" \
POSTGRES_BACKUP_SPOOL="$TMP/recovery/staging/backup-agent" \
MREADER_LOCAL_RECOVERY_STORE="$ROOT/scripts/backup/local-recovery-store.sh" \
MREADER_RECOVERY_BRIDGE_BIN="$TMP/bin/mreader-recovery-bridge" \
RECOVERY_BRIDGE_TOKEN=test-recovery-bridge-token \
DBP_CURL_LOG="$TMP/curl.log" \
bash "$ROOT/scripts/backup/backup-agent.sh" health

echo "backup agent local dump/snapshot runtime contract PASS"
