#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x scripts/tests/test-runner-common.sh ]] || fail "missing executable test-runner-common.sh"
[[ -x scripts/tests/show-test-status.sh ]] || fail "missing executable show-test-status.sh"
grep -q 'run_docker_test' scripts/tests/test-runner-common.sh || fail "live Docker test helper missing"
grep -q 'test_set_status' scripts/tests/test-runner-common.sh || fail "host-side runner status tracking missing"
grep -q 'test-results/.runner-status' scripts/tests/show-test-status.sh || fail "status command does not display host runner phase"
grep -q 'docker logs -f' scripts/tests/show-test-status.sh || fail "Docker log follow support missing"
grep -q -- '--status' scripts/test-mreader.sh || fail "test-mreader --status missing"
grep -q -- '--follow' scripts/test-mreader.sh || fail "test-mreader --follow missing"
grep -q -- '--progress=plain' scripts/run-hybrid-tests.sh || fail "pytest runner image build progress hidden"
grep -q -- '--progress=plain' scripts/run-breakpoint-tests.sh || fail "breakpoint runner image build progress hidden"
grep -q 'python -u -m pytest -vv' scripts/run-hybrid-tests.sh || fail "pytest is not live/unbuffered/verbose"
grep -q 'host.docker.internal' scripts/run-hybrid-tests.sh || fail "Docker runner does not target host-exposed gateways"
grep -q 'TEST_SEAWEEDFS_FILER_URL' scripts/run-hybrid-tests.sh || fail "NAS filer is not explicitly wired into Docker tests"
grep -q 'test_stateful_network' scripts/run-hybrid-tests.sh || fail "Docker test runner does not join stateful network"
! grep -q 'run_k8s_test_job' scripts/run-hybrid-tests.sh || fail "active pytest runner still creates Kubernetes test Jobs"
! grep -q 'run_k8s_test_job' scripts/run-breakpoint-tests.sh || fail "active capacity runner still creates Kubernetes test Jobs"
# The pytest correctness runner must never build or invoke k6; capacity has its own runner.
! grep -q 'tests/load/Dockerfile' scripts/run-hybrid-tests.sh || fail "pytest runner still builds k6"
! grep -q 'K6_PROFILE' scripts/run-hybrid-tests.sh || fail "pytest runner still exposes mixed k6 profiles"

echo "PASS: observable Dockerized test runner"
