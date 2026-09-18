#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source scripts/tests/test-runner-common.sh

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
uname(){ printf '%s\n' 'MINGW64_NT-10.0-22631'; }
docker(){
  printf 'excl=%s\n' "${MSYS2_ARG_CONV_EXCL:-}" > "$TMP/call"
  printf 'args=' >> "$TMP/call"; printf '%q ' "$@" >> "$TMP/call"; printf '\n' >> "$TMP/call"
}

test_docker_run --rm mreader/api-tests:test python -u /load/seed.py create

grep -q '/load' "$TMP/call"
grep -q '/tests' "$TMP/call"
grep -q '/repo' "$TMP/call"
grep -q '/load/seed.py' "$TMP/call"
! grep -q 'Program.Files.Git' "$TMP/call"

grep -q 'test_docker_run --name mreader-test-preflight' scripts/run-breakpoint-tests.sh
grep -q 'test_docker_run --name mreader-test-preflight' scripts/run-hybrid-tests.sh
grep -q 'test_docker_run --rm' scripts/run-api-route-audit.sh

echo 'MSYS container-path conversion contract PASS'
