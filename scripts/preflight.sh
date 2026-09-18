#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
[[ -f .env ]] || { echo "ERROR: .env is missing. Run ./scripts/bootstrap.sh first." >&2; exit 2; }
for cmd in docker kubectl; do command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
docker compose version >/dev/null
kubectl config current-context | grep -qx docker-desktop || { echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2; }
./scripts/hybrid/validate.sh
echo "Preflight checks passed for MReader $(cat VERSION) hybrid runtime."
