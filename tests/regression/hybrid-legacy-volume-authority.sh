#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "FAIL: $*" >&2; exit 1; }
script=scripts/hybrid/adopt-existing-stateful-volumes.sh
[[ -x "$script" ]] || fail "stateful adoption helper missing"
# Upgrade policy: automatic adoption must be deterministic and must not depend
# on catalog inspection to choose between a populated legacy volume and a
# bootstrap-created canonical volume. Legacy wins unless the operator explicitly
# disables legacy-first selection or pins another volume.
! grep -Fq 'MREADER_PG_VOLUME_INSPECTOR' "$script" || fail "automatic PGDATA adoption still depends on catalog inspector"
! grep -Fq 'catalog_state=' "$script" || fail "automatic PGDATA adoption still branches on catalog inspection"
grep -Fq 'if $l_live; then' "$script" || fail "legacy-first PGDATA branch missing"
grep -Fq 'selected="$legacy"' "$script" || fail "legacy PGDATA is not selected by upgrade policy"
echo 'hybrid legacy-volume authority regression PASSED'
