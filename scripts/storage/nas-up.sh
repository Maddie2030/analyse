#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/ops/nas-seaweedfs/.env}"
if [[ "$ENV_FILE" != /* ]]; then ENV_FILE="$ROOT_DIR/$ENV_FILE"; fi
[[ -f "$ENV_FILE" ]] || { echo "Create $ENV_FILE from ops/nas-seaweedfs/.env.example first." >&2; exit 1; }
exec "$ROOT_DIR/ops/nas-seaweedfs/start.sh" "$ENV_FILE"
