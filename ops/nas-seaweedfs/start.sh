#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env}"
if [[ "$ENV_FILE" != /* ]]; then ENV_FILE="$ROOT/$ENV_FILE"; fi
[[ -f "$ENV_FILE" ]] || { echo "ERROR: NAS env file not found: $ENV_FILE" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: required command missing: docker" >&2; exit 2; }

# Never start/reconfigure SeaweedFS until the host HDD mount is proven.
"$SCRIPT_DIR/storage-contract.sh" "$ENV_FILE" check

docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/docker-compose.yml" up -d

# Publish proof only after the Filer is reachable.
"$SCRIPT_DIR/storage-contract.sh" "$ENV_FILE" publish
