#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
for f in \
  scripts/development-reference/build_mreader_code_graph.py \
  scripts/development-reference/build_mreader_development_graph.py \
  scripts/development-reference/build-reference.sh \
  scripts/development-reference/mreader-impact.py \
  docs/development-reference/ISSUE-TO-CHANGE-INDEX.md \
  docs/development-reference/SERVICE-LOCATOR.md; do
  [[ -s "$f" ]] || { echo "development reference regression FAILED: missing $f" >&2; exit 1; }
done
bash -n scripts/development-reference/build-reference.sh
"$PYTHON_RUNTIME" tests/regression/test_development_reference_tooling.py -v
echo 'development reference static regression PASS'
