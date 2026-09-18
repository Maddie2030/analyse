#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
manifest=tests/api/endpoint_coverage.tsv
[[ -s "$manifest" ]] || { echo 'FAIL: endpoint coverage manifest missing' >&2; exit 1; }
header="$(head -n1 "$manifest" | tr -d '\r')"
[[ "$header" == $'method\tpath\tcoverage\tevidence' ]] || { echo "FAIL: bad endpoint coverage header: $header" >&2; exit 1; }
count="$(awk -F'\t' 'NR>1 && NF>=4{n++}END{print n+0}' "$manifest")"
(( count >= 100 )) || { echo "FAIL: suspiciously small API inventory: $count" >&2; exit 1; }
dups="$(awk -F'\t' 'NR>1{k=$1 FS $2; seen[k]++} END{for(k in seen) if(seen[k]>1) n++} END{print n+0}' "$manifest")"
[[ "$dups" == 0 ]] || { echo "FAIL: duplicate method/path rows in endpoint manifest: $dups" >&2; exit 1; }
while IFS=$'\t' read -r method path coverage evidence; do
  [[ "$method" == method ]] && continue
  case "$coverage" in functional|integration|e2e|authz|validation) ;; *) echo "FAIL: invalid coverage class $coverage for $method $path" >&2; exit 1;; esac
  [[ -f "$evidence" ]] || { echo "FAIL: missing evidence $evidence for $method $path" >&2; exit 1; }
done < "$manifest"
# Run the semantic source-vs-manifest parser when a host interpreter exists.
# Dockerized pytest always runs the same audit, so Windows hosts need no Python.
if command -v python3 >/dev/null 2>&1; then python3 scripts/tests/api-route-audit.py
elif command -v python >/dev/null 2>&1; then python scripts/tests/api-route-audit.py
else echo 'API manifest structural audit PASS; semantic audit deferred to Dockerized API gate (no host Python).'; fi
echo "API route coverage static regression PASS: $count classified routes"
