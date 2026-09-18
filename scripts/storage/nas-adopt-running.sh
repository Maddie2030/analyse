#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

command -v docker >/dev/null 2>&1 || { echo 'ERROR: docker is required.' >&2; exit 2; }
volume_c="$(docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-(volume-hdd|volume)$' | head -n1 || true)"
filer_c="$(docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-filer$' | head -n1 || true)"
master_c="$(docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-master$' | head -n1 || true)"
[[ -n "$volume_c" && -n "$filer_c" && -n "$master_c" ]] || { echo 'ERROR: expected running MReader SeaweedFS master/filer/volume containers were not found.' >&2; exit 3; }

mount_src(){ docker inspect "$1" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'; }
volume_dir="$(mount_src "$volume_c")"
filer_dir="$(mount_src "$filer_c")"
master_dir="$(mount_src "$master_c")"
[[ "$volume_dir" == /* && "$filer_dir" == /* && "$master_dir" == /* ]] || { echo 'ERROR: could not resolve bind sources.' >&2; exit 3; }
workdir="$(docker inspect "$volume_c" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)"
env_file="${NAS_ADOPT_ENV_FILE:-${workdir:+$workdir/.env}}"
[[ -n "$env_file" ]] || env_file="$ROOT_DIR/ops/nas-seaweedfs/.env"

hdd_mount="$(findmnt -T "$volume_dir" -no TARGET 2>/dev/null || true)"
hdd_source="$(findmnt -T "$volume_dir" -no SOURCE 2>/dev/null || true)"
ssd_mount="$(findmnt -T "$filer_dir" -no TARGET 2>/dev/null || true)"

cat <<INFO
Detected running MReader SeaweedFS layout:
  compose_workdir=$workdir
  env_file=$env_file
  NAS_VOLUME_DATA_DIR=$volume_dir
  NAS_FILER_DATA_DIR=$filer_dir
  NAS_MASTER_DATA_DIR=$master_dir
  volume_mountpoint=$hdd_mount
  volume_device=$hdd_source
  filer_mountpoint=$ssd_mount
INFO

if ! $APPLY; then
  cat <<'INFO'

Dry run only. No files were changed.
To update the active NAS .env to exactly match these running bind sources and publish storage proof, rerun:
  ./scripts/storage/nas-adopt-running.sh --apply
INFO
  exit 0
fi

[[ -f "$env_file" ]] || { echo "ERROR: active NAS env file does not exist: $env_file" >&2; exit 4; }
backup="$env_file.before-rc451-$(date '+%Y%m%d-%H%M%S')"
cp -a "$env_file" "$backup"
set_value(){
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$env_file"; then
    sed -i -E "s#^${key}=.*#${key}=${value}#" "$env_file"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$env_file"
  fi
}
set_value NAS_VOLUME_DATA_DIR "$volume_dir"
set_value NAS_FILER_DATA_DIR "$filer_dir"
set_value NAS_MASTER_DATA_DIR "$master_dir"
[[ -z "$hdd_mount" ]] || set_value NAS_HDD_ROOT "$hdd_mount"
[[ -z "$ssd_mount" ]] || set_value NAS_SSD_ROOT "$ssd_mount"
set_value POSTGRES_BACKUP_NAS_PATH "${POSTGRES_BACKUP_NAS_PATH:-backups/mreader/postgres}"
set_value NAS_SEAWEEDFS_PORT "${NAS_SEAWEEDFS_PORT:-8888}"

echo "Updated active NAS env safely. Backup copy: $backup"
"$ROOT_DIR/ops/nas-seaweedfs/storage-contract.sh" "$env_file" publish
