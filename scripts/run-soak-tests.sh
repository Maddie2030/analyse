#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"; source "$ROOT/scripts/env/env-lib.sh"; source "$ROOT/scripts/tests/load-runner-common.sh"
DURATION=600; WORKLOAD_FILTER=''; KEEP_DATA=0; ALL=0
while [[ $# -gt 0 ]]; do case "$1" in --quick) DURATION=120; shift;; --standard) DURATION=600; shift;; --deep) DURATION=1800; shift;; --all) ALL=1; shift;; --workload) WORKLOAD_FILTER="${2:?workload}"; shift 2;; --keep-test-data) KEEP_DATA=1; shift;; *) echo "ERROR: unsupported option $1" >&2; exit 2;; esac; done
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; OUT="$ROOT/test-results/soak/$RUN_ID"; mkdir -p "$OUT/logs" "$OUT/snapshots"
test_set_status soak-start "run_id=${RUN_ID} duration=${DURATION}s out=${OUT}"; trap 'rc=$?; test_set_status finished "mode=soak run_id='"$RUN_ID"' exit=${rc} out='"$OUT"'"' EXIT
load_prepare; load_build_images; load_seed create "$OUT/seed.log"; load_snapshot "$OUT/snapshots/before.txt"
printf 'workload\tservice\tlevel\tunit\tduration_s\trequests\tp50_ms\tp95_ms\tp99_ms\tfailure_rate\tserver_5xx_rate\tstate\n' > "$OUT/results.tsv"; failed=0
run_one(){
 local workload="$1" level="$2" service kind p95 p99 max notes
 IFS='|' read -r _ service kind p95 p99 max notes < <(awk -F'|' -v w="$workload" '$1==w{print;exit}' tests/load/workloads.tsv)
 [[ -n "$service" ]] || { echo "ERROR: unknown workload $workload" >&2; return 2; }
 log="$OUT/logs/${workload}.log"; test_section "Soak $workload: level=$level duration=${DURATION}s"
 resource_log="$OUT/snapshots/${workload}-resource-timeseries.tsv"
 : > "$resource_log"
 ( while true; do ts="$(date -u +%FT%TZ)"; for ns in mreader-user mreader-admin; do kubectl top pods -n "$ns" --no-headers 2>/dev/null | awk -v t="$ts" -v n="$ns" '{print t "\t" n "\t" $1 "\t" $3}' || true; done; sleep 15; done ) >> "$resource_log" 2>/dev/null &
 resource_pid=$!
 k6args=(); while IFS= read -r x; do k6args+=("$x"); done < <(load_k6_env)
 set +e; run_docker_test mreader-k6-soak "$log" "${k6args[@]}" -e "K6_BREAKPOINT_WORKLOAD=${workload}" -e "K6_BREAKPOINT_P95_MS=${p95}" -e "K6_BREAKPOINT_P99_MS=${p99}" -e "K6_SOAK_LEVEL=${level}" -e "K6_SOAK_DURATION_SECONDS=${DURATION}" "$K6_IMAGE" run /tests/load/soak.js; rc=$?; kill "$resource_pid" >/dev/null 2>&1 || true; wait "$resource_pid" 2>/dev/null || true; set -e
 growth_log="$OUT/snapshots/${workload}-resource-growth.txt"
 set +e; awk -f scripts/tests/check-soak-resource-growth.awk "$resource_log" > "$growth_log"; growth_rc=$?; set -e
 if [[ $growth_rc -ne 0 ]]; then echo "Gross same-pod memory growth detected for $workload" >&2; cat "$growth_log" >&2; failed=$((failed+1)); fi
 marker="$(grep 'MREADER_SOAK_RESULT=' "$log" | tail -1 | sed 's/^.*MREADER_SOAK_RESULT=//' || true)"
 if [[ $rc -ne 0 || -z "$marker" ]]; then printf '%s\t%s\t%s\t%s\t%s\t0\t0\t0\t0\t1\t1\tFAIL\n' "$workload" "$service" "$level" "$([[ "$kind" == arrival ]] && echo rps || echo connections)" "$DURATION" >> "$OUT/results.tsv"; failed=$((failed+1)); return; fi
 IFS='|' read -r w l unit dur req p50 p95v p99v fail server state <<< "$marker"; printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$w" "$service" "$l" "$unit" "$dur" "$req" "$p50" "$p95v" "$p99v" "$fail" "$server" "$state" >> "$OUT/results.tsv"; [[ "$state" == PASS ]] || failed=$((failed+1)); load_snapshot "$OUT/snapshots/${workload}-after.txt"
}
if [[ $ALL -eq 1 ]]; then while IFS='|' read -r w service kind p95 p99 max notes; do [[ -z "$w" || "$w" == \#* ]] && continue; [[ -n "$WORKLOAD_FILTER" && "$w" != "$WORKLOAD_FILTER" ]] && continue; run_one "$w" 5; done < tests/load/workloads.tsv
else while IFS='|' read -r w level reason; do [[ -z "$w" || "$w" == \#* ]] && continue; [[ -n "$WORKLOAD_FILTER" && "$w" != "$WORKLOAD_FILTER" ]] && continue; run_one "$w" "$level"; done < tests/load/soak-workloads.tsv; fi
load_snapshot "$OUT/snapshots/after.txt"; [[ $KEEP_DATA -eq 1 ]] || load_seed cleanup "$OUT/cleanup.log" || true
{ echo "MReader soak run: $RUN_ID"; echo "Duration per workload: ${DURATION}s"; echo "Failed workloads: $failed"; echo "Results: $OUT/results.tsv"; } | tee "$OUT/SUMMARY.txt"; [[ $failed -eq 0 ]]
