#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$#" -le 1 ]] || { echo "Usage: backup-storage-doctor.sh [ENV_FILE]" >&2; exit 2; }
# PostgreSQL protection is validated by its host-local owner. NAS media has its
# own diagnostics; it is no longer an alternative database recovery inventory.
MREADER_ENV_FILE="${1:-$ROOT/.env}" exec bash "$ROOT/scripts/backup/postgres-backup.sh" check-storage
