#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-}"

# This command is intentionally non-disruptive for established NAS deployments.
# It derives the active SeaweedFS /data bind source from Docker, verifies that
# source with findmnt, and publishes proof. It does not restart containers or move data.
if [[ -z "$ENV_FILE" ]]; then
  cid="$(docker ps -q --filter name=mreader-seaweed-volume-hdd | head -n1 || true)"
  workdir=""
  [[ -z "$cid" ]] || workdir="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)"
  if [[ -n "$workdir" && -f "$workdir/.env" ]]; then ENV_FILE="$workdir/.env"; fi
fi

if [[ -n "$ENV_FILE" && "$ENV_FILE" != /* ]]; then ENV_FILE="$ROOT_DIR/$ENV_FILE"; fi
exec "$ROOT_DIR/ops/nas-seaweedfs/storage-contract.sh" "${ENV_FILE:-}" publish-running
