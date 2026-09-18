#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-}"
MODE="${2:-publish}"

case "$MODE" in
  check|publish|check-running|publish-running) ;;
  *) echo "ERROR: mode must be check, publish, check-running, or publish-running" >&2; exit 2 ;;
esac
RUNNING_MODE=false
[[ "$MODE" == *-running ]] && RUNNING_MODE=true
PUBLISH=false
[[ "$MODE" == publish* ]] && PUBLISH=true

if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
elif [[ -n "$ENV_FILE" && ! -f "$ENV_FILE" ]]; then
  echo "WARNING: NAS env file not found: $ENV_FILE; inspecting running SeaweedFS mounts instead." >&2
fi

for cmd in findmnt curl awk docker jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: required command missing: $cmd" >&2; exit 2; }
done

BIND_IP="${NAS_BIND_IP:-127.0.0.1}"
FILER_PORT="${NAS_SEAWEEDFS_PORT:-8888}"
BACKUP_PATH="${POSTGRES_BACKUP_NAS_PATH:-backups/mreader/postgres}"
HDD_ROOT="${NAS_HDD_ROOT:-/srv/seaweed/hdd}"
SSD_ROOT="${NAS_SSD_ROOT:-/srv/seaweed/ssd/meta}"
CONFIG_VOLUME_DIR="${NAS_VOLUME_DATA_DIR:-${HDD_ROOT%/}/volumes}"
CONFIG_MASTER_DIR="${NAS_MASTER_DATA_DIR:-${SSD_ROOT%/}/master}"
CONFIG_FILER_DIR="${NAS_FILER_DATA_DIR:-${SSD_ROOT%/}/filer}"

valid_abs(){ [[ "$1" == /* && "$1" != *'/../'* && "$1" != */.. ]]; }
for pair in \
  "NAS_HDD_ROOT:$HDD_ROOT" \
  "NAS_SSD_ROOT:$SSD_ROOT" \
  "NAS_VOLUME_DATA_DIR:$CONFIG_VOLUME_DIR" \
  "NAS_MASTER_DATA_DIR:$CONFIG_MASTER_DIR" \
  "NAS_FILER_DATA_DIR:$CONFIG_FILER_DIR"; do
  name="${pair%%:*}"; value="${pair#*:}"
  valid_abs "$value" || { echo "ERROR: $name must be an absolute path without '..' (got '$value')." >&2; exit 2; }
done
[[ "$FILER_PORT" =~ ^[0-9]+$ ]] && (( FILER_PORT >= 1 && FILER_PORT <= 65535 )) || { echo "ERROR: NAS_SEAWEEDFS_PORT must be 1-65535." >&2; exit 2; }
BACKUP_PATH="/${BACKUP_PATH#/}"; BACKUP_PATH="${BACKUP_PATH%/}"
[[ "$BACKUP_PATH" == /backups/* && "$BACKUP_PATH" != *'/../'* && "$BACKUP_PATH" != */.. ]] || { echo "ERROR: POSTGRES_BACKUP_NAS_PATH must stay under backups/ and contain no '..'." >&2; exit 2; }

