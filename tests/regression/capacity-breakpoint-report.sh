#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/results.tsv" <<'TSV'
workload	service	level	unit	requests	throughput	p50_ms	p95_ms	p99_ms	failure_rate	dropped	dropped_rate	status_429	state	p95_slo_ms	p99_slo_ms	attempt
catalog_detail	catalog-go	20	rps	1200	20	10	100	180	0	0	0	0	OPTIMAL	450	1000	1
catalog_detail	catalog-go	40	rps	2400	40	15	250	500	0.002	0	0	0	PASS	450	1000	1
catalog_detail	catalog-go	60	rps	3600	59	25	700	1200	0.02	0	0	0	FAIL	450	1000	1
catalog_detail	catalog-go	60	rps	3600	59	25	720	1250	0.02	0	0	0	FAIL	450	1000	2
auth_login	auth-service	20	rps	1200	20	100	500	900	0	0	0	0	PASS	1200	2500	1
auth_login	auth-service	30	rps	1800	30	120	600	1000	0.02	0	0	25	FAIL	1200	2500	1
auth_login	auth-service	30	rps	1800	30	120	600	1000	0.02	0	0	30	FAIL	1200	2500	2
TSV
"$ROOT/scripts/tests/build-breakpoint-report.sh" "$TMP" >/dev/null
grep -q $'catalog_detail\tcatalog-go\t20\t40\t60\trps\tHTTP/logical error saturation' "$TMP/CAPACITY_SUMMARY.tsv"
grep -q $'auth_login\tauth-service\tnot-found\t20\t30\trps\tAuth 429 policy limit' "$TMP/CAPACITY_SUMMARY.tsv"
grep -q 'First confirmed break' "$TMP/CAPACITY_REPORT.md"
echo 'capacity breakpoint report regression PASSED'
