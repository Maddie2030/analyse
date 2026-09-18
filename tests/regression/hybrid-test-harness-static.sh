#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ -f tests/load/breakpoint.js && -f tests/load/workloads.tsv && -f tests/load/Dockerfile && -f tests/load/seed.py ]]
[[ ! -f tests/load/mixed.js ]]
[[ -f tests/api/Dockerfile && -f tests/api/conftest.py ]]
[[ -x scripts/run-hybrid-tests.sh ]]
[[ -x scripts/run-breakpoint-tests.sh ]]
[[ -x scripts/tests/build-breakpoint-report.sh ]]
[[ -x scripts/tests/test-runner-common.sh ]]
[[ -x scripts/tests/show-test-status.sh ]]

grep -q 'TEST_USER_BASE_URL' tests/api/conftest.py
grep -q 'TEST_ADMIN_BASE_URL' tests/api/conftest.py
! grep -q 'http://gateway' tests/api/conftest.py
! grep -q 'svc.cluster.local' tests/api/conftest.py
! grep -q 'svc.cluster.local' tests/load/breakpoint.js

grep -q 'host.docker.internal' scripts/run-hybrid-tests.sh
grep -q 'host.docker.internal' scripts/run-breakpoint-tests.sh
grep -q 'TEST_SEAWEEDFS_FILER_URL' scripts/run-hybrid-tests.sh
grep -q 'TEST_SEAWEEDFS_FILER_URL' scripts/run-breakpoint-tests.sh
grep -q 'TEST_DATABASE_URL' scripts/run-hybrid-tests.sh
grep -q 'test_stateful_network' scripts/run-hybrid-tests.sh
grep -q 'test_stateful_network' scripts/run-breakpoint-tests.sh
! grep -q 'kubectl apply' scripts/run-hybrid-tests.sh
! grep -q 'mixed.js' scripts/run-hybrid-tests.sh
! grep -q 'kubectl apply' scripts/run-breakpoint-tests.sh
grep -q -- '--status' scripts/test-mreader.sh
grep -q -- '--follow' scripts/test-mreader.sh
grep -q 'docker logs -f' scripts/tests/show-test-status.sh

grep -q 'grafana/k6:2.2.0' tests/load/Dockerfile
grep -q 'constant-arrival-rate' tests/load/breakpoint.js
grep -q 'per-vu-iterations' tests/load/breakpoint.js
grep -q 'MREADER_BREAKPOINT_RESULT' tests/load/breakpoint.js
grep -q 'OPTIMAL' tests/load/breakpoint.js
grep -q 'First failure' scripts/run-breakpoint-tests.sh
grep -q 'Confirmed breaking point' scripts/run-breakpoint-tests.sh
grep -q 'CAPACITY_REPORT.md' scripts/tests/build-breakpoint-report.sh
grep -q 'reader_image' tests/load/workloads.tsv
grep -q 'realtime_ws' tests/load/workloads.tsv
# Preserve the requested gradual capacity ladders and confirmation semantics.
grep -Fq 'LEVELS=(1 2 5 10 15 20 30 40 60 80 100)' scripts/run-breakpoint-tests.sh
grep -Fq 'LEVELS=(1 2 5 10 15 20 30 40 60 80 100 125 150 200 250 300)' scripts/run-breakpoint-tests.sh
grep -q 'failureRate<=OPTIMAL_ERROR_RATE' tests/load/breakpoint.js
grep -q 'p95<=P95_SLO\*0.70' tests/load/breakpoint.js
grep -q 'p99<=P99_SLO\*0.75' tests/load/breakpoint.js
grep -q 'droppedRate<0.005' tests/load/breakpoint.js
grep -q 'status429Count' tests/load/breakpoint.js
grep -q 'kubectl top pods' scripts/run-breakpoint-tests.sh
grep -q 'kubectl -n mreader-user get hpa' scripts/run-breakpoint-tests.sh
grep -q 'kubectl -n mreader-admin get hpa' scripts/run-breakpoint-tests.sh
grep -q 'kubectl -n mreader-user get scaledobjects' scripts/run-breakpoint-tests.sh
grep -q 'kubectl -n mreader-admin get scaledobjects' scripts/run-breakpoint-tests.sh
awk -F'|' '$1 !~ /^#/ && NF { if (($6+0) < 300) exit 1 }' tests/load/workloads.tsv
grep -q 'docker stats --no-stream' scripts/run-breakpoint-tests.sh
# Dummy fixtures must satisfy the current Auth and v4 page contracts.
grep -q '_ACCOUNT_RUN_TOKEN' tests/api/conftest.py
grep -q 'encoding_version, encoding_rows, encoding_columns, encoding_seed' tests/api/conftest.py
grep -q 'VALUES (%s::uuid, %s, %s, 24, 32, 4, 1, 1, %s)' tests/api/conftest.py
grep -q 'history_retained' tests/api/test_18_scraper_operations.py
grep -q 'operation_group.*acknowledged' tests/api/test_18_scraper_operations.py
grep -q 'k6-v4-' tests/load/seed.py
grep -q 'full) exec ./scripts/run-release-qualification.sh --full' scripts/test-mreader.sh
grep -q 'capacity) exec ./scripts/run-breakpoint-tests.sh --standard' scripts/test-mreader.sh

grep -q 'K6_TEST_LOGIN_USERNAME' tests/load/workload-common.js
grep -q 'SERIES_WORKLOADS = new Set' tests/load/workload-common.js
grep -q 'USER_AUTH_WORKLOADS = new Set' tests/load/workload-common.js
grep -q 'LOGIN_USERNAME' tests/load/seed.py
grep -q 'K6_LOGIN_USERNAME="mreader_k6_login_' scripts/run-breakpoint-tests.sh
! grep -q 'K6_TEST_PASSWORD=' tests/load/seed.py

grep -q '/api/progress/.*/commit' tests/api/test_17_smart_library.py
! grep -q "read_latest = user.session.get(f'/api/reader" tests/api/test_17_smart_library.py

echo 'Dockerized twin-plane gradual breakpoint test harness static regression PASSED'
