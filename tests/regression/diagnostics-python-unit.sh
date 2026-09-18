#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec "$ROOT/scripts/hybrid/python-runtime.sh" -m unittest tests.diagnostics.test_runner_protocol tests.diagnostics.test_analyze_report tests.diagnostics.test_report_bundle -v
