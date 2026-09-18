#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
fail(){ echo "RC4.84 UPGRADE/RECOVERY REGRESSION FAILED: $*" >&2; exit 1; }

[[ -x scripts/hybrid/adopt-existing-stateful-volumes.sh ]] || fail 'missing one-time stateful-volume adoption tool'
[[ -x scripts/recovery/catalog-restore.sh ]] || fail 'missing catalog recovery entrypoint'
[[ -f scripts/recovery/catalog-import.sql ]] || fail 'missing transactional catalog import SQL'
[[ -f docs/recovery/CATALOG_RECOVERY.md ]] || fail 'missing catalog recovery operator guide'

grep -q 'HYBRID_PGDATA_VOLUME_NAME' deploy/compose/docker-compose.hybrid-stateful.yml || fail 'PostgreSQL volume name is not selectable through explicit adoption state'
grep -q 'adopt-existing-stateful-volumes.sh' scripts/bootstrap.sh || fail 'bootstrap does not perform safe one-time volume adoption'

grep -q -- '--check' scripts/recovery/catalog-restore.sh || fail 'catalog restore lacks read-only check mode'
grep -q -- '--import' scripts/recovery/catalog-restore.sh || fail 'catalog restore lacks explicit import mode'
grep -q 'series_genres' scripts/recovery/catalog-import.sql || fail 'catalog restore does not include taxonomy relationships'
grep -q 'encoding_seed' scripts/recovery/catalog-import.sql || fail 'catalog restore does not preserve v4 decode seed'
! grep -Eq '\b(users|bookmarks|subscriptions|comments|notifications|reading_progress|chapter_reads)\b' scripts/recovery/catalog-import.sql || fail 'catalog recovery SQL imports non-catalog/user state'

grep -q 'NAS.*read-only\|read-only.*NAS' docs/recovery/CATALOG_RECOVERY.md || fail 'recovery guide does not state NAS read-only requirement'
grep -q "LOCAL_STORE=.*mreader-local-recovery-store" scripts/backup/backup-agent.sh || fail 'backup agent does not publish through canonical host-local recovery catalog'
grep -q 'schema_version:1' scripts/backup/backup-agent.sh || fail 'future local recovery manifests do not record schema version'
grep -q 'checksums_file' scripts/backup/backup-agent.sh || fail 'future local recovery manifests do not declare checksum inventory'

# Canonical API aliases proven dead in RC4.81 must not remain.
! grep -q 'r.Get("/dashboard"' services/catalog_go/internal/httpapi/api.go || fail 'Catalog /dashboard alias remains'
! grep -q 'Methods(http.MethodGet, http.MethodPut)' services/progress_go/internal/httpapi/api.go || fail 'Progress PUT compatibility route remains'
! grep -q '@app.get("/api/scraper/series-drafts/{draft_id}/publish-status")' services/scraper_service/app/main.py || fail 'Scraper publish-status alias remains'
! grep -q 'HandleFunc("GET /ws"' services/realtime_go/cmd/realtime/main.go || fail 'Realtime /ws alias remains'

echo 'RC4.84 upgrade/recovery/static contract passed'
