#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
MODE=full; WORKLOAD=""; KEEP_DATA=0; STATUS_FOLLOW=0; USER_800_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) MODE=quick; shift;; --full) MODE=full; shift;; --everything) MODE=everything; shift;;
    --capacity|--k6-only) MODE=capacity; shift;; --capacity-deep) MODE=capacity-deep; shift;;
    --spike) MODE=spike; shift;; --spike-deep) MODE=spike-deep; shift;;
    --soak) MODE=soak; shift;; --soak-deep) MODE=soak-deep; shift;;
    --pytest-only) MODE=pytest; shift;; --browser-only) MODE=browser; shift;;
    --regression-only) MODE=regression; shift;; --runtime-integration|--runtime-regressions) MODE=runtime; shift;;
    --chaos) MODE=chaos; shift;; --external) MODE=external; shift;;
    --api-route-audit) MODE=route-audit; shift;;
    --diagnose) MODE=diagnose; shift;;
    --user-800|--user-qualification) MODE=user-800; shift; USER_800_ARGS=("$@"); break;;
    --workload) WORKLOAD="${2:?workload required}"; MODE=workload; shift 2;;
    --keep-test-data) KEEP_DATA=1; shift;; --status) MODE=status; shift;; --follow) MODE=status; STATUS_FOLLOW=1; shift;;
    -h|--help)
      cat <<'HELP'
Usage: ./test-mreader.sh [MODE]

Release qualification:
  --quick        static + API/integration + browser E2E + runtime integration + short breakpoint/spike + integrity
  --full         deterministic release qualification: all above + standard breakpoint + spike/recovery + soak + integrity
  --everything   --full plus live external scraper tests and destructive RabbitMQ chaos; requires explicit env/config

Focused modes:
  --pytest-only          Dockerized functional/API/integration tests + API route coverage audit
  --browser-only         Playwright user/admin end-to-end suite
  --regression-only      fast static/config/harness regressions
  --runtime-integration  current twin-plane PostgreSQL outbox -> RabbitMQ confirmation path
  --capacity             gradual standard breakpoint ladder (16 workloads)
  --capacity-deep        deeper gradual breakpoint ladder
  --spike                true sudden spike + recovery tests
  --spike-deep           larger/longer spike + recovery tests
  --soak                 selected critical workloads for 10 minutes each
  --soak-deep            selected critical workloads for 30 minutes each
  --workload NAME        one gradual capacity workload
  --external             live external scraper tests (requires source URLs in .env)
  --chaos                RabbitMQ outage/recovery test; requires MREADER_ALLOW_DESTRUCTIVE_TESTS=1
  --api-route-audit      prove every source /api route is classified with test evidence
  --diagnose             dedicated Dockerized diagnostics + evidence/report bundle
  --user-800             full user/admin 800-case qualification ledger + all extra runtime cases
  --status / --follow    inspect current/recent test execution
HELP
      exit 0;;
    *) echo "ERROR: unsupported option $1" >&2; exit 2;;
  esac
done
keep=(); [[ $KEEP_DATA -eq 1 ]] && keep+=(--keep-test-data)
case "$MODE" in
  status) [[ $STATUS_FOLLOW -eq 1 ]] && exec ./scripts/tests/show-test-status.sh --follow || exec ./scripts/tests/show-test-status.sh;;
  quick) exec ./scripts/run-release-qualification.sh --quick;;
  full) exec ./scripts/run-release-qualification.sh --full;;
  everything) exec ./scripts/run-release-qualification.sh --everything;;
  pytest) exec ./scripts/run-hybrid-tests.sh --pytest-only "${keep[@]}";;
  browser) exec ./scripts/run-browser-tests.sh;;
  regression) exec ./scripts/run-regression-tests.sh --static;;
  runtime) exec ./scripts/run-runtime-integration-tests.sh;;
  capacity) exec ./scripts/run-breakpoint-tests.sh --standard "${keep[@]}";;
  capacity-deep) exec ./scripts/run-breakpoint-tests.sh --deep "${keep[@]}";;
  spike) exec ./scripts/run-spike-tests.sh --standard "${keep[@]}";;
  spike-deep) exec ./scripts/run-spike-tests.sh --deep "${keep[@]}";;
  soak) exec ./scripts/run-soak-tests.sh --standard "${keep[@]}";;
  soak-deep) exec ./scripts/run-soak-tests.sh --deep "${keep[@]}";;
  workload) exec ./scripts/run-breakpoint-tests.sh --standard --workload "$WORKLOAD" "${keep[@]}";;
  external) exec ./scripts/run-hybrid-tests.sh --external-only;;
  chaos) exec ./scripts/run-chaos-tests.sh;;
  route-audit) exec ./scripts/run-api-route-audit.sh;;
  diagnose) exec ./scripts/diagnostics/run-diagnostics.sh;;
  user-800) exec ./scripts/run-user-perspective-qualification.sh "${USER_800_ARGS[@]}";;
esac
