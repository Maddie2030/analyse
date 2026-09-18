#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"

fail(){ echo "RC4.84 CONSOLIDATION FAILED: $*" >&2; exit 1; }
pass(){ echo "  [ok] $*"; }

[[ "$(cat VERSION)" == "1.3.0-rc4.84" ]] || fail "VERSION is not RC4.84"
pass "release version is RC4.84"

! rg -n '/api/token/page' services/reader_go frontend/src android/app/src/main >/dev/null || fail "legacy page-token endpoint remains"
rg -n '/api/token/chapter/\{seriesSlug\}/\{chapterSlug\}' services/reader_go/internal/httpapi/api.go >/dev/null || fail "chapter-token refresh route missing"
! rg -n 'GenerateScope|GenerateBatch|func \(s \*Service\) Generate\(|func \(s \*Service\) Refresh\(' services/reader_go/internal/imagetoken/token.go >/dev/null || fail "legacy exact/scope/batch/refresh token methods remain"
! rg -n '^[[:space:]]*(Path|Scope)[[:space:]]+string' services/reader_go/internal/imagetoken/token.go >/dev/null || fail "legacy path/scope token payload remains"
pass "reader token service is chapter-grant only"

! rg -n 'refreshChapterToken\([^)]*pageNumber|refreshChapterToken\([^)]*imagePath' android/app/src/main/java >/dev/null || fail "Android chapter refresh still carries page/path compatibility arguments"
! rg -n 'protectedAssetUrls\(path, (token|grant)\)' android/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt android/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt >/dev/null || fail "Android native reader still falls back to direct protected /images origins"
! rg -n 'fun protectedAssetUrls\(|fun protectedAssetUrl\(' android/app/src/main/java/com/mreader/android/core/network/MReaderApiAdapter.kt >/dev/null || fail "Android API adapter still exposes retired direct protected-image helpers"
! rg -n 'refreshChapterToken: \(pageNumber: number\)' frontend/src/reader/ProtectedPage.tsx frontend/src/pages/Reader.tsx >/dev/null || fail "Web chapter refresh callback still models a page token"
! rg -n 'refreshChapterToken\(page\.page_number\)' frontend/src/reader/ProtectedPage.tsx >/dev/null || fail "Web protected-page component still passes page number to chapter refresh"
pass "web/android refresh callers are chapter-scoped"

! rg -n 'SALT_V2|SALT_V3|version === [23]|req\.version === [23]|encoding\.version !in 2\.\.4|decodePlainPage|encodingVersion < 3|encodingVersion >= 3' frontend/src/reader/codec.ts frontend/src/reader/codec.worker.ts android/app/src/main/java/com/mreader/android/core/codec/ProtectedPageDecoder.kt android/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt android/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt >/dev/null || fail "retired v2/v3/plain protected-page compatibility remains"
pass "protected page clients are v4-only"

[[ ! -f services/scraper_service/app/draft_image_processor.py ]] || fail "retired Scraper image processor still exists"
! rg -n 'encoding\.version if encoding else 0|encoding\.rows if encoding else None|encoding\.columns if encoding else None|encoding\.seed if encoding else None' services/image_service/app/services/image_processor.py >/dev/null || fail "v4 encoder still carries impossible nullable-encoding fallbacks"
! rg -n 'reference_missing_unrecoverable' frontend/src >/dev/null || fail "admin UI still models retired recoverable/unrecoverable staging split"
pass "v4 encoder and staging-health contracts are strict"

! rg -n 'CREATE TABLE IF NOT EXISTS reading_history|ReadingHistory' db/init.sql shared services frontend/src android/app/src/main >/dev/null || fail "runtime/fresh schema reading_history remains"
[[ -f db/migrations/048_rc483_current_baseline.sql ]] || fail "RC4.83 migration 048 missing"
rg -n 'DROP TABLE IF EXISTS reading_history' db/migrations/048_rc483_current_baseline.sql >/dev/null || fail "migration 048 does not remove reading_history"
pass "reading state has two canonical tables"

! rg -n 'JOB_PREFIX = "mediajob:|def set_job_status|def get_job_status|_safe_set_job_status|from app\.jobs import .*set_job_status|Upgrade compatibility for jobs already present in Redis|Redis status is a compatibility cache' services/image_service/app >/dev/null || fail "media status compatibility Redis ledger remains"
pass "media job status has no compatibility Redis ledger"

rg -n 'CACHE_REDIS_URL' services/image_service/app/lifecycle_worker.py deploy/docker-desktop-hybrid deploy/compose/docker-compose.hybrid-stateful.yml >/dev/null || fail "lifecycle cache redis ownership is not explicit"
pass "chapter-grant cache ownership is explicit"

! rg -n '_is_recoverable_source_url|_recoverable_source_url|_get_or_restore|reference_missing_unrecoverable|adopted new scraper staging spool|legacy staging migration' services/scraper_service/app services/image_service/app/lifecycle_worker.py >/dev/null || fail "scraper/lifecycle recovery compatibility remains"
pass "staging ownership is strict"

! rg -n 'default\("legacy"\)' services/social_ts db/init.sql >/dev/null || fail "legacy notification kind default remains"
pass "notification kinds are explicit"

