#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# Historical entrypoint retained for existing validator callers. Source-string
# matches cannot verify transaction ordering or acknowledgements. Exercise the
# production client state machine instead; PostgreSQL command acceptance belongs
# to tests/api/test_26_reading_commands.py against actual disposable services.
#
# The production test imports TypeScript directly. Node 22 keeps type stripping
# behind an explicit flag, while newer runtimes may enable it by default. Probe
# the production module without the test's defensive import catch so a loader
# incompatibility cannot be misreported as dozens of missing exports.
NODE_TS_FLAGS=()
if node --help 2>&1 | grep -q -- '--experimental-strip-types'; then
  NODE_TS_FLAGS+=(--experimental-strip-types)
elif ! node --input-type=module -e "await import('./frontend/src/reading/model.ts')" >/dev/null 2>&1; then
  echo 'ERROR: reading repository regression requires a Node runtime with TypeScript type stripping support (Node >= 22.6).' >&2
  exit 2
fi
exec node "${NODE_TS_FLAGS[@]}" --test tests/regression/test_web_reading_repository.mjs
