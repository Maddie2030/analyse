#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"; source "$ROOT/scripts/env/env-lib.sh"; source "$ROOT/scripts/tests/load-runner-common.sh"
MODE=standard; WORKLOAD_FILTER=''; KEEP_DATA=0; BASE=5; SPIKE=100; BASE_S=20; SPIKE_S=15; RECOVERY_S=30
while [[ $# -gt 0 ]]; do case "$1" in
  --quick) MODE=quick; BASE=2; SPIKE=30; BASE_S=10; SPIKE_S=8; RECOVERY_S=15; shift;;
  --standard) shift;; --deep) MODE=deep; BASE=10; SPIKE=200; BASE_S=30; SPIKE_S=20; RECOVERY_S=60; shift;;
  --workload) WORKLOAD_FILTER="${2:?workload required}"; shift 2;; --keep-test-data) KEEP_DATA=1; shift;;
  *) echo "ERROR: unsupported option $1" >&2; exit 2;; esac; done
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; OUT="$ROOT/test-results/spike/$RUN_ID"; mkdir -p "$OUT/logs" "$OUT/snapshots"
test_set_status spike-start "run_id=${RUN_ID} mode=${MODE} out=${OUT}"; trap 'rc=$?; test_set_status finished "mode=spike run_id='"$RUN_ID"' exit=${rc} out='"$OUT"'"' EXIT
load_prepare; load_build_images; load_seed create "$OUT/seed.log"
printf 'workload\tservice\tbaseline\tspike\tunit\tbaseline_requests\tbaseline_p95\tbaseline_p99\tbaseline_failure\tspike_requests\tspike_p95\tspike_p99\tspike_failure\trecovery_requests\trecovery_p95\trecovery_p99\trecovery_failure\tserver_5xx_rate\tstatus_429\tdropped_iterations\tdropped_rate\tstate\n' > "$OUT/results.tsv"
load_snapshot "$OUT/snapshots/before.txt"; failed=0
while IFS='|' read -r workload service kind p95 p99 max_level notes; do
  [[ -z "$workload" || "$workload" == \#* ]] && continue; [[ -n "$WORKLOAD_FILTER" && "$workload" != "$WORKLOAD_FILTER" ]] && continue
  target=$SPIKE; (( target > max_level )) && target=$max_level
  log="$OUT/logs/${workload}.log"; test_section "Spike $workload: baseline=$BASE peak=$target recovery=$BASE"
  k6args=(); while IFS= read -r x; do k6args+=("$x"); done < <(load_k6_env)
  monitor_log="$OUT/snapshots/${workload}-live-scaling.log"
  ( while true; do echo "### $(date -u +%FT%TZ)"; kubectl -n mreader-user get pods,hpa 2>/dev/null || true; kubectl -n mreader-admin get pods,hpa,scaledobjects 2>/dev/null || true; kubectl top pods -A 2>/dev/null || true; sleep 2; done ) > "$monitor_log" 2>&1 &
  monitor_pid=$!
  set +e
  run_docker_test mreader-k6-spike "$log" "${k6args[@]}" \
    -e "K6_BREAKPOINT_WORKLOAD=${workload}" -e "K6_BREAKPOINT_P95_MS=${p95}" -e "K6_BREAKPOINT_P99_MS=${p99}" \
    -e "K6_SPIKE_BASELINE_LEVEL=${BASE}" -e "K6_SPIKE_LEVEL=${target}" -e "K6_SPIKE_BASELINE_SECONDS=${BASE_S}" -e "K6_SPIKE_SECONDS=${SPIKE_S}" -e "K6_SPIKE_RECOVERY_SECONDS=${RECOVERY_S}" \
    "$K6_IMAGE" run /tests/load/spike.js
  rc=$?; kill "$monitor_pid" >/dev/null 2>&1 || true; wait "$monitor_pid" 2>/dev/null || true; set -e
  marker="$(grep 'MREADER_SPIKE_RESULT=' "$log" | tail -1 | sed 's/^.*MREADER_SPIKE_RESULT=//' || true)"
  if [[ $rc -ne 0 || -z "$marker" ]]; then
    printf '%s\t%s\t%s\t%s\t%s\t0\t0\t0\t1\t0\t0\t0\t1\t0\t0\t0\t1\t1\t0\t0\t0\tFAIL\n' "$workload" "$service" "$BASE" "$target" "$([[ "$kind" == arrival ]] && echo rps || echo connections)" >> "$OUT/results.tsv"; failed=$((failed+1)); continue
  fi
  IFS='|' read -r w b s unit br bp95 bp99 bf sr sp95 sp99 sf rr rp95 rp99 rf e r429 dropped dropped_rate state <<< "$marker"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$w" "$service" "$b" "$s" "$unit" "$br" "$bp95" "$bp99" "$bf" "$sr" "$sp95" "$sp99" "$sf" "$rr" "$rp95" "$rp99" "$rf" "$e" "$r429" "$dropped" "$dropped_rate" "$state" >> "$OUT/results.tsv"
  [[ "$state" == PASS ]] || failed=$((failed+1)); load_snapshot "$OUT/snapshots/${workload}-after.txt"
done < tests/load/workloads.tsv
load_snapshot "$OUT/snapshots/after.txt"; [[ $KEEP_DATA -eq 1 ]] || load_seed cleanup "$OUT/cleanup.log" || true
{
 echo "MReader spike run: $RUN_ID"; echo "Mode: $MODE"; echo "Failed workloads: $failed"; echo "Results: $OUT/results.tsv";
} | tee "$OUT/SUMMARY.txt"
[[ $failed -eq 0 ]]
