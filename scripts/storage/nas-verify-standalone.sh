#!/usr/bin/env bash
set -euo pipefail

# Standalone, non-disruptive verifier for an already-running MReader SeaweedFS NAS.
# It inspects Docker bind mounts + findmnt and publishes storage proof through the
# local Filer. It never restarts containers, creates storage directories, or moves data.
BACKUP_PATH="${1:-${POSTGRES_BACKUP_NAS_PATH:-backups/mreader/postgres}}"
BACKUP_PATH="/${BACKUP_PATH#/}"; BACKUP_PATH="${BACKUP_PATH%/}"
[[ "$BACKUP_PATH" == /backups/* && "$BACKUP_PATH" != *'/../'* && "$BACKUP_PATH" != */.. ]] || {
  echo 'ERROR: backup path must stay below backups/ and contain no ..' >&2; exit 2;
}
for cmd in docker findmnt curl jq awk; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: required command missing: $cmd" >&2; exit 2; }
done

find_container(){ docker ps --format '{{.Names}}' | grep -E "$1" | head -n1 || true; }
volume_c="$(find_container '^mreader-seaweed-(volume-hdd|volume)$')"
filer_c="$(find_container '^mreader-seaweed-filer$')"
master_c="$(find_container '^mreader-seaweed-master$')"
[[ -n "$volume_c" && -n "$filer_c" && -n "$master_c" ]] || {
  echo 'ERROR: running MReader SeaweedFS master/filer/volume containers were not found.' >&2; exit 3;
}
mount_src(){ docker inspect "$1" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true; }
volume_dir="$(mount_src "$volume_c")"
filer_dir="$(mount_src "$filer_c")"
master_dir="$(mount_src "$master_c")"
[[ "$volume_dir" == /* && "$filer_dir" == /* && "$master_dir" == /* ]] || {
  echo 'ERROR: expected bind-mounted /data sources were not found.' >&2; exit 3;
}

root_source="$(findmnt -T / -no SOURCE)"
hdd_source="$(findmnt -T "$volume_dir" -no SOURCE 2>/dev/null || true)"
hdd_target="$(findmnt -T "$volume_dir" -no TARGET 2>/dev/null || true)"
hdd_fstype="$(findmnt -T "$volume_dir" -no FSTYPE 2>/dev/null || true)"
ssd_source="$(findmnt -T "$filer_dir" -no SOURCE 2>/dev/null || true)"
ssd_target="$(findmnt -T "$filer_dir" -no TARGET 2>/dev/null || true)"
[[ -n "$hdd_source" && "$hdd_source" != "$root_source" && "$hdd_target" != "/" ]] || {
  echo 'ERROR: active SeaweedFS volume /data bind is not on a dedicated mounted filesystem.' >&2; exit 4;
}

port_line="$(docker port "$filer_c" 8888/tcp 2>/dev/null | head -n1 || true)"
filer_port="${port_line##*:}"
[[ "$filer_port" =~ ^[0-9]+$ ]] || filer_port=8888
filer="http://127.0.0.1:${filer_port}"
curl -fsS --connect-timeout 3 --max-time 10 "$filer/" >/dev/null || {
  echo 'ERROR: local SeaweedFS Filer is not reachable.' >&2; exit 5;
}

compose_workdir="$(docker inspect "$volume_c" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)"
config_volume_dir="$volume_dir"
if [[ -n "$compose_workdir" && -f "$compose_workdir/.env" ]]; then
  explicit="$(awk -F= '$1=="NAS_VOLUME_DATA_DIR"{sub(/^[^=]*=/,"");print;exit}' "$compose_workdir/.env" | tr -d '\r' || true)"
  [[ -z "$explicit" ]] || config_volume_dir="$explicit"
fi
config_match=false
[[ "${config_volume_dir%/}" == "${volume_dir%/}" ]] && config_match=true

proof="$(mktemp)"; trap 'rm -f "$proof"' EXIT
jq -n \
  --arg verified_at_utc "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --arg physical_volume_root "$volume_dir" \
  --arg configured_physical_volume_root "$config_volume_dir" \
  --arg volume_container "$volume_c" \
  --arg mount_source "$hdd_source" \
  --arg mountpoint "$hdd_target" \
  --arg filesystem "$hdd_fstype" \
  --arg root_filesystem_source "$root_source" \
  --arg ssd_filer_root "$filer_dir" \
  --arg ssd_mount_source "$ssd_source" \
  --arg ssd_master_root "$master_dir" \
  --arg logical_backup_root "$BACKUP_PATH" \
  --arg verification_source 'running-container-bind' \
  --arg compose_workdir "$compose_workdir" \
  --argjson runtime_mount_matches_config "$config_match" \
  '{verified:true,verified_at_utc:$verified_at_utc,physical_volume_root:$physical_volume_root,
    configured_physical_volume_root:$configured_physical_volume_root,
    runtime_mount_matches_config:$runtime_mount_matches_config,volume_container:$volume_container,
    mount_source:$mount_source,mountpoint:$mountpoint,filesystem:$filesystem,
    root_filesystem_source:$root_filesystem_source,ssd_filer_root:$ssd_filer_root,
    ssd_mount_source:$ssd_mount_source,ssd_master_root:$ssd_master_root,
    logical_backup_root:$logical_backup_root,verification_source:$verification_source,
    compose_workdir:$compose_workdir}' > "$proof"

curl -fsS --retry 4 --retry-all-errors -F "file=@${proof}" "$filer${BACKUP_PATH}/storage-location.json" >/dev/null
curl -fsS "$filer${BACKUP_PATH}/storage-location.json" | jq -e '.verified == true' >/dev/null

echo 'NAS physical-storage verification published successfully.'
echo 'No SeaweedFS container was restarted and no existing data was moved.'
