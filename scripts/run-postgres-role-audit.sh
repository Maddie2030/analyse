#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec "$ROOT/scripts/hybrid/python-runtime.sh" "$ROOT/scripts/tests/postgres-role-audit.py" "$@"
