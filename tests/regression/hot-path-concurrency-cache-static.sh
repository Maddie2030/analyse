#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# Media chapter conversion must not advance CPU-heavy synchronous generators on
# the asyncio event loop. Keep prefetch bounded to one encoded page.
grep -q 'async def _drain_sync_pages' services/image_service/app/services/chapter_ingestion.py || fail 'async page drain missing'
grep -q 'asyncio.to_thread(next, iterator, _PAGE_ITER_END)' services/image_service/app/services/chapter_ingestion.py || fail 'page generator is not advanced off-loop'
grep -q 'asyncio.Queue(maxsize=1)' services/image_service/app/services/chapter_ingestion.py || fail 'page prefetch is not memory-bounded'
! grep -q 'for page in page_iter:' services/image_service/app/services/chapter_ingestion.py || fail 'chapter generator still runs directly on event loop'
[[ "$(grep -c 'await asyncio.to_thread(' services/image_service/app/services/chapter_ingestion.py)" -ge 3 ]] || fail 'boundary image conversion is not off-loop'

# Thumbnail libvips work must leave the ASGI event loop free.
grep -q 'from starlette.concurrency import run_in_threadpool' services/thumbnail_transformer/app/main.py || fail 'thumbnail threadpool helper missing'
grep -q 'await run_in_threadpool(_transform, data, width)' services/thumbnail_transformer/app/main.py || fail 'thumbnail transform still blocks event loop'

# Reader navigation index already exists in the fresh baseline. The upgrade
# migration must reuse the same name/definition so it repairs legacy DBs without
# creating a duplicate equivalent index.
grep -Eq 'idx_chapters_series_number .*chapters\(series_id, chapter_number DESC\).*status = .published.' db/init.sql || fail 'published series/chapter-number index missing from baseline'
[[ -f db/migrations/040_reader_chapter_navigation_index.sql ]] || fail 'Reader navigation upgrade guard missing'
grep -q 'CREATE INDEX IF NOT EXISTS idx_chapters_series_number' db/migrations/040_reader_chapter_navigation_index.sql || fail 'upgrade guard does not reuse canonical index name'
! grep -R -q 'idx_chapters_series_number_published' db/migrations || fail 'duplicate Reader navigation index name introduced'

# Pages + prev + next are independent after the manifest and should fan out.
grep -q 'wg.Add(3)' services/reader_go/internal/store/store.go || fail 'Reader post-manifest reads are still sequential'
grep -q 'pages, pagesErr = s.fetchPages' services/reader_go/internal/store/store.go || fail 'Reader page fetch helper/fanout missing'
grep -q 'prev, prevErr = s.chapterLink' services/reader_go/internal/store/store.go || fail 'Reader previous lookup fanout missing'
grep -q 'next, nextErr = s.chapterLink' services/reader_go/internal/store/store.go || fail 'Reader next lookup fanout missing'

# Catalog local invalidation is scope-aware, including in-flight generation
# protection and cross-replica Pub/Sub delivery.
grep -q 'scopeGen.*map\[string\]uint64' services/catalog_go/internal/cache/cache.go || fail 'per-scope cache generations missing'
grep -q 'func (s \*Service) invalidateLocalScope' services/catalog_go/internal/cache/cache.go || fail 'scope-local invalidation missing'
grep -q 's.invalidateLocalScope(message.Payload)' services/catalog_go/internal/cache/cache.go || fail 'Pub/Sub still clears every local scope'
! grep -A4 'func (s \*Service) InvalidateScope' services/catalog_go/internal/cache/cache.go | grep -q 'ClearLocal()' || fail 'InvalidateScope still globally clears local cache'
grep -q 'a.loadCacheableJSON(r, "genres", "all"' services/catalog_go/internal/httpapi/api.go || fail 'genres cache is not explicitly scoped'
grep -q 'a.loadCacheableJSON(r, "series", "discovery"' services/catalog_go/internal/httpapi/api.go || fail 'series/discovery cache is not explicitly scoped'
grep -q 'a.loadCacheableJSON(r, "curation", "public"' services/catalog_go/internal/httpapi/api.go || fail 'curation cache is not explicitly scoped'
[[ "$(grep -c 'a.invalidateCurationCaches(r)' services/catalog_go/internal/httpapi/api.go)" -ge 8 ]] || fail 'curation cache invalidation coverage is incomplete'

printf '%s\n' 'hot-path concurrency/cache static regression PASSED'
