#!/usr/bin/env bash
# Deterministic CURRENT twin-plane release qualification. Destructive/external
# checks are only added by --everything and never hidden inside the default run.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
MODE="${1:---full}"
case "$MODE" in --quick|--full|--everything) ;; *) echo "Usage: $0 --quick|--full|--everything" >&2; exit 2;; esac
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
if [[ "$MODE" == --everything ]]; then
  [[ "${MREADER_ALLOW_DESTRUCTIVE_TESTS:-0}" == 1 ]] || { echo "ERROR: --everything includes RabbitMQ chaos; set MREADER_ALLOW_DESTRUCTIVE_TESTS=1" >&2; exit 2; }
  [[ -n "$(env_get .env SCRAPER_TEST_SERIES_URL)" && -n "$(env_get .env SCRAPER_TEST_CHAPTER_URL)" ]] || { echo "ERROR: --everything requires SCRAPER_TEST_SERIES_URL and SCRAPER_TEST_CHAPTER_URL in .env" >&2; exit 2; }
fi
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; OUT="$ROOT/test-results/qualification/$RUN_ID"; mkdir -p "$OUT/logs" "$OUT/integrity"
RESULTS="$OUT/phases.tsv"; printf 'phase\tclass\tstatus\texit_code\n' > "$RESULTS"
OVERALL=0; CORRECTNESS_OK=1
run_phase(){
  local name="$1" class="$2"; shift 2
  printf '\n========== %s ==========' "$name"; printf '\n'
  local rc phase_rc tee_rc
  local -a pipe_status
  set +e
  "$@" 2>&1 | tee "$OUT/logs/${name}.log"
  pipe_status=("${PIPESTATUS[@]}")
  phase_rc=${pipe_status[0]}
  tee_rc=${pipe_status[1]}
  rc=$phase_rc
  if [[ $rc -eq 0 && $tee_rc -ne 0 ]]; then
    echo "ERROR: log capture failed for phase ${name} with exit ${tee_rc}" >&2
    rc=$tee_rc
  fi
  set +e
  if [[ $rc -eq 0 ]]; then printf '%s\t%s\tPASS\t0\n' "$name" "$class" >> "$RESULTS"; else printf '%s\t%s\tFAIL\t%s\n' "$name" "$class" "$rc" >> "$RESULTS"; OVERALL=1; fi
  return "$rc"
}
# Do not let caller/global errexit prevent final integrity evidence.
set +e
run_phase integrity-baseline integrity ./scripts/tests/post-run-integrity.sh --capture "$OUT/integrity" || { echo "ERROR: could not establish pre-test integrity baseline" >&2; exit 2; }

# Correctness gates: stop expensive traffic if any fails.
run_phase static-regressions correctness ./scripts/run-regression-tests.sh --static || CORRECTNESS_OK=0
if (( CORRECTNESS_OK )); then run_phase api-integration correctness ./scripts/run-hybrid-tests.sh --pytest-only || CORRECTNESS_OK=0; fi
if (( CORRECTNESS_OK )); then run_phase browser-e2e correctness ./scripts/run-browser-tests.sh || CORRECTNESS_OK=0; fi
if (( CORRECTNESS_OK )); then run_phase runtime-integration correctness ./scripts/run-runtime-integration-tests.sh || CORRECTNESS_OK=0; fi
if [[ "$MODE" == --everything && $CORRECTNESS_OK -eq 1 ]]; then run_phase external-scraper external ./scripts/run-hybrid-tests.sh --external-only || CORRECTNESS_OK=0; fi

if (( CORRECTNESS_OK )); then
  if [[ "$MODE" == --quick ]]; then
    run_phase breakpoint-load performance ./scripts/run-breakpoint-tests.sh --quick || true
    run_phase spike-recovery performance ./scripts/run-spike-tests.sh --quick || true
  else
    run_phase breakpoint-load performance ./scripts/run-breakpoint-tests.sh --standard || true
    run_phase spike-recovery performance ./scripts/run-spike-tests.sh --standard || true
    run_phase soak-endurance performance ./scripts/run-soak-tests.sh --standard || true
  fi
  if [[ "$MODE" == --everything ]]; then run_phase rabbitmq-chaos chaos ./scripts/run-chaos-tests.sh || true; fi
else
  echo "Correctness gate failed; load/spike/soak/chaos phases are BLOCKED to avoid testing a known-broken deployment." | tee "$OUT/logs/performance-blocked.log"
  printf 'performance-phases\tperformance\tBLOCKED\t0\n' >> "$RESULTS"
fi

# Always run post-integrity even after a test phase failed.
run_phase post-run-integrity integrity ./scripts/tests/post-run-integrity.sh --verify "$OUT/integrity" || true
passed="$(awk -F'\t' '$3=="PASS"{n++}END{print n+0}' "$RESULTS")"; failed="$(awk -F'\t' '$3=="FAIL"{n++}END{print n+0}' "$RESULTS")"; blocked="$(awk -F'\t' '$3=="BLOCKED"{n++}END{print n+0}' "$RESULTS")"
cat > "$OUT/SUMMARY.txt" <<SUMMARY
MReader release qualification: $RUN_ID
Version: $(cat VERSION)
Mode: ${MODE#--}
Passed phases: $passed
Failed phases: $failed
Blocked phases: $blocked
Overall: $([[ $OVERALL -eq 0 ]] && echo PASS || echo FAIL)
Results: $RESULTS
SUMMARY
cat "$OUT/SUMMARY.txt"
echo "Qualification evidence: $OUT"
exit "$OVERALL"
