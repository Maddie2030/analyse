#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
FOLLOW=0
[[ "${1:-}" == "--follow" ]] && FOLLOW=1

echo "=== MReader Docker test runner status ==="
date
if [[ -f test-results/.runner-status ]]; then
  echo; echo "=== Host runner phase ==="; cat test-results/.runner-status
  pid="$(awk -F= '$1=="pid"{print $2}' test-results/.runner-status 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then echo "runner_process=alive"; else echo "runner_process=not-running"; fi
fi

echo; echo "=== Docker test containers ==="
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null | grep -E 'NAMES|mreader-(api-tests|k6-tests|k6-breakpoint|load-seed|test-preflight)' || echo '(none found)'

echo; echo "=== Local test images ==="
docker images --format '{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}\t{{.Size}}' 2>/dev/null | grep -E '^mreader/(api-tests|k6-tests):' || echo '(none found)'

echo; echo "=== Current application gateways ==="
kubectl -n mreader-user get deploy user-gateway 2>/dev/null || true
kubectl -n mreader-admin get deploy admin-gateway 2>/dev/null || true

echo; echo "=== Latest pytest/hybrid result ==="
hrun="$(ls -td test-results/hybrid/* 2>/dev/null | head -1 || true)"
if [[ -n "$hrun" ]]; then
  echo "$hrun"; ls -lah "$hrun" 2>/dev/null || true
  [[ -f "$hrun/SUMMARY.txt" ]] && { echo; cat "$hrun/SUMMARY.txt"; }
  [[ -f "$hrun/pytest.log" ]] && { echo; echo '--- pytest tail ---'; tail -30 "$hrun/pytest.log"; }
else echo '(no hybrid result directory yet)'; fi

echo; echo "=== Latest capacity result ==="
crun="$(ls -td test-results/capacity/* 2>/dev/null | head -1 || true)"
if [[ -n "$crun" ]]; then
  echo "$crun"; [[ -f "$crun/results.tsv" ]] && { echo; echo '--- completed staircase steps ---'; tail -20 "$crun/results.tsv"; }
else echo '(no capacity result directory yet)'; fi

if [[ $FOLLOW -eq 1 ]]; then
  name=""
  for candidate in mreader-api-tests mreader-k6-breakpoint mreader-k6-tests mreader-load-seed mreader-test-preflight; do
    running="$(docker inspect -f '{{.State.Running}}' "$candidate" 2>/dev/null || true)"
    if [[ "$running" == true ]]; then name="$candidate"; break; fi
  done
  if [[ -z "$name" ]]; then
    for candidate in mreader-api-tests mreader-k6-breakpoint mreader-k6-tests mreader-load-seed mreader-test-preflight; do
      docker inspect "$candidate" >/dev/null 2>&1 && { name="$candidate"; break; }
    done
  fi
  [[ -n "$name" ]] || { echo "No current/recent Docker test container to follow." >&2; exit 1; }
  echo; echo "=== Following Docker container: $name ==="
  exec docker logs -f "$name"
fi
