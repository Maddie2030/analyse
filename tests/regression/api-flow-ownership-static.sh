#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# 1) Publication has one notification owner. The Catalog command path emits
# chapter.published for converted callers. Media must no longer emit it after
# manual chapter cutover; legacy Scraper continues only until its P06.4 slice.
# Only notification_worker writes notifications.
! grep -R -n --exclude-dir='__pycache__' --exclude='*.pyc' 'notify_series_followers' services shared >/dev/null || fail 'legacy direct follower notification helper remains'
grep -q 'enqueueChapterPublishedTx' services/catalog_go/internal/store/publication.go || fail 'Catalog command path does not emit chapter.published'
! grep -q 'enqueue_chapter_published' services/image_service/app/services/chapter_ingestion.py || fail 'Media still emits chapter.published after Catalog cutover'
! grep -R -n --exclude-dir='__pycache__' --exclude='*.pyc' 'enqueue_chapter_published' services/scraper_service/app >/dev/null || fail 'Scraper still emits chapter.published after new-series cutover'
writers="$(grep -R -l --exclude-dir='__pycache__' --exclude='*.pyc' -E 'INSERT INTO notifications|prisma\.notification\.create' services shared || true)"
[[ "$writers" == "services/notification_worker/internal/store/store.go" ]] || fail "unexpected direct notification writers: $writers"

# 2) Reader GET is read-only for canonical reading state; Progress owns history/read markers.
! grep -R -n 'reading_history\|chapter_reads' services/reader_go >/dev/null || fail 'Reader still owns reading state'
grep -q 'r.Get("/api/progress/history"' services/progress_go/internal/httpapi/api.go || fail 'Progress history route missing'
grep -q '"/api/progress/series/{seriesSlug}/state"' services/progress_go/internal/httpapi/api.go || fail 'Progress series-state route missing'
grep -q 'INSERT INTO chapter_reads' services/progress_go/internal/store/store.go || fail 'exact chapter read persistence missing'
grep -q 'update.UserID + "\\x00" + update.SeriesID + "\\x00" + update.ChapterID' services/progress_go/internal/progress/service.go || fail 'Progress coalescing may drop cross-chapter read markers'
grep -q '/api/progress/history' frontend/src/api/client.ts || fail 'frontend history still points at Reader'
! grep -R -n --exclude-dir=node_modules '/api/reader/history' frontend services tests/api >/dev/null || fail 'stale Reader history route remains'

# 3) All chapter upload variants use the durable Media job.
grep -q 'form.get("first_image")' services/image_service/app/routers/jobs.py || fail 'queued Media job lacks first boundary image'
grep -q 'form.get("last_image")' services/image_service/app/routers/jobs.py || fail 'queued Media job lacks last boundary image'
grep -q 'staged_object_paths=' services/image_service/app/routers/jobs.py || fail 'all staged Media inputs are not represented durably'
! grep -q '/upload/{series_slug}/{chapter_slug}' services/image_service/app/routers/upload.py || fail 'legacy upload compatibility route still exists'
! grep -A40 'upload_chapter_compatibility_adapter' services/image_service/app/routers/upload.py | grep -q 'convert_image_to_webp\|Chapter(' || fail 'compatibility adapter still performs ingestion'

# 4) P06.4 chapter publication ownership: all Scraper chapter paths use
# private staging -> Media evidence -> Catalog. Legacy Scraper publisher/transform
# modules are removed once new-series joins the same command path.
for retired in publication.py draft_image_processor.py tilepack_codec.py events.py; do
  [[ ! -f "services/scraper_service/app/$retired" ]] || fail "legacy Scraper publication module remains: $retired"