"$PYTHON_RUNTIME" - <<'PYMETRICS' || fail "viewer-state still owns a duplicate aggregate implementation"
from pathlib import Path
s = Path("services/social_ts/src/routes.ts").read_text()
block = s[s.index("async function viewerStateForSeries"):s.index("type SmartLibraryScope", s.index("async function viewerStateForSeries"))]
assert "metricsForSeriesBatch(prisma, [seriesId], userId)" in block
assert "SELECT COUNT(*)::bigint FROM bookmarks" not in block
assert "SELECT COUNT(*)::bigint FROM subscriptions" not in block
assert "SELECT AVG(sr.rating)::float8" not in block
PYMETRICS
pass "social public metrics have one aggregate owner"

! rg -n 'docker-compose\.(dev|core|prod|nas|tailscale|cloudflare|gcore|ngrok)' scripts/hybrid scripts/preflight.sh scripts/runtime-health.sh scripts/rabbitmq-*.sh scripts/migrate.sh >/dev/null || fail "active operational scripts still reference superseded compose runtime"
! rg -n 'deploy/helm/mreader' scripts/android-static-audit.sh scripts/android-web-reader-contract-audit.sh scripts/validate-current-release.sh tests/regression/release-version-consistency.sh >/dev/null || fail "active release audits still require retired Helm deployment"
pass "release tooling targets hybrid deployment"

[[ ! -d deploy/helm && ! -d deploy/platform && ! -d deploy/gateway ]] || fail "superseded Helm/platform/generic-gateway deployment trees remain executable"
for stale in docker-compose.yml docker-compose.core.yml docker-compose.dev.yml docker-compose.nas.yml docker-compose.tailscale.yml docker-compose.nas-tailscale.yml docker-compose.cloudflare.yml docker-compose.gcore.yml docker-compose.ngrok.yml docker-compose.prod.yml docker-compose.prod-cloudflare.yml docker-compose.prod-gcore.yml docker-compose.prod-hybrid.yml docker-compose.security.yml docker-compose.monitoring.yml; do
  [[ ! -e "deploy/compose/$stale" ]] || fail "superseded compose launcher remains: $stale"
done
! rg -n 'docker-compose\.(dev|core|prod|nas|tailscale|cloudflare|gcore|ngrok)|deploy/helm|deploy/platform|deploy/gateway/Caddyfile' scripts tests/api tests/browser tests/load Jenkinsfile >/dev/null || fail "active script/test/CI still references a superseded deployment path"
pass "only the hybrid deployment model remains executable"

[[ -x scripts/hybrid/adopt-existing-stateful-volumes.sh ]] || fail "stateful volume adoption helper is missing"
rg -n 'HYBRID_PGDATA_VOLUME_NAME' deploy/compose/docker-compose.hybrid-stateful.yml >/dev/null || fail "hybrid PostgreSQL volume is not explicitly selectable"
rg -n 'mreader-hybrid-stateful_pgdata' scripts/hybrid/adopt-existing-stateful-volumes.sh >/dev/null || fail "legacy PostgreSQL volume cannot be adopted during upgrade"
pass "hybrid stateful ownership supports one-time explicit adoption"

for retired in scripts/start-mode.sh scripts/stop-mode.sh scripts/status-mode.sh scripts/logs-mode.sh scripts/up.sh scripts/down.sh scripts/status.sh scripts/hybrid/retire-single-plane.sh; do
  [[ ! -e "$retired" ]] || fail "retired compatibility launcher remains: $retired"
done
[[ ! -d scripts/tailscale ]] || fail "retired standalone Tailscale launcher remains beside hybrid public-edge owner"
! rg -n 'retire-single-plane|scripts/(start-mode|stop-mode|status-mode|logs-mode)\.sh|scripts/tailscale/' Makefile scripts docs services/scraper_service/LOCAL_STAGING_SPOOL.md >/dev/null || fail "active docs/scripts still reference a retired launcher"
pass "hybrid operator surface has no legacy launcher aliases"


# Hybrid validator must not invoke deleted regression scripts.
while IFS= read -r test_path; do
  [[ -x "$test_path" ]] || fail "hybrid validator references missing/non-executable regression: $test_path"
done < <(grep -oE '\./tests/regression/[A-Za-z0-9._-]+\.sh' scripts/hybrid/validate.sh | sort -u)
pass "hybrid validator regression references resolve"

# Kotlin source must not contain malformed doubled braces before catch clauses.
! rg -n '}[[:space:]]*}[[:space:]]*catch[[:space:]]*\(' android/app/src/main/java >/dev/null || fail "Android Kotlin source contains malformed doubled brace before catch"
pass "Android Kotlin catch structure has no known merge-remnant pattern"

rg -n 'reader-go\.mreader-user\.svc\.cluster\.local:8080' deploy/docker-desktop-hybrid/Caddyfile.admin >/dev/null || fail "admin gateway does not use cross-namespace reader service"
pass "admin mobile reader route is cross-namespace correct"

! rg -n 'v1\.3\.0-rc4\.82|1\.3\.0-rc4\.82' VERSION frontend/package.json services/social_ts/package.json deploy/docker-desktop-hybrid deploy/compose/docker-compose.hybrid-*.yml scripts/hybrid android/app/build.gradle.kts >/dev/null || fail "active release files still contain RC4.82"
rg -n 'versionCode = 484' android/app/build.gradle.kts >/dev/null || fail "Android versionCode is not 484"
pass "active release identity is RC4.84"

echo 'RC4.84 consolidation static gate PASSED'
