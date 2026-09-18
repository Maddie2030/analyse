#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }

for f in scripts/run-release-qualification.sh scripts/run-browser-tests.sh scripts/run-runtime-integration-tests.sh scripts/run-spike-tests.sh scripts/run-soak-tests.sh scripts/run-chaos-tests.sh scripts/tests/post-run-integrity.sh tests/load/spike.js tests/load/soak.js tests/load/workload-common.js tests/browser/admin-scraper-reader-flow.spec.mjs tests/browser/user-journey.spec.mjs tests/browser/admin-ui-smoke.spec.mjs; do
  [[ -s "$f" ]] || fail "missing comprehensive test component $f"
done
q="scripts/run-release-qualification.sh"
for token in 'static-regressions' 'api-integration' 'browser-e2e' 'runtime-integration' 'breakpoint-load' 'spike-recovery' 'soak-endurance' 'post-run-integrity'; do grep -q "$token" "$q" || fail "qualification runner missing phase $token"; done
grep -q 'MREADER_ALLOW_DESTRUCTIVE_TESTS' "$q" || fail '--everything must explicitly gate destructive chaos'
grep -q 'external-scraper' "$q" || fail '--everything must include external scraper coverage'
grep -q 'rabbitmq-chaos' "$q" || fail '--everything must include chaos coverage'

grep -q 'MREADER_BROWSER_ADMIN_BASE_URL' tests/browser/reader-long-chapter.spec.mjs || fail 'reader E2E must use admin plane for fixture writes'
grep -q 'MREADER_BROWSER_ADMIN_BASE_URL' tests/browser/admin-scraper-reader-flow.spec.mjs || fail 'scraper E2E must separate admin/user planes'
grep -q '/api/scraper/batches' tests/browser/admin-scraper-reader-flow.spec.mjs || fail 'missing admin->scraper batch E2E'
grep -q '/read/' tests/browser/admin-scraper-reader-flow.spec.mjs || fail 'scraper E2E must finish through browser Reader'
grep -q '/register' tests/browser/user-journey.spec.mjs || fail 'missing browser registration journey'
grep -q 'Bookmarked' tests/browser/user-journey.spec.mjs || fail 'missing browser bookmark journey'
grep -q 'Subscribed' tests/browser/user-journey.spec.mjs || fail 'missing browser subscription journey'
grep -q "Admin Dashboard" tests/browser/admin-ui-smoke.spec.mjs || fail 'missing admin frontend dashboard journey'
grep -q "/admin/scraper/operations" tests/browser/admin-ui-smoke.spec.mjs || fail 'admin frontend journey must cover scrape operations UI'
grep -q "userBaseURL}/admin" tests/browser/admin-ui-smoke.spec.mjs || fail 'admin frontend journey must assert user-plane isolation'
grep -q 'authenticated non-admin user' tests/browser/admin-ui-smoke.spec.mjs || fail 'admin frontend journey must assert AdminOnly role guard'
grep -q "postgresql\\+" tests/browser/admin-ui-smoke.spec.mjs || fail 'browser DB URL must normalize SQLAlchemy asyncpg scheme for node-postgres'
grep -q 'postgresql+\*://\*) DB_URL=' scripts/run-browser-tests.sh || fail 'browser runner must normalize SQLAlchemy database URLs before passing them to node-postgres'

for phase in baseline spike recovery; do grep -q "$phase" tests/load/spike.js || fail "spike.js missing $phase phase"; done
grep -q 'constant-arrival-rate' tests/load/spike.js || fail 'HTTP spike must use arrival-rate traffic, not only VUs'
grep -q 'K6_SOAK_DURATION_SECONDS' tests/load/soak.js || fail 'soak duration must be configurable'
# Every declared workload must be implemented by the shared executor and therefore
# exercise identical request/auth semantics in breakpoint, spike and soak runners.
while IFS='|' read -r workload _; do
  [[ -z "$workload" || "$workload" == \#* ]] && continue
  grep -q "'$workload'" tests/load/workload-common.js || fail "shared load executor missing $workload"
done < tests/load/workloads.tsv

grep -q 'api-route-audit.py' tests/api/Dockerfile || fail 'Dockerized API suite must carry route coverage auditor'
grep -q 'api-route-audit.py' scripts/run-hybrid-tests.sh || fail 'API test runner must execute route coverage audit'
grep -q 'test_23_endpoint_contract_matrix.py' tests/api/endpoint_coverage.tsv || fail 'endpoint manifest must cite targeted endpoint contract tests'

grep -q 'stale_outbox' scripts/tests/post-run-integrity.sh || fail 'post-run integrity missing outbox check'
grep -q 'OOMKilled' scripts/tests/post-run-integrity.sh || fail 'post-run integrity missing OOM detection'
grep -q 'rabbit-backlog' scripts/tests/post-run-integrity.sh || fail 'post-run integrity missing RabbitMQ drain check'
grep -q 'stale_database_operations' scripts/tests/post-run-integrity.sh || fail 'post-run integrity missing stale database-operation check'
grep -q 'failed_database_operations' scripts/tests/post-run-integrity.sh || fail 'post-run integrity missing failed database-operation check'
grep -q 'PIPESTATUS' scripts/run-release-qualification.sh || fail 'qualification runner must preserve phase/log pipeline status'
grep -q 'tee_rc' scripts/run-release-qualification.sh || fail 'qualification runner must fail on log-capture errors'
grep -q 's.fail<0.50' tests/load/spike.js || fail 'spike test must require at least half of delivered peak requests to succeed'
grep -q 'mreader_spike_peak_status_429' tests/load/spike.js || fail 'spike test must isolate peak 429 shedding from baseline/recovery'
grep -q 'mreader_spike_peak_server_errors' tests/load/spike.js || fail 'spike test must measure peak 5xx rate separately'
grep -q 'realtime-series-%' scripts/tests/post-run-integrity.sh || fail 'post-run integrity must detect realtime browser fixture leaks'
grep -q "slug LIKE 'pytest-%'" scripts/tests/post-run-integrity.sh || fail 'post-run integrity must detect pytest series leaks'


for f in diagnose-mreader.sh scripts/diagnostics/run-diagnostics.sh scripts/diagnostics/collect-runtime-evidence.sh scripts/diagnostics/analyze_report.py scripts/diagnostics/report_builder.py tests/diagnostics/Dockerfile tests/regression/diagnostics-python-unit.sh; do
  [[ -s "$f" ]] || fail "missing dedicated diagnostics component $f"
done
grep -q 'REPORT_BUNDLE.zip' scripts/diagnostics/run-diagnostics.sh || fail 'diagnostics runner must surface report bundle'
grep -q 'api-route-audit.py' tests/diagnostics/runner.py || fail 'diagnostics container must execute route coverage audit'

echo 'comprehensive test harness static regression PASS'
