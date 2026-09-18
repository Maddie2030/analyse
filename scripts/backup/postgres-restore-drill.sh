#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BACKUP_ID=""
ENV_FILE=".env"
usage(){
  cat <<'USAGE'
Usage: ./scripts/backup/postgres-restore-drill.sh --backup-id <bkp_...> [--env-file .env]

Runs read-only catalog/NAS media validation first, then restores the same verified
recovery point into the existing isolated database restore-drill engine. It never
imports catalog rows and never writes to NAS/SeaweedFS.
USAGE
}
while (($#)); do
  case "$1" in
    --backup-id) BACKUP_ID="${2:-}"; shift 2 ;;
    --env-file) ENV_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$BACKUP_ID" =~ ^bkp_[0-9a-f]{24}$ ]] || { echo "ERROR: --backup-id must be an opaque bkp_<24 hex> id." >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE is required." >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker Engine is not ready." >&2; exit 2; }

echo "==> Read-only catalog + NAS/media validation"
bash "$ROOT/scripts/recovery/catalog-restore.sh" --env-file "$ENV_FILE" --backup-id "$BACKUP_ID" --check

echo "==> Isolated PostgreSQL restore drill"
docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm backup_agent restore-drill-public-id "$BACKUP_ID"

echo "P08.7 restore drill completed: database validation + read-only NAS/media validation passed."
