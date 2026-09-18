#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }
[[ -x scripts/hybrid/inspect-postgres-volumes.sh ]] || fail "PostgreSQL volume inspection helper missing"
sh -n scripts/hybrid/inspect-postgres-volumes.sh || fail "PostgreSQL volume inspection helper syntax invalid"
grep -Fq 'mreader_pgdata' scripts/hybrid/inspect-postgres-volumes.sh || fail "canonical PG volume not inspected"
grep -Fq 'mreader-hybrid-stateful_pgdata' scripts/hybrid/inspect-postgres-volumes.sh || fail "legacy PG volume not inspected"
grep -Fq 'series_count' scripts/hybrid/inspect-postgres-volumes.sh || fail "catalog series count not reported"
grep -Fq 'chapter_count' scripts/hybrid/inspect-postgres-volumes.sh || fail "catalog chapter count not reported"
grep -Fq 'page_count' scripts/hybrid/inspect-postgres-volumes.sh || fail "catalog page count not reported"
grep -Fq 'temporary clone' scripts/hybrid/inspect-postgres-volumes.sh || fail "helper does not document safe clone inspection"
! grep -Fq 'MREADER_PG_VOLUME_INSPECTOR' scripts/hybrid/adopt-existing-stateful-volumes.sh || fail "automatic adoption must not depend on the manual PG inspector"
echo 'hybrid PostgreSQL volume inspection static regression PASSED'
