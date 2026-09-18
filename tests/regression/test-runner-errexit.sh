#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/docker" <<'FAKE'
#!/usr/bin/env bash
case "${1:-}" in
  rm) exit 0 ;;
  run) echo "synthetic docker output"; exit "${FAKE_DOCKER_RC:-37}" ;;
  inspect) exit 0 ;;
  cp) exit "${FAKE_DOCKER_CP_RC:-0}" ;;
  *) exit 0 ;;
esac
FAKE
cat > "$TMP/tee" <<'FAKE'
#!/usr/bin/env bash
out="${@: -1}"
cat > "$out"
exit "${FAKE_TEE_RC:-0}"
FAKE
chmod +x "$TMP/docker" "$TMP/tee"
PATH="$TMP:$PATH"
TEST_RUNNER_STATUS_FILE="$TMP/status"

set +e
FAKE_DOCKER_RC=37 FAKE_TEE_RC=0 run_docker_test fake-test "$TMP/run.log" fake/image true
rc=$?
[[ $rc -eq 37 ]] || { echo "FAIL: expected docker rc=37, got $rc" >&2; exit 1; }
[[ $- != *e* ]] || { echo 'FAIL: run_docker_test unexpectedly enabled errexit for a set +e caller' >&2; exit 1; }
grep -q 'synthetic docker output' "$TMP/run.log" || { echo 'FAIL: failed-container log was not retained' >&2; exit 1; }
grep -q 'container-failed' "$TMP/status" || { echo 'FAIL: failed-container status was not retained' >&2; exit 1; }

FAKE_DOCKER_RC=0 FAKE_TEE_RC=55 run_docker_test fake-log "$TMP/logfail.log" fake/image true
rc=$?
[[ $rc -eq 55 ]] || { echo "FAIL: expected log-capture rc=55, got $rc" >&2; exit 1; }
grep -q 'log_exit=55' "$TMP/status" || { echo 'FAIL: log-capture failure was not exposed in runner status' >&2; exit 1; }

set -e
if FAKE_DOCKER_RC=37 FAKE_TEE_RC=0 run_docker_test fake-test-2 "$TMP/run2.log" fake/image true; then
  echo 'FAIL: synthetic failing docker unexpectedly passed' >&2; exit 1
else
  rc=$?
fi
[[ $rc -eq 37 ]] || { echo "FAIL: expected docker rc=37 under errexit caller, got $rc" >&2; exit 1; }
[[ $- == *e* ]] || { echo 'FAIL: run_docker_test unexpectedly disabled caller errexit' >&2; exit 1; }

FAKE_DOCKER_CP_RC=0 test_copy_results fake-test "$TMP/results-ok" || { echo 'FAIL: successful result copy reported failure' >&2; exit 1; }
if FAKE_DOCKER_CP_RC=61 test_copy_results fake-test "$TMP/results-fail"; then
  echo 'FAIL: failed result copy was silently accepted' >&2; exit 1
fi

echo 'test runner errexit/log/result-artifact regression PASSED'
