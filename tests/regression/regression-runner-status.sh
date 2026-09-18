#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/cases" "$TMP/results"

cat > "$TMP/cases/pass.sh" <<'CASE'
#!/usr/bin/env bash
exit 0
CASE
cat > "$TMP/cases/skip.sh" <<'CASE'
#!/usr/bin/env bash
echo 'synthetic capability skip'
exit 77
CASE
chmod +x "$TMP/cases"/*.sh

MREADER_REGRESSION_DIR="$TMP/cases" \
MREADER_REGRESSION_RESULTS_ROOT="$TMP/results" \
TEST_RUNNER_STATUS_FILE="$TMP/status" \
  ./scripts/run-regression-tests.sh --static > "$TMP/first.log"

summary="$(find "$TMP/results" -name results.tsv -type f | head -n1)"
[[ -f "$summary" ]] || { echo 'FAIL: synthetic regression results.tsv missing' >&2; exit 1; }
grep -q $'pass.sh\tstatic\tPASS\t0' "$summary" || { echo 'FAIL: PASS result not recorded' >&2; exit 1; }
grep -q $'skip.sh\tstatic\tSKIP\t77' "$summary" || { echo 'FAIL: SKIP/77 result not recorded' >&2; exit 1; }
grep -q '^Skipped: 1$' "${summary%/results.tsv}/SUMMARY.txt" || { echo 'FAIL: skip count missing from summary' >&2; exit 1; }

cat > "$TMP/cases/fail.sh" <<'CASE'
#!/usr/bin/env bash
exit 42
CASE
chmod +x "$TMP/cases/fail.sh"
set +e
MREADER_REGRESSION_DIR="$TMP/cases" \
MREADER_REGRESSION_RESULTS_ROOT="$TMP/results2" \
TEST_RUNNER_STATUS_FILE="$TMP/status2" \
  ./scripts/run-regression-tests.sh --static > "$TMP/second.log" 2>&1
rc=$?
set -e
[[ $rc -eq 1 ]] || { echo "FAIL: synthetic failed regression should return runner rc=1, got $rc" >&2; exit 1; }
summary2="$(find "$TMP/results2" -name results.tsv -type f | head -n1)"
grep -q $'fail.sh\tstatic\tFAIL\t42' "$summary2" || { echo 'FAIL: failed test exit code was not preserved' >&2; exit 1; }

echo 'regression runner PASS/SKIP/FAIL status handling PASSED'