done
! grep -q 'publish_chapter_record' services/scraper_service/app/drafts.py || fail 'existing-series draft still writes through legacy Scraper publication core'
grep -q 'submit_to_media' services/scraper_service/app/drafts.py || fail 'existing-series draft does not delegate final transform to Media'
grep -q 'ensure_ingestion_operation' services/scraper_service/app/drafts.py || fail 'existing-series draft does not establish Scraper ingestion authority'
! grep -q 'publish_chapter_record' services/scraper_service/app/batch_queue.py || fail 'batch upload still writes through legacy Scraper publication core'
grep -q 'submit_to_media' services/scraper_service/app/batch_queue.py || fail 'batch upload does not delegate final transform to Media'
grep -q 'ensure_ingestion_operation' services/scraper_service/app/batch_queue.py || fail 'batch upload does not establish Scraper ingestion authority'
! grep -q 'publish_chapter_record\|process_page\|build_page_path' services/scraper_service/app/series_drafts.py || fail 'new-series still owns final chapter transform/catalog write'
grep -q 'submit_to_media' services/scraper_service/app/series_drafts.py || fail 'new-series does not delegate final transform to Media'
grep -q 'ensure_ingestion_operation' services/scraper_service/app/series_drafts.py || fail 'new-series does not establish ingestion authority'

# 5) Series Detail uses aggregate viewer-state + targeted Progress state.
grep -q 'seriesViewerState' frontend/src/pages/SeriesDetail.tsx || fail 'Series Detail still fans out social relationship calls'
grep -q 'getSeriesReadingState' frontend/src/pages/SeriesDetail.tsx || fail 'Series Detail still over-fetches global history'
! grep -q 'api\.bookmarkStatus\|api\.subscriptionStatus\|api\.getHistory' frontend/src/pages/SeriesDetail.tsx || fail 'Series Detail retains old fan-out'
grep -q '/api/social/series/:seriesId/viewer-state' services/social_ts/src/routes.ts || fail 'viewer-state backend missing'

# 6) Smart Library remains transactional and one-query; no permanent projection table added.
grep -q 'SMART_LIBRARY_BASE_SQL' services/social_ts/src/routes.ts || fail 'Smart Library canonical query missing'
grep -q 'summary AS MATERIALIZED' services/social_ts/src/routes.ts || fail 'Smart Library summary/page query is not consolidated'
! grep -R -n --exclude-dir=node_modules 'CREATE TABLE.*user_series_state\|user_series_state' db services >/dev/null || fail 'unexpected permanent Smart Library projection introduced'

# 7) Realtime comments use WS deltas, not a second Redis/SSE pipeline.
! grep -R -n --exclude-dir=node_modules '/api/social/comments/stream\|commentStreamUrl' frontend services >/dev/null || fail 'legacy comment SSE pipeline remains'
grep -q "event.type === 'created'" frontend/src/components/CommentSection.tsx || fail 'comment create delta not applied locally'
grep -q "event.type === 'deleted'" frontend/src/components/CommentSection.tsx || fail 'comment delete delta not applied locally'
grep -q '30_000' frontend/src/components/CommentSection.tsx || fail 'HTTP recovery reconciliation missing'
grep -q '5_000' frontend/src/components/CommentSection.tsx || fail 'stuck CONNECTING recovery guard missing'

# 8) Session Contract v1 is explicit and inactive admins cannot bypass it.
[[ -f contracts/session/v1/session.schema.json ]] || fail 'Session v1 schema missing'
grep -q '"version"' contracts/session/v1/session.schema.json || fail 'Session v1 version field missing'
grep -q 'SESSION_CONTRACT_VERSION = 1' shared/shared/session_contract.py || fail 'Python session contract version missing'
grep -q 's.Version != 1' services/catalog_go/internal/session/session.go || fail 'Catalog session v1 guard missing'
grep -q 'version !== 1' services/social_ts/src/session.ts || fail 'Social session v1 guard missing'
grep -A8 'async def require_admin' shared/shared/auth.py | grep -q 'is_active' || fail 'inactive Python admin sessions are still accepted'

