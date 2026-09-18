#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The supported manual entry point must also create a verified local recovery
# bundle. Keep a single production orchestration path, including failure gates.
if [[ "${MREADER_COMPOSE_FILE:-deploy/compose/docker-compose.hybrid-stateful.yml}" != "deploy/compose/docker-compose.hybrid-stateful.yml" ]]; then
  echo "ERROR: migrations require the supported hybrid stateful Compose configuration." >&2
  exit 2
fi
exec bash "$ROOT_DIR/scripts/hybrid/stateful-up.sh" core
