#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "diagnostics harness static regression FAILED: $*" >&2; exit 1; }
[[ -x diagnose-mreader.sh ]] || fail 'diagnose-mreader.sh missing or not executable'
[[ -f scripts/diagnostics/run-diagnostics.sh ]] || fail 'run-diagnostics.sh missing'
grep -Fq 'scripts/diagnostics/run-diagnostics.sh' diagnose-mreader.sh || fail 'top-level wrapper does not delegate to diagnostics runner'
grep -Fq -- '--diagnose' scripts/test-mreader.sh || fail 'test-mreader.sh lacks --diagnose alias'
grep -Fq 'scripts/diagnostics/run-diagnostics.sh' scripts/test-mreader.sh || fail 'test-mreader.sh does not delegate diagnose mode'
grep -Fq 'scripts/tests/test-runner-common.sh' scripts/diagnostics/run-diagnostics.sh || fail 'runner does not use shared test helpers'
grep -Fq 'scripts/docker/msys-paths.sh' scripts/diagnostics/run-diagnostics.sh || fail 'runner does not use shared MSYS path helpers'
! grep -Eq '(^|[;&|[:space:]])(python|python3|jq)([[:space:]]|$)' scripts/diagnostics/run-diagnostics.sh || fail 'runner requires host Python/jq'
grep -Fq 'test-results/diagnostics' scripts/diagnostics/run-diagnostics.sh || fail 'diagnostics result root missing'
grep -Fq 'mreader/diagnostics:' scripts/diagnostics/run-diagnostics.sh || fail 'dedicated diagnostics image missing'
grep -Fq 'mreader-diagnostics-' scripts/diagnostics/run-diagnostics.sh || fail 'dedicated diagnostics container name missing'
grep -Fq 'analyze_report.py' tests/diagnostics/runner.py || fail 'diagnostics container does not run report analyzer'
grep -Fq 'report_builder.py' tests/diagnostics/runner.py || fail 'diagnostics container does not build final report'
grep -Fq 'REPORT_BUNDLE.zip' scripts/diagnostics/run-diagnostics.sh || fail 'host runner does not surface final report bundle'
grep -Fq "FROM mreader/api-tests:$(cat VERSION)" tests/diagnostics/Dockerfile || fail 'diagnostics Dockerfile base does not match exact MReader release'
for needle in '--scraper-series-url' '--scraper-chapter-url' '--chapter-file' '--cover-image' '--no-browser'; do
  grep -Fq -- "$needle" scripts/diagnostics/run-diagnostics.sh || fail "diagnostics input flag missing: $needle"
done
grep -Fq 'tests/browser/Dockerfile' scripts/diagnostics/run-diagnostics.sh || fail 'full diagnostics does not integrate browser actor journeys'
grep -Fq 'browser-ui' scripts/diagnostics/run-diagnostics.sh || fail 'browser actor stage is not recorded'
grep -Fq 'MREADER_DIAGNOSTICS_CHAPTER_FILE' scripts/diagnostics/run-diagnostics.sh || fail 'chapter fixture is not passed to diagnostics container'
grep -Fq 'MREADER_DIAGNOSTICS_SERIES_URL' scripts/diagnostics/run-diagnostics.sh || fail 'scraper series fixture is not passed to diagnostics container'
echo 'diagnostics harness static regression PASS'
