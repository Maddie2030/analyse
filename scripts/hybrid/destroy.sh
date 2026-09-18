#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Backward compatibility: DELETE_DATA=true maps to the new explicit purge-data mode.
args=("$@")
if [[ "${DELETE_DATA:-false}" == "true" ]]; then
  args=(--purge-data --yes "${args[@]}")
fi
exec "$ROOT/scripts/hybrid-down.sh" "${args[@]}"
