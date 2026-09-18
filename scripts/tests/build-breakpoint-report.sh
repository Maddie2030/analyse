#!/usr/bin/env bash
set -euo pipefail
DIR="${1:?capacity result directory required}"
RESULTS="$DIR/results.tsv"
REPORT="$DIR/CAPACITY_REPORT.md"
SUMMARY="$DIR/CAPACITY_SUMMARY.tsv"
[[ -f "$RESULTS" ]] || { echo "ERROR: missing $RESULTS" >&2; exit 2; }

printf 'workload\tservice\toptimal_level\thighest_sustainable\tbreaking_level\tunit\tbreak_reason\n' > "$SUMMARY"

awk -F'\t' 'NR>1 {
  w=$1; service[w]=$2; unit[w]=$4;
  level=$3+0; state=$14;
  if (state=="OPTIMAL" && level>optimal[w]) optimal[w]=level;
  if ((state=="OPTIMAL" || state=="PASS") && level>sustainable[w]) sustainable[w]=level;
  if (state=="FAIL" && $17==2 && (breaking[w]==0 || level<breaking[w])) {
    breaking[w]=level;
    if (($5+0)==0) reason[w]="runtime/job failure";
    else if (($13+0)>0 && w=="auth_login") reason[w]="Auth 429 policy limit";
    else if (($12+0)>=0.005 || ($11+0)>0) reason[w]="k6/target-rate saturation";
    else if (($10+0)>=0.01) reason[w]="HTTP/logical error saturation";
    else if (($8+0)>($15+0) || ($9+0)>($16+0)) reason[w]="latency SLO exceeded";
    else reason[w]="runtime/job failure";
  }
  order[w]=1;
}
END {
  for (w in order) {
    b=(breaking[w]>0 ? breaking[w] : ">tested-max");
    o=(optimal[w]>0 ? optimal[w] : "not-found");
    s=(sustainable[w]>0 ? sustainable[w] : "none");
    r=(reason[w]!="" ? reason[w] : "none within ladder");
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", w, service[w], o, s, b, unit[w], r;
  }
}' "$RESULTS" | sort >> "$SUMMARY"

{
  echo '# MReader API / Service Breakpoint Report'
  echo
  echo 'This report is produced by gradual, isolated load ladders against the current Docker Desktop twin-plane deployment.'
  echo
  echo '## How to interpret the numbers'
  echo
  echo '- **Optimal level**: highest tested step with <=0.1% failures, no dropped iterations, p95 <=70% of the configured p95 SLO, and p99 <=75% of the p99 SLO.'
  echo '- **Highest sustainable**: highest step that stayed below 1% failures, below p95/p99 SLOs, and below 0.5% dropped iterations.'
  echo '- **Breaking level**: first load level that failed twice after a cooldown. A single transient failure is not called a breakpoint.'
  echo '- Arrival workloads are measured in target requests/second. Realtime is measured as concurrent authenticated WebSocket connections.'
  echo '- If `auth_login` breaks on HTTP 429, that is an intentional policy/rate-limit breakpoint, not necessarily CPU capacity.'
  echo '- If the break reason is target-rate/generator saturation, rerun with a stronger/distributed k6 generator before treating it as an application limit.'
  echo
  echo '## Per-workload capacity summary'
  echo
  echo '| Workload | Service | Optimal | Highest sustainable | First confirmed break | Unit | Reason |'
  echo '|---|---|---:|---:|---:|---|---|'
  tail -n +2 "$SUMMARY" | while IFS=$'\t' read -r w s o h b u r; do
    printf '| `%s` | `%s` | %s | %s | %s | %s | %s |\n' "$w" "$s" "$o" "$h" "$b" "$u" "$r"
  done
  echo
  echo '## Raw staircase measurements'
  echo
  echo '| Workload | Level | Unit | Throughput | p50 ms | p95 ms | p99 ms | Failure | Dropped | 429 | State | Attempt |'
  echo '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|'
  tail -n +2 "$RESULTS" | while IFS=$'\t' read -r w s level unit req thr p50 p95 p99 fail dropped drate r429 state s95 s99 attempt; do
    printf '| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' "$w" "$level" "$unit" "$thr" "$p50" "$p95" "$p99" "$fail" "$dropped" "$r429" "$state" "$attempt"
  done
  echo
  echo '## Service/resource correlation'
  echo
  echo 'A Kubernetes/Docker resource snapshot is stored after every step under `snapshots/`. Use the snapshot for the first failing step and the previous passing step to determine whether the limiting layer was an application pod/HPA, PostgreSQL, Valkey, RabbitMQ, image edge/NAS, or the k6 generator itself.'
  echo
  echo '## Safety note'
  echo
  echo 'The capacity ladder intentionally stops after the first confirmed failure for each workload. It does not continue increasing load after the breakpoint, which avoids turning capacity discovery into a prolonged denial-of-service against the local development machine.'
} > "$REPORT"

echo "$REPORT"