find_volume_container(){ docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-(volume-hdd|volume)$' | head -n1 || true; }
find_filer_container(){ docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-filer$' | head -n1 || true; }
find_master_container(){ docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-master$' | head -n1 || true; }
mount_source_for_data(){
  local c="$1"
  [[ -n "$c" ]] || return 0
  docker inspect "$c" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true
}
compose_workdir_for(){
  local c="$1"
  [[ -n "$c" ]] || return 0
  docker inspect "$c" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true
}
published_filer_port(){
  local c="$1" line port
  [[ -n "$c" ]] || return 0
  line="$(docker port "$c" 8888/tcp 2>/dev/null | head -n1 || true)"
  port="${line##*:}"
  [[ "$port" =~ ^[0-9]+$ ]] && printf '%s\n' "$port"
}

volume_container="$(find_volume_container)"
filer_container="$(find_filer_container)"
master_container="$(find_master_container)"
runtime_volume_dir="$(mount_source_for_data "$volume_container")"
runtime_filer_dir="$(mount_source_for_data "$filer_container")"
runtime_master_dir="$(mount_source_for_data "$master_container")"
compose_workdir="$(compose_workdir_for "$volume_container")"

if $RUNNING_MODE; then
  [[ -n "$volume_container" && -n "$runtime_volume_dir" ]] || { echo "ERROR: running MReader SeaweedFS volume container with a /data bind mount was not found." >&2; exit 3; }
  [[ -n "$filer_container" ]] || { echo "ERROR: running MReader SeaweedFS filer container was not found." >&2; exit 3; }
  valid_abs "$runtime_volume_dir" || { echo "ERROR: running SeaweedFS /data source is not a safe absolute path." >&2; exit 3; }
  VOLUME_DIR="$runtime_volume_dir"
  FILER_DIR="${runtime_filer_dir:-$CONFIG_FILER_DIR}"
  MASTER_DIR="${runtime_master_dir:-$CONFIG_MASTER_DIR}"
else
  VOLUME_DIR="$CONFIG_VOLUME_DIR"
  FILER_DIR="$CONFIG_FILER_DIR"
  MASTER_DIR="$CONFIG_MASTER_DIR"
fi

root_source="$(findmnt -T / -no SOURCE)"

# Package-managed startup may create missing child directories, but only after
# proving their parent is on a dedicated mounted filesystem. Running-mode
# verification is strictly non-disruptive and never creates/moves anything.
if ! $RUNNING_MODE; then
  volume_parent="$(dirname "$VOLUME_DIR")"
  if [[ ! -e "$VOLUME_DIR" ]]; then
    [[ -e "$volume_parent" ]] || { echo "ERROR: volume parent does not exist: $volume_parent" >&2; exit 3; }
    parent_source="$(findmnt -T "$volume_parent" -no SOURCE 2>/dev/null || true)"
    parent_target="$(findmnt -T "$volume_parent" -no TARGET 2>/dev/null || true)"
    if [[ -z "$parent_source" || "$parent_source" == "$root_source" || "$parent_target" == "/" ]]; then
      echo "ERROR: refusing to create $VOLUME_DIR because its parent resolves to the NAS root filesystem." >&2
      exit 3
    fi
    mkdir -p "$VOLUME_DIR"
  fi
  mkdir -p "$FILER_DIR" "$MASTER_DIR"
fi

hdd_source="$(findmnt -T "$VOLUME_DIR" -no SOURCE 2>/dev/null || true)"
hdd_target="$(findmnt -T "$VOLUME_DIR" -no TARGET 2>/dev/null || true)"
hdd_fstype="$(findmnt -T "$VOLUME_DIR" -no FSTYPE 2>/dev/null || true)"
ssd_source="$(findmnt -T "$FILER_DIR" -no SOURCE 2>/dev/null || true)"
ssd_target="$(findmnt -T "$FILER_DIR" -no TARGET 2>/dev/null || true)"

if [[ -z "$hdd_source" || "$hdd_source" == "$root_source" || "$hdd_target" == "/" ]]; then
  cat >&2 <<MSG
ERROR: NAS HDD verification FAILED.
  actual SeaweedFS /data source: $VOLUME_DIR
  resolved source:               ${hdd_source:-unknown}
  resolved mountpoint:           ${hdd_target:-unknown}
  NAS root source:               $root_source

The active/configured SeaweedFS volume path is not backed by a dedicated mounted filesystem.
Do not move existing SeaweedFS files. Fix the host mount before accepting new recovery points.
MSG
  exit 3
fi

config_match=true
[[ -z "$runtime_volume_dir" || "${runtime_volume_dir%/}" == "${CONFIG_VOLUME_DIR%/}" ]] || config_match=false

# Before package-managed restart, configuration drift is a hard stop because the
# restart could point SeaweedFS at a different/empty directory. For adoption of
# an already-running NAS, the running Docker bind is the source of truth; drift
# is recorded in proof and warned about but existing data is never moved.
if ! $RUNNING_MODE && [[ "$config_match" != "true" ]]; then
  cat >&2 <<MSG
ERROR: NAS configuration/runtime mount mismatch.
  running SeaweedFS /data source: $runtime_volume_dir
  configured NAS_VOLUME_DATA_DIR: $CONFIG_VOLUME_DIR

Refusing package-managed restart because it could switch SeaweedFS to a different directory.
Use ./scripts/storage/nas-verify.sh for non-disruptive verification of an established NAS,
or align NAS_VOLUME_DATA_DIR before using ./scripts/storage/nas-up.sh.
MSG
  exit 5
fi
if $RUNNING_MODE && [[ "$config_match" != "true" ]]; then
  echo "WARNING: NAS config/default path differs from the currently running SeaweedFS /data bind; runtime bind is authoritative for this verification." >&2
fi
if [[ -n "$ssd_source" && "$ssd_source" == "$hdd_source" ]]; then
  echo "WARNING: Filer metadata and SeaweedFS volume data resolve to the same device ($hdd_source)." >&2
fi

echo "NAS storage mount verified:"
echo "  actual SeaweedFS chunks: $VOLUME_DIR -> $hdd_source ($hdd_fstype), mountpoint=$hdd_target"
echo "  runtime bind source:     ${runtime_volume_dir:-not-running}"
echo "  configured volume dir:   $CONFIG_VOLUME_DIR"
echo "  runtime/config match:     $config_match"
echo "  filer metadata:           $FILER_DIR -> ${ssd_source:-unknown}, mountpoint=${ssd_target:-unknown}"

$PUBLISH || exit 0

# Established deployments may publish the Filer on a custom host port even when
# no NAS .env exists. Prefer the running container's published port in running
# mode, then fall back to configured/default port.
if $RUNNING_MODE; then
  runtime_port="$(published_filer_port "$filer_container")"
  [[ -z "$runtime_port" ]] || FILER_PORT="$runtime_port"
  filer_host="127.0.0.1"
else
  filer_host="$BIND_IP"
  [[ "$filer_host" == "0.0.0.0" || "$filer_host" == "::" ]] && filer_host="127.0.0.1"
fi
filer="http://${filer_host}:${FILER_PORT}"
for _ in $(seq 1 30); do curl -fsS "$filer/" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$filer/" >/dev/null || { echo "ERROR: SeaweedFS Filer is not reachable at the configured local endpoint." >&2; exit 4; }

proof="$(mktemp)"; trap 'rm -f "$proof"' EXIT
jq -n \
  --arg verified_at_utc "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --arg physical_volume_root "$VOLUME_DIR" \
  --arg configured_physical_volume_root "$CONFIG_VOLUME_DIR" \
  --arg volume_container "${volume_container:-not-running}" \
  --arg mount_source "$hdd_source" \
  --arg mountpoint "$hdd_target" \
  --arg filesystem "$hdd_fstype" \
  --arg root_filesystem_source "$root_source" \
  --arg ssd_filer_root "$FILER_DIR" \
  --arg ssd_mount_source "${ssd_source:-}" \
  --arg ssd_master_root "$MASTER_DIR" \
  --arg logical_backup_root "$BACKUP_PATH" \
  --arg verification_source "$([[ "$RUNNING_MODE" == true ]] && echo running-container-bind || echo configured-storage-contract)" \
  --arg compose_workdir "$compose_workdir" \
  --argjson runtime_mount_matches_config "$config_match" \
  '{verified:true, verified_at_utc:$verified_at_utc, physical_volume_root:$physical_volume_root,
    configured_physical_volume_root:$configured_physical_volume_root,
    runtime_mount_matches_config:$runtime_mount_matches_config,
    volume_container:$volume_container, mount_source:$mount_source, mountpoint:$mountpoint,
    filesystem:$filesystem, root_filesystem_source:$root_filesystem_source,
    ssd_filer_root:$ssd_filer_root, ssd_mount_source:$ssd_mount_source,
    ssd_master_root:$ssd_master_root, logical_backup_root:$logical_backup_root,
    verification_source:$verification_source, compose_workdir:$compose_workdir}' > "$proof"

curl -fsS --retry 4 --retry-all-errors -F "file=@${proof}" "$filer${BACKUP_PATH}/storage-location.json" >/dev/null

echo "Storage proof published successfully for the active SeaweedFS deployment."
echo "No SeaweedFS data was moved or restarted."
