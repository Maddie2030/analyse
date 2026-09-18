#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
MODE=static
while (($#)); do
  case "$1" in
    --static) MODE=static ;;
    --runtime) MODE=runtime ;;
    --all) MODE=all ;;
    -h|--help)
      cat <<'HELP'
Usage: ./scripts/run-regression-tests.sh [--static|--runtime|--all]

  --static   Source/config/harness regressions; no running application required.
  --runtime  Current Docker Desktop hybrid runtime integration tests.
  --all      Static regressions followed by current hybrid runtime integration.
HELP
      exit 0 ;;
    *) echo "ERROR: unsupported option $1" >&2; exit 2 ;;
  esac
  shift
done
if [[ "$MODE" == runtime ]]; then exec "$ROOT/scripts/run-runtime-integration-tests.sh"; fi
if [[ "$MODE" == all ]]; then
  "$0" --static
  exec "$ROOT/scripts/run-runtime-integration-tests.sh"
fi
REGRESSION_DIR="${MREADER_REGRESSION_DIR:-$ROOT/tests/regression}"
RESULTS_ROOT="${MREADER_REGRESSION_RESULTS_ROOT:-$ROOT/test-results/regression}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$RESULTS_ROOT/$RUN_ID"; mkdir -p "$OUT/logs"
SUMMARY="$OUT/results.tsv"; printf 'test\tclass\tstatus\texit_code\n' > "$SUMMARY"
test_set_status "regression-start" "mode=static run_id=${RUN_ID} out=${OUT}"
finish(){ local rc=$?; test_set_status "finished" "mode=regression-static run_id=${RUN_ID} exit=${rc} out=${OUT}"; }
trap finish EXIT
selected=0; failed=0; skipped=0
shopt -s nullglob; files=("$REGRESSION_DIR"/*.sh); shopt -u nullglob
for file in "${files[@]}"; do
  name="$(basename "$file")"; selected=$((selected+1))
  test_section "Regression [static] $name"; log="$OUT/logs/${name%.sh}.log"
  set +e; bash "$file" 2>&1 | tee "$log"; ps=("${PIPESTATUS[@]}"); set -e
  rc=${ps[0]}; tee_rc=${ps[1]}
  if [[ $tee_rc -ne 0 ]]; then status=FAIL; rc=$tee_rc; failed=$((failed+1))
  elif [[ $rc -eq 0 ]]; then status=PASS
  elif [[ $rc -eq 77 ]]; then status=SKIP; skipped=$((skipped+1))
  else status=FAIL; failed=$((failed+1)); fi
  printf '%s\tstatic\t%s\t%s\n' "$name" "$status" "$rc" >> "$SUMMARY"
done
[[ $selected -gt 0 ]] || { echo "ERROR: no regression tests selected" >&2; exit 2; }
passed=$((selected-failed-skipped))
printf 'MReader static regression run: %s\nSelected: %d\nPassed: %d\nSkipped: %d\nFailed: %d\nResults: %s\n' "$RUN_ID" "$selected" "$passed" "$skipped" "$failed" "$SUMMARY" | tee "$OUT/SUMMARY.txt"
[[ $failed -eq 0 ]]
