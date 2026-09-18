#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-}"
if [[ -z "$ENV_FILE" ]]; then
  [[ -f "$ROOT_DIR/ops/nas-seaweedfs/.env" ]] && ENV_FILE="$ROOT_DIR/ops/nas-seaweedfs/.env"
  if [[ -z "$ENV_FILE" ]]; then
    cid="$(docker ps -q --filter name=mreader-seaweed-volume-hdd | head -n1 || true)"
    workdir=""; [[ -z "$cid" ]] || workdir="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)"
    [[ -n "$workdir" && -f "$workdir/.env" ]] && ENV_FILE="$workdir/.env"
  fi
fi
[[ -z "$ENV_FILE" || "$ENV_FILE" == /* ]] || ENV_FILE="$ROOT_DIR/$ENV_FILE"
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi

echo '==> Resolved NAS storage environment (non-secret)'
printf 'env_file=%s\n' "${ENV_FILE:-<runtime inspection only>}"
printf 'NAS_BIND_IP=%s\n' "${NAS_BIND_IP:-0.0.0.0}"
printf 'NAS_SEAWEEDFS_PORT=%s\n' "${NAS_SEAWEEDFS_PORT:-8888}"
printf 'NAS_HDD_ROOT=%s\n' "${NAS_HDD_ROOT:-/srv/seaweed/hdd}"
printf 'NAS_SSD_ROOT=%s\n' "${NAS_SSD_ROOT:-/srv/seaweed/ssd/meta}"
printf 'NAS_VOLUME_DATA_DIR=%s\n' "${NAS_VOLUME_DATA_DIR:-${NAS_HDD_ROOT:-/srv/seaweed/hdd}/volumes}"
printf 'NAS_FILER_DATA_DIR=%s\n' "${NAS_FILER_DATA_DIR:-${NAS_SSD_ROOT:-/srv/seaweed/ssd/meta}/filer}"
printf 'NAS_MASTER_DATA_DIR=%s\n' "${NAS_MASTER_DATA_DIR:-${NAS_SSD_ROOT:-/srv/seaweed/ssd/meta}/master}"
printf 'POSTGRES_BACKUP_NAS_PATH=%s\n' "${POSTGRES_BACKUP_NAS_PATH:-backups/mreader/postgres}"
echo

echo '==> Running SeaweedFS containers and ACTUAL /data bind sources'
for c in $(docker ps --format '{{.Names}}' | grep -E '^mreader-seaweed-(master|filer|volume-hdd|volume)$' || true); do
  echo "[$c]"
  docker inspect "$c" --format '{{range .Mounts}}{{println "SOURCE=" .Source " DEST=" .Destination " TYPE=" .Type}}{{end}}'
done
echo

echo '==> Physical mount verification'
if "$ROOT_DIR/ops/nas-seaweedfs/storage-contract.sh" "${ENV_FILE:-}" check-running; then echo 'mount_contract=PASS'; else echo "mount_contract=FAIL exit=$?"; fi
echo

echo '==> Filer backup namespace'
port="${NAS_SEAWEEDFS_PORT:-8888}"
curl -fsS -H 'Accept: application/json' "http://127.0.0.1:${port}/backups/mreader/postgres/?limit=1000" 2>/dev/null || echo 'backup namespace unavailable'
