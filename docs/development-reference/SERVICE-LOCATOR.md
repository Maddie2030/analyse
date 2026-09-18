# MReader service and ownership locator

| Domain | Client entry | Backend owner | Durable/important state | Primary contract / map | First verification |
|---|---|---|---|---|---|
| Authentication/session | `frontend/src/hooks/useAuth.tsx`, `frontend/src/api/client.ts`; Android network adapter | `services/auth_service/` | PostgreSQL + critical Valkey session state | `contracts/session/v1/`, ownership routes | auth/session API tests + private transport/access gates |
| Catalog browse/search | `Catalog.tsx`, `AdvancedSearch.tsx`, `SeriesDetail.tsx` | `services/catalog_go/` | PostgreSQL + cache | ownership routes | `test_04_catalog_reads.py` + browse/search UI |
| Reader manifest/grants | `Reader.tsx`, Android reader | `services/reader_go/` | PostgreSQL metadata + grant/cache Valkey | ownership routes | reader manifest/token API + browser/Android reader tests |
| Web reading intent/history | `frontend/src/reading/*`, `Library.tsx` | `services/progress_go/` | Web IndexedDB journal locally; PostgreSQL canonical | `contracts/reading/v1/` | Web repository tests + reading commands/progress API |
| Protected page cache | `frontend/src/reader/protectedAssetCache.ts` | client cache; Reader/Image path upstream | CacheStorage, IndexedDB fallback, encoded bytes only | reader/cache rules in code/static tests | browser reading acceptance + quota/offline scenarios |
| Android reading/cache | Android `ReadingRepository`, `ReadingJournal`, `ProtectedAssetStore` | Progress/Reader APIs | Android native storage; PostgreSQL canonical | reading contract | Android source/repository + mobile API tests |
| Social/bookmarks/subscriptions/comments | UI social/library/series components | `services/social_ts/` | PostgreSQL; Valkey signals for realtime comments | ownership/events | API 09–11 + relevant UI tests |
| Scraper/discovery/staging | Admin scraper UI | `services/scraper_service/` | PostgreSQL draft/operation state + staging PVC | ownership routes | scraper operation/new/existing-series API + P07 tests |
| Media transform | Admin ingestion path | `services/image_service/` | staging input -> protected-v4 assets in SeaweedFS | `contracts/catalog/v1/` media receipt | media API/events + publication evidence/cutover |
| Production publication | indirect via Scraper/Media | `services/catalog_go/` only | production catalog/chapter/page rows + outbox | `contracts/catalog/v1/` | publication contract/HTTP/source + ownership gates |
| Lifecycle delete/replace | admin mutation path | lifecycle/media worker with Catalog references | captured generation/reference -> SeaweedFS cleanup | catalog/lifecycle rules | lifecycle integrity + P07.4 cleanup tests |
| Notifications | notification UI | `services/notification_worker/` | PostgreSQL notifications | event contracts | notification API + worker tests |
| Realtime | WebSocket client | `services/realtime_go/` | canonical reread from backend state; RabbitMQ/Valkey as transport/signals | event contracts | realtime Go tests + browser realtime spec |
| Outbox/events | no direct UI | producers + `services/outbox_relay/` | PostgreSQL `event_outbox`; RabbitMQ transport | `contracts/events/` | event producer/finalization + relay/consumer tests |
| Database protection | `AdminDatabase.tsx` | database protection facade/backup agent/scripts | host recovery root + PostgreSQL dumps/snapshots/catalog | P08 contracts/docs/tests | local backup + inventory/download/restore/drill/fencing tests |
| Hybrid runtime | launch/ops scripts | Compose + Docker Desktop Kubernetes | Compose volumes + K8s stateless workloads + NAS | deploy/manifests/scripts | hybrid regressions + diagnostics |
| Diagnostics / actor acceptance | `diagnose-mreader.sh` | diagnostics scripts/container + API/browser actor journeys | evidence bundle + disposable journey state | diagnostics tests/static gates + actor action ledger | diagnostics unit/static + live user/admin journey run |
