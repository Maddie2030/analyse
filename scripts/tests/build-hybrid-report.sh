#!/usr/bin/env bash
set -euo pipefail
DIR="${1:?result directory required}"
SUMMARY="$DIR/SUMMARY.txt"
REPORT="$DIR/REPORT.md"
[[ -f "$SUMMARY" ]] || { echo "ERROR: missing $SUMMARY" >&2; exit 2; }
{
  echo "# MReader Dockerized Twin-Plane Test Report"
  echo
  echo '```text'
  cat "$SUMMARY"
  echo '```'
  echo
  echo "## Test coverage"
  echo
  echo "- Pytest: health/routing, authentication/session/RBAC, catalog read/write, Reader manifests/tokens/images, Progress/history/chapter-read ownership, bookmarks/subscriptions/ratings, comments/realtime contracts, notifications, Media durable jobs, Scraper existing/new-series workflows, lifecycle cleanup, Smart Library, outbox/event contracts, SQL bind contracts."
  echo "- Capacity: intentionally separate from this pytest correctness report. `./test-mreader.sh --full` continues into isolated gradual k6 breakpoint ladders only after pytest passes; `--capacity` and `--capacity-deep` can run them explicitly."
  echo "- Test execution: ordinary Docker containers; application under test remains the current Kubernetes twin-plane."
  echo "- Post-run snapshot: Kubernetes pods/deployments/HPA/KEDA plus Docker stateful/test-container state."
  echo
  echo "## Pytest output"
  echo
  echo '```text'
  if [[ -f "$DIR/pytest.log" ]]; then tail -80 "$DIR/pytest.log"; else echo 'not run'; fi
  echo '```'
  echo
  echo "## Kubernetes warnings after the run"
  echo
  echo '```text'
  if [[ -f "$DIR/cluster-after.txt" ]]; then
    awk '/### recent warning events/{flag=1;next} flag{print}' "$DIR/cluster-after.txt" | tail -100
  else
    echo 'snapshot unavailable'
  fi
  echo '```'
  echo
  echo "## Interpretation"
  echo
  echo "- Any pytest failure is treated as a functional/integration defect until investigated."
  echo "- Gradual k6 capacity results are written under `test-results/capacity/<run-id>/` and use per-workload optimal/sustainable/confirmed-break semantics."
  echo "- Worker pods at 0/0 after the test are expected when KEDA has drained all durable work; CrashLoopBackOff, persistent unacknowledged work, or repeated scaler errors are not expected."
} > "$REPORT"
echo "$REPORT"
