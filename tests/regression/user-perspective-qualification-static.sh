#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "user-perspective qualification regression FAILED: $*" >&2; exit 1; }

grep -q -- '--user-800' scripts/test-mreader.sh || fail 'top-level --user-800 mode missing'
grep -q 'run-user-perspective-qualification.sh' scripts/test-mreader.sh || fail 'top-level qualification dispatch missing'
grep -q 'CANONICAL_TARGET = 800' scripts/tests/build-user-perspective-report.py || fail 'canonical 800-case report gate missing'
grep -q 'ui-access-point-audit.py' scripts/run-user-perspective-qualification.sh || fail 'UI access-point inventory stage missing'
grep -q 'diagnose-mreader.sh' scripts/run-user-perspective-qualification.sh || fail 'full diagnostics stage missing'
grep -q 'MREADER_PYTHON_FORCE_DOCKER=1.*python-runtime.sh.*ui-access-point-audit.py' scripts/run-user-perspective-qualification.sh || fail 'UI access audit is not forced through Docker Python runtime'
grep -q 'MREADER_PYTHON_FORCE_DOCKER=1.*python-runtime.sh.*build-user-perspective-report.py' scripts/run-user-perspective-qualification.sh || fail 'qualification report builder is not forced through Docker Python runtime'
grep -q 'tests/api/Dockerfile' scripts/diagnostics/run-diagnostics.sh || fail 'dedicated API test image build missing'
grep -q 'tests/diagnostics/Dockerfile' scripts/diagnostics/run-diagnostics.sh || fail 'dedicated diagnostics image build missing'
grep -q 'docker run -d --name "$DIAGNOSTICS_CONTAINER"' scripts/diagnostics/run-diagnostics.sh || fail 'diagnostics suite is not launched in a dedicated Docker container'
grep -q '_with_junit' tests/diagnostics/runner.py || fail 'core API JUnit evidence helper missing'
grep -q "expression='not external and not permission and not boundary'" tests/diagnostics/runner.py || fail 'core API marker isolation missing'
grep -q 'junit-api.xml' tests/diagnostics/runner.py || fail 'core API JUnit evidence path missing'
grep -q 'MREADER_BROWSER_SCRAPER_SERIES_URL' scripts/diagnostics/run-diagnostics.sh || fail 'external scraper URL is not passed into Playwright'
grep -q 'MREADER_TEST_ADMIN_PASSWORD' scripts/diagnostics/run-diagnostics.sh || fail 'disposable admin credentials are not passed to diagnostics'
grep -q 'admin new-series Analyze button discovers the supplied real series URL' tests/browser/admin-external-series-discovery.spec.mjs || fail 'real scraper UI Analyze-button test missing'

# Keep this gate host-dependency free: inventory the source shape with POSIX tools.
# The exact semantic UI inventory is executed by ui-access-point-audit.py in the
# forced-Docker qualification stage above.
route_count="$(grep -c '<Route' frontend/src/App.tsx || true)"
button_count="$(grep -Rho '<button\b' frontend/src/pages frontend/src/components --include='*.tsx' | wc -l | tr -d ' ')"
access_count="$(grep -RhoE '<(button|Link|NavLink|RRNavLink|a)\b|onClick[[:space:]]*=' frontend/src/pages frontend/src/components --include='*.tsx' | wc -l | tr -d ' ')"
[[ "$route_count" -ge 19 ]] || fail "expected at least 19 route declarations, found $route_count"
[[ "$button_count" -ge 120 ]] || fail "expected at least 120 button declarations, found $button_count"
[[ "$access_count" -ge 200 ]] || fail "expected at least 200 interactive access-point declarations, found $access_count"

echo 'user-perspective qualification regression PASSED'
