#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

mode="${1:---all}"
[[ -f .env ]] || { echo "ERROR: .env is required." >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 2; }

val() {
  local v
  v="$(env_get .env "$1")"
  case "$v" in
    \"*\") v="${v#\"}"; v="${v%\"}" ;;
    \'*\') v="${v#\'}"; v="${v%\'}" ;;
  esac
  printf '%s' "$v"
}

NAS_HOST="$(val NAS_SEAWEEDFS_HOST)"
NAS_PORT="$(val NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
DB_USER="$(val POSTGRES_USER)"; DB_USER="${DB_USER:-manhwa}"
DB_NAME="$(val POSTGRES_DB)"; DB_NAME="${DB_NAME:-manhwa}"
[[ -n "$NAS_HOST" ]] || { echo "ERROR: NAS_SEAWEEDFS_HOST is empty." >&2; exit 2; }
NAS_BASE="http://${NAS_HOST}:${NAS_PORT}"

host_check() {
  command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required for NAS validation." >&2; exit 2; }
  echo "Checking host -> NAS SeaweedFS Filer: $NAS_BASE"
  curl -fsS --connect-timeout 5 --max-time 10 "$NAS_BASE/" >/dev/null || {
    echo "ERROR: NAS SeaweedFS Filer is not reachable from the Windows/Git-Bash host at $NAS_BASE" >&2
    echo "Check NAS power, Ethernet/IP, firewall, SeaweedFS filer process, NAS_SEAWEEDFS_HOST and NAS_SEAWEEDFS_PORT." >&2
    exit 10
  }
  echo "PASS: host can reach NAS SeaweedFS Filer"

    db_cid="$(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml ps -q db 2>/dev/null | head -n1)"
  [[ -n "$db_cid" ]] || { echo "ERROR: hybrid PostgreSQL container is not running." >&2; exit 11; }

  counts="$(docker exec "$db_cid" psql -U "$DB_USER" -d "$DB_NAME" -At -F '|' -c \
    "SELECT (SELECT count(*) FROM series),(SELECT count(*) FROM chapters),(SELECT count(*) FROM pages);" 2>/dev/null)" || {
      echo "ERROR: unable to read MReader metadata counts from PostgreSQL." >&2
      exit 12
    }
  IFS='|' read -r series_count chapter_count page_count <<<"$counts"
  echo "PostgreSQL metadata: series=${series_count:-?} chapters=${chapter_count:-?} pages=${page_count:-?}"
  echo "PostgreSQL volume: mreader_pgdata"

  if [[ "${series_count:-0}" == "0" ]]; then
    echo "WARNING: PostgreSQL currently contains zero series. The webpage catalog will therefore be empty even if NAS is connected." >&2
    echo "Available PostgreSQL volumes:" >&2
    docker volume ls --format '{{.Name}}' | grep -Fx 'mreader_pgdata' >&2 || true
    return 0
  fi

  # Verify a few object paths referenced by the authoritative metadata DB.
  mapfile -t samples < <(docker exec "$db_cid" psql -U "$DB_USER" -d "$DB_NAME" -At -c \
    "SELECT p FROM (SELECT cover_image_path AS p FROM series WHERE cover_image_path IS NOT NULL UNION ALL SELECT image_path FROM pages WHERE image_path IS NOT NULL UNION ALL SELECT responsive_image_path FROM pages WHERE responsive_image_path IS NOT NULL) q WHERE p <> '' LIMIT 5;" 2>/dev/null | sed '/^$/d')
  if ((${#samples[@]} == 0)); then
    echo "WARNING: metadata exists but no sample media object paths were found to verify against NAS." >&2
    return 0
  fi

  local ok=0 fail=0 path url
  for path in "${samples[@]}"; do
    case "$path" in
      http://*|https://*) url="$path" ;;
      *) url="$NAS_BASE/${path#/}" ;;
    esac
    if curl -fsS --connect-timeout 5 --max-time 15 -o /dev/null "$url"; then
      ok=$((ok+1))
    else
      echo "FAIL NAS object: $path" >&2
      fail=$((fail+1))
    fi
  done
  echo "NAS object sample: ok=$ok failed=$fail sampled=${#samples[@]}"
  (( fail == 0 )) || {
    echo "ERROR: PostgreSQL references media objects that are not reachable on the configured NAS filer." >&2
    exit 13
  }
}

k8s_check() {
  command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required for Kubernetes -> NAS validation." >&2; exit 2; }
  kubectl get namespace mreader-admin >/dev/null 2>&1 || { echo "ERROR: mreader-admin namespace does not exist yet." >&2; exit 20; }
  kubectl -n mreader-admin delete pod hybrid-nas-connectivity-check --ignore-not-found --wait=true --timeout=30s >/dev/null 2>&1 || true
  cat <<EOF_POD | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: hybrid-nas-connectivity-check
  namespace: mreader-admin
  labels:
    app: hybrid-nas-connectivity-check
    part-of: mreader
spec:
  restartPolicy: Never
  enableServiceLinks: false
  containers:
    - name: nas-check
      image: busybox:1.37.0
      command: ["sh", "-c", "wget -q -T 5 -O /dev/null '${NAS_BASE}/'"]
      resources:
        requests:
          cpu: 5m
          memory: 8Mi
        limits:
          cpu: 50m
          memory: 32Mi
EOF_POD
  if ! kubectl -n mreader-admin wait --for=jsonpath='{.status.phase}'=Succeeded pod/hybrid-nas-connectivity-check --timeout=60s >/dev/null 2>&1; then
    kubectl -n mreader-admin describe pod hybrid-nas-connectivity-check >&2 || true
    kubectl -n mreader-admin logs hybrid-nas-connectivity-check >&2 2>/dev/null || true
    echo "ERROR: Kubernetes pods cannot reach NAS SeaweedFS Filer at $NAS_BASE" >&2
    exit 21
  fi
  kubectl -n mreader-admin delete pod hybrid-nas-connectivity-check --wait=false >/dev/null 2>&1 || true
  echo "PASS: Kubernetes can reach NAS SeaweedFS Filer at $NAS_BASE"
}

case "$mode" in
  --host) host_check ;;
  --kubernetes) k8s_check ;;
  --all) host_check; k8s_check ;;
  *) echo "Usage: $0 [--host|--kubernetes|--all]" >&2; exit 2 ;;
esac
