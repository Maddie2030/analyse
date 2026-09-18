#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
if command -v python3 >/dev/null 2>&1; then exec python3 scripts/tests/api-route-audit.py; fi
if command -v python >/dev/null 2>&1; then exec python scripts/tests/api-route-audit.py; fi
command -v docker >/dev/null || { echo "ERROR: Python or Docker is required for API route audit" >&2; exit 2; }
VERSION="$(cat VERSION)"; IMAGE="mreader/api-tests:${VERSION}"
docker build --progress=plain -t "$IMAGE" -f tests/api/Dockerfile .
test_docker_run --rm "$IMAGE" python -u /repo/scripts/tests/api-route-audit.py