# 9) Catalog cache is normalized, miss-coalesced, generation-safe and hybrid cache traffic uses cache Valkey.
grep -q 'normalizedCacheKey' services/catalog_go/internal/httpapi/api.go || fail 'normalized Catalog cache keys missing'
grep -q 'flights.*map\[string\]\*flight' services/catalog_go/internal/cache/cache.go || fail 'Catalog singleflight missing'
grep -q 'setLocalIfGeneration' services/catalog_go/internal/cache/cache.go || fail 'Catalog invalidation race guard missing'
grep -q 'RunInvalidationLoop' services/catalog_go/internal/cache/cache.go || fail 'Catalog cross-replica invalidation missing'
grep -q 'CacheRedisAddr' services/catalog_go/internal/config/config.go || fail 'Catalog cache Redis config missing'
grep -q 'CATALOG_GO_CACHE_REDIS_ADDR' deploy/docker-desktop-hybrid/user-apps.yaml || fail 'user Catalog cache Valkey wiring missing'
grep -q 'CATALOG_GO_CACHE_REDIS_ADDR' deploy/docker-desktop-hybrid/admin-apps.yaml || fail 'admin Catalog cache Valkey wiring missing'
grep -q 'name: redis-cache' deploy/docker-desktop-hybrid/external-stateful-admin.yaml || fail 'admin cache Valkey service missing'

# 10) Chapter search is server-side and badges come from exact Progress read state.
grep -q "params.set('chapter_search', chapterSearchQuery)" frontend/src/pages/SeriesDetail.tsx || fail 'Series Detail does not use server chapter search'
grep -q 'chapter_number::text ILIKE' services/catalog_go/internal/store/store.go || fail 'Catalog chapter search missing'
grep -q 'read_chapter_ids' frontend/src/api/client.ts || fail 'exact chapter read IDs absent from API contract'
grep -q 'readingState?.read_chapter_ids' frontend/src/pages/SeriesDetail.tsx || fail 'Read badges still use resume history'

# Migration and fresh schema must agree about the exact chapter read table.
[[ -f db/migrations/039_progress_owns_reading_state.sql ]] || fail 'RC4.40 reading-state migration missing'
grep -q 'CREATE TABLE IF NOT EXISTS chapter_reads' db/migrations/039_progress_owns_reading_state.sql || fail 'chapter_reads migration missing'
grep -q 'CREATE TABLE IF NOT EXISTS chapter_reads' db/init.sql || fail 'fresh schema lacks chapter_reads'


# 11) Clients must not restore the independent History safety-floor merge.
# Transaction/ledger semantics are exercised by test_26_reading_commands.py;
# the former source check incorrectly required opens to be outside a transaction.
! grep -q "api.getHistory('?offset=0&limit=100')" frontend/src/pages/Library.tsx || fail 'web Library still duplicates Smart Library with Progress history fallback'
! grep -q 'repository.history(limit = 100' android/app/src/main/java/com/mreader/android/ui/screens/LibraryScreen.kt || fail 'Android Library still duplicates Smart Library with Progress history fallback'

# 12) Public aggregate metrics remain visible without auth/session coupling.
metrics_block="$(sed -n '/app.post("\/api\/social\/series\/metrics-batch"/,/^  });/p' services/social_ts/src/routes.ts)"
! grep -q 'sessionFromRequest' <<<"$metrics_block" || fail 'public metrics batch still depends on session Redis'
single_metrics_block="$(sed -n '/app.get("\/api\/social\/series\/:seriesId\/metrics"/,/^  });/p' services/social_ts/src/routes.ts)"
! grep -q 'sessionFromRequest' <<<"$single_metrics_block" || fail 'public series metrics still depend on session Redis'
grep -q 'subscription_count' frontend/src/components/SeriesPosterCard.tsx || fail 'web poster cards do not expose public subscriber count'
grep -q 'subscriptionCount.toString()' android/app/src/main/java/com/mreader/android/ui/components/Common.kt || fail 'Android poster cards do not expose public subscriber count'
grep -q 'repository.socialMetricsBatch(metricSeriesIds)' android/app/src/main/java/com/mreader/android/ui/screens/CatalogScreen.kt || fail 'Android Browse does not load public metrics for visible series'
grep -q 'test_public_series_aggregates_visible_to_anonymous_guests' tests/api/test_09_bookmarks.py || fail 'anonymous aggregate metrics regression test missing'

printf '%s\n' 'API ownership/integration static regression PASSED'
