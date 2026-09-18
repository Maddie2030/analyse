#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "repository path/static layout regression FAILED: $*" >&2; exit 1; }
[[ -d deploy/compose && -d deploy/docker-desktop-hybrid ]] || fail 'canonical hybrid deployment directories are missing'
[[ ! -d deploy/helm && ! -d deploy/platform && ! -d deploy/gateway ]] || fail 'retired deployment tree still exists'
[[ -d docs/architecture && -d docs/deployment && -d docs/development && -d docs/operations ]] || fail 'documentation layout is incomplete'
! find . -maxdepth 1 -type f -name 'docker-compose*.yml' | grep -q . || fail 'root-level Compose file remains'
mapfile -t compose_files < <(find deploy/compose -maxdepth 1 -type f -name 'docker-compose*.yml' -printf '%f\n' | sort)
expected=(docker-compose.hybrid-build.yml docker-compose.hybrid-public-edge.yml docker-compose.hybrid-stateful.yml)
[[ "${compose_files[*]}" == "${expected[*]}" ]] || { printf 'found: %s\n' "${compose_files[*]}" >&2; fail 'Compose surface is not the three canonical hybrid files'; }
for file in deploy/compose/docker-compose.hybrid-*.yml; do
  ! grep -qE '^[[:space:]]+context:[[:space:]]+\.$' "$file" || fail "$file has a moved/ambiguous build context"
done
grep -q 'context: ../..' deploy/compose/docker-compose.hybrid-build.yml || fail 'hybrid build context is not repository root'
grep -q 'deploy/compose/' scripts/ci/service-matrix.sh || fail 'CI matrix does not watch canonical Compose changes'
! grep -Eq 'deploy/(helm|platform|gateway)' scripts/ci/service-matrix.sh Jenkinsfile || fail 'CI still references retired deployment trees'
! grep -Eq 'helm upgrade|GitOps|update-gitops' Jenkinsfile || fail 'Jenkins still deploys a second runtime architecture'
grep -Fq 'docker-compose.hybrid-build.yml' scripts/hybrid/build-images.sh || fail 'hybrid build helper does not use build-only Compose'
! grep -Fq 'docker-compose.core.yml' scripts/hybrid/build-images.sh || fail 'hybrid build still inherits retired core Compose'
for f in tests/api/Dockerfile tests/api/requirements.txt tests/load/Dockerfile tests/load/breakpoint.js tests/load/seed.py tests/load/workloads.tsv scripts/run-hybrid-tests.sh scripts/run-breakpoint-tests.sh scripts/tests/test-runner-common.sh scripts/tests/show-test-status.sh scripts/tests/build-hybrid-report.sh scripts/tests/build-breakpoint-report.sh; do
  [[ -f "$f" ]] || fail "missing path-integrity target: $f"
done
grep -Fq 'docker build --progress=plain -t "$API_IMAGE" -f tests/api/Dockerfile .' scripts/run-hybrid-tests.sh || fail 'hybrid API test build context drifted'
grep -Fq 'docker build --progress=plain -t "$K6_IMAGE" -f tests/load/Dockerfile .' scripts/run-breakpoint-tests.sh || fail 'hybrid load-test build context drifted'
for f in hybrid-up.sh hybrid-down.sh db-backup.sh db-restore.sh test-mreader.sh; do [[ -x "$f" ]] || fail "$f is not executable"; done
echo 'repository path/static layout regression PASSED'
