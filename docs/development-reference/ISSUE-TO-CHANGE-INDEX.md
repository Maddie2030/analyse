# MReader issue → change-impact index

Use this table to choose the first files and tests. Then run Graphify `explain`/`affected`; do not treat the table as an exhaustive edit list.

| Symptom / capability | Start here | Follow dependency path into | Focused verification |
|---|---|---|---|
| Reader page blank / decode failure | `frontend/src/pages/Reader.tsx`, `frontend/src/reader/ProtectedPage.tsx`, `codec.ts`, `codec.worker.ts` | `protectedAssetCache.ts` → Reader Go → Image Edge/SeaweedFS | `tests/regression/browser-reading-acceptance-static.sh`, `tests/regression/test_p10_1_reader_ui.py`, `tests/api/test_06_reader_manifest_history.py`, `test_07_reader_images_tokens.py`, `test_27_mobile_reader_adapter.py` |
| Protected page re-downloads / cache miss | `frontend/src/reader/protectedAssetCache.ts` | CacheStorage / `mreader-protected-assets-v1`, runtime config, auth cache clearing | Browser reading acceptance + reader UI + quota/offline/two-tab cases |
| IndexedDB reading state missing / duplicate sync | `frontend/src/reading/indexedDB.ts`, `browser.ts`, `repository.ts`, `transport.ts` | `useReading.ts` → Reader/Library UI → Progress Go | `tests/regression/test_web_reading_repository.mjs`, `test_rc485_p02_reading_source.py`, browser reading specs, `tests/api/test_26_reading_commands.py` |
| Recent read/history/library wrong | `frontend/src/pages/Library.tsx`, `frontend/src/reading/*` | Progress Go + Smart Library/Social projections + Android reading repository | `tests/api/test_17_smart_library.py`, `test_26_reading_commands.py`, `test_p10_1_library_ui.py`, P02 reading source tests |
| Android reader parity issue | `ReaderScreen.kt`, `MReaderApiAdapter.kt`, `ReadingRepository.kt`, `ProtectedAssetStore.kt` | Reader/Progress APIs, native codec/cache | Android repository/codec tests + API mobile reader tests + `test_rc485_p04_android_source.py` |
| Login/session/logout/cookie issue | `frontend/src/hooks/useAuth.tsx`, `frontend/src/api/client.ts` | Auth service/session contract → critical Valkey → gateway | auth API tests, session/ownership static checks, private-transport tests |
| Catalog browse/search/series issue | `Catalog.tsx`, `AdvancedSearch.tsx`, `SeriesDetail.tsx` | Catalog Go HTTP API/store/cache → PostgreSQL | `tests/api/test_04_catalog_reads.py`, browse/search UI tests, series UI tests |
| Admin catalog mutation/curation issue | `AdminDashboard.tsx`, `AdminCuration.tsx` | admin gateway → Catalog write-enabled API/store | `test_05_catalog_admin_writes.py`, P10 admin curation/content UI, ownership route tests |
| Scraper discovery/source issue | `AdminScraper.tsx`, adapters under `services/scraper_service/app/adapters/` | scraper fetcher/browser/discovery/queue | scraper API tests + hardening/source compatibility tests |
| Stage / retry / manual upload issue | `AdminScraperNewSeries.tsx` | `staging_store.py`, `drafts.py`, `series_drafts.py`, revision/generation fences | P07 staging/retry/status regression tests, `test_18_scraper_operations.py`, deep route coverage |
| Publish stuck / only partial pages published | `services/scraper_service/app/publication_bridge.py`, `series_drafts.py` | Scraper → Media/Image → Catalog publication → SeaweedFS/PostgreSQL | `test_scraper_media_publication_cutover.py`, `test_media_catalog_publication_cutover.py`, Catalog publication contract/source tests |
| Media transform / WebP / chapter asset issue | `services/image_service/app/media_operations.py`, `services/image_service/app/services/chapter_ingestion.py` | SeaweedFS + catalog publication receipt + lifecycle worker | `tests/api/test_13_media.py`, `test_19_media_events.py`, `webp-publish-verification-static.sh`, media cutover tests |
| Catalog publication ownership/data corruption risk | `services/catalog_go/internal/store/publication.go`, `internal/httpapi/api.go` | publication contract → PostgreSQL transaction → event_outbox | publication Go tests, `test_catalog_publication_contract.py`, `test_catalog_publication_http_source.py`, P06.4/P06.6 ownership tests |
| Delete/replace storage cleanup issue | Media lifecycle routes/worker + Catalog mutation path | generation/reference capture → lifecycle cleanup → SeaweedFS | lifecycle API/integrity tests, P07 deletion/generation regressions |
| Notifications missing/duplicate | `services/notification_worker/` | Catalog/Progress outbox → Outbox Relay → RabbitMQ → notifications rows | `tests/api/test_12_notifications.py`, notification worker Go tests, browser realtime spec |
| Realtime notification/comment issue | `services/realtime_go/internal/sources/*`, `hub/*` | RabbitMQ notification batches / Valkey comment signals → canonical reread | realtime hub tests + `tests/browser/notification-realtime.spec.mjs` |
| Social/bookmark/subscription/comment issue | `services/social_ts/src/routes.ts` | Prisma/PostgreSQL + Valkey comment signals | relevant API tests + UI comment/library tests + ownership route gate |
| Database backup/snapshot/download issue | `frontend/src/pages/AdminDatabase.tsx`, `services/scraper_service/app/database_facade.py` | backup-agent + host recovery root + PostgreSQL tools | P08.3/P08.5/P08.7 regression tests, backup-agent/static/local backup suites |
| Restore/drill safety issue | restore scripts under `scripts/backup/` and `scripts/recovery/` | recovery catalog, fencing, safety capture, PostgreSQL | P08.6/P08.7 restore qualification + local recovery catalog tests |
| Hybrid startup/bootstrap issue | `hybrid-up.sh`, `hybrid-down.sh`, `scripts/hybrid/`, deployment manifests | Compose stateful backbone + Docker Desktop K8s + migrations/gateways | hybrid/Windows/MSYS/volume/secret regressions + diagnostics |
| KEDA/HPA/worker scaling issue | `deploy/docker-desktop-hybrid/admin-keda.yaml` and app manifests | RabbitMQ/queue metrics → worker deployments | scaling/static deployment tests and runtime pod/KEDA checks |
| PostgreSQL volume/adoption/data preservation issue | Compose stateful files + hybrid volume scripts | migration/quiescence/backup ordering | hybrid legacy-volume, volume inspection, pre-upgrade backup, migration quiescence tests |
| NAS/SeaweedFS connectivity issue | `shared/shared/seaweedfs.py`, Media config, `ops/nas-seaweedfs/` | NAS endpoint → Image Edge → Reader/Media | storage env contract, media API tests, diagnostics runtime snapshot |
| Gateway route/CORS/public edge issue | user/admin Caddy/gateway manifests + runtime config | ownership manifest → service route → auth/session | `api-flow-ownership-static.sh`, twin-plane static, API route audit, health gateway tests |
| Diagnostics report incomplete/wrong | `diagnose-mreader.sh`, `scripts/diagnostics/report_builder.py`, `analyze_report.py` | runtime snapshot + API runner + bundle builder | `tests/diagnostics/*`, `diagnostics-harness-static.sh`, comprehensive harness static |
| User/admin actor journey action fails | `tests/api/test_28_user_actor_journeys.py`, `test_29_admin_actor_journeys.py`, `test_30_external_actor_journeys.py` | failing action → owning API/service → persisted/public state asserted by the journey | `./diagnose-mreader.sh` full mode, actor action report, focused owner regression/API test |

## Mandatory cross-checks by change type

### Route or API change

Always inspect/run:

- `contracts/ownership/routes.v1.json`
- route ownership audit
- API flow ownership static check
- consumer denial/access-plane tests
- gateway mapping if the route crosses a plane

### PostgreSQL schema/write change

Always inspect/run:

- migrations and role grants
- PostgreSQL role/grant gates
- ownership contract permitted writes
- backup/restore compatibility if schema semantics change

### Publication/media change

Always inspect/run:

- `contracts/catalog/v1/*`
- Scraper→Media cutover tests
- Media→Catalog cutover tests
- Catalog publication contract/HTTP source tests
- event finalization tests
- lifecycle generation/reference tests when assets are replaced/deleted

### Reading state change

Always inspect/run:

- `contracts/reading/*`
- Web reading repository behavioral tests
- Progress source/API tests
- Smart Library/history UI tests
- Android reading journal parity tests if the contract changes

### Deployment/config change

Always inspect/run:

- twin-plane/static deployment checks
- secrets/env-scope tests
- Windows/MSYS path regressions where host paths are involved
- pre-upgrade backup ordering if stateful startup changes
- diagnostics snapshot after live deployment
