#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/env/env-lib.sh"
FILE="${1:-$ROOT/.env}"
[[ -f "$FILE" && ! -L "$FILE" ]] || { echo "ERROR: a regular environment file is required." >&2; exit 2; }
for key in MREADER_DB_PROTECTION_CONFIG_VERSION POSTGRES_BACKUP_DAILY_RETENTION_DAYS POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS; do
  count="$(awk -F= -v key="$key" '$1==key {n++} END {print n+0}' "$FILE")"
  [[ "$count" -le 1 ]] || { echo "ERROR: resolve duplicate $key assignments before configuration migration." >&2; exit 2; }
done
version="$(env_get "$FILE" MREADER_DB_PROTECTION_CONFIG_VERSION)"
case "$version" in
  1) echo "Host-local recovery configuration is current."; exit 0 ;;
  '') ;;
  *) echo "ERROR: unsupported recovery configuration version." >&2; exit 2 ;;
esac
backup="${FILE}.before-rc485-local-recovery"
[[ ! -L "$backup" ]] || { echo "ERROR: configuration backup cannot be a symlink." >&2; exit 2; }
if [[ ! -e "$backup" ]]; then
  cp -p "$FILE" "$backup"
  chmod 600 "$backup"
fi
[[ -f "$backup" ]] || { echo "ERROR: configuration backup is not a regular file." >&2; exit 2; }
working="$(mktemp "${FILE}.rc485.XXXXXXXX")"
trap 'rm -f "$working"' EXIT
cp "$FILE" "$working"
chmod 600 "$working"
# Only missing values and the known RC4.81 defaults change once. Existing NAS
# keys remain dormant import evidence; no runtime proof requirement is added.
logical="$(env_get "$FILE" POSTGRES_BACKUP_DAILY_RETENTION_DAYS)"
snapshot="$(env_get "$FILE" POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS)"
if [[ -z "$logical" || "$logical" == 7 ]]; then
  env_set "$working" POSTGRES_BACKUP_DAILY_RETENTION_DAYS 4
fi
if [[ -z "$snapshot" || "$snapshot" == 14 ]]; then
  env_set "$working" POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS 2
fi
env_set "$working" MREADER_DB_PROTECTION_CONFIG_VERSION 1
mv "$working" "$FILE"
echo "Migrated known recovery defaults; custom settings and the original configuration are preserved."
