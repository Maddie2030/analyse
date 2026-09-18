# MReader RC4.85 architecture/code map

This is the maintained architecture guide. The package-generated Graphify reference supplies checkpoint-specific file/symbol topology for the exact source being tested.

## 1. System at a glance

```text
                         PUBLIC / USER PLANE
 Browser Web -------------------+---------------- Native Android
       |                         |                       |
       | HTTP + WS               | HTTP                  |
       v                         v                       v
  user-gateway :8080 ---------------------------------------
       |             |             |            |          |
       v             v             v            v          v
   auth-service  catalog-go    reader-go    progress-go  social-ts
                    |              |             |           |
                    |              |             |           +--> Valkey pub/sub (comment signals)
                    |              |             |           +--> PostgreSQL social + notifications
                    |              |             |
                    |              |             +--> PostgreSQL reading_progress/chapter_reads
                    |              |                  + transactional event_outbox
                    |              |
                    |              +--> PostgreSQL catalog/page metadata
                    |              +--> cache Valkey chapter grants
                    |              +--> Image Edge -> NAS SeaweedFS
                    |
                    +--> PostgreSQL catalog + curation

                  realtime-go <---- RabbitMQ notification.batch.created
                       ^             + Valkey social:comments:* pub/sub
                       |
                    WebSocket

                         ADMIN / INGESTION PLANE
  admin-frontend --> admin-gateway :8081
       |                   |
       |                   +--> auth-admin
       |                   +--> catalog-admin (writes enabled)
       |                   +--> scraper-service
       |                   +--> image-service
       |
       +--> scraper workers / browser worker
                  |
                  v
          scraper staging PVC
                  |
                  v
          ingestion_operations
                  |
                  v
            media-worker --------> NAS SeaweedFS
                  |
                  +--> internal Catalog publication command
                  v
            catalog-admin --------> immutable catalog/page commit

 PostgreSQL event_outbox --> outbox-relay --> RabbitMQ --> notification-worker
                                                   |             |
                                                   |             +--> PostgreSQL notifications
                                                   |             +--> event_outbox notification.batch.created
                                                   v
                                              realtime-go

 Docker Compose backbone: PostgreSQL + critical Valkey + cache Valkey + RabbitMQ
                          + Image Edge nginx + backup-agent
 External: NAS SeaweedFS
 Kubernetes: stateless services/workers in mreader-user and mreader-admin
```

## 2. Repository shape

| Area | Main paths | Purpose |
|---|---|---|
| Web | `frontend/src/` | React/Vite public + admin UI, browser reader, reading journal |
| Android | `android/app/src/main/java/com/mreader/android/` | Native Compose client, native protected reader + WebReader fallback |
| API contracts | `contracts/` | Catalog publication, event envelopes, ownership, reading, session contracts |
| Database | `db/migrations/` | PostgreSQL schema/history through current RC4.85 work |
| Services | `services/` | Auth, Catalog, Reader, Progress, Social, Realtime, Media/Image, Scraper, workers |
| User/admin deployment | `deploy/docker-desktop-hybrid/` | Twin-plane Kubernetes manifests, HPA/KEDA, Caddy gateways, env scopes |
| Stateful runtime | `deploy/compose/` | PostgreSQL, Valkey, RabbitMQ, Image Edge, backup agent, migration runtime |
| Ops | `ops/` | Observability, NAS, backup, image edge support |
| Recovery | `scripts/recovery/`, `scripts/backup/` | Catalog recovery, PostgreSQL protection/restore |
| Diagnostics | `diagnose-mreader.sh`, `scripts/diagnostics/`, `tests/diagnostics/` | One-command Dockerized fault finding and report bundle |
| Tests | `tests/api`, `tests/browser`, `tests/regression`, `tests/load` | API/integration/browser/static/load qualification |

## 3. Web application map

### Routing

`frontend/src/App.tsx` is the top-level route graph.

Public/user routes:

- `/` -> `Catalog`
- `/advanced-search` -> `AdvancedSearch`
- `/series/:slug` -> `SeriesDetail`
- `/read/:seriesSlug/:chapterSlug` -> `Reader`
- `/login`, `/register`
- protected `/profile`, `/library`, `/notifications`
- `/dashboard` redirects to `/library`

Admin routes are conditionally registered only when `runtimeConfig.adminPlane` is true:

- `/admin`
- `/admin/upload`
- `/admin/storage`
- `/admin/database`
- `/admin/curation`
- `/admin/scraper`
- `/admin/scraper/new-series`
- `/admin/scraper/operations`

### API layer

`frontend/src/api/client.ts` is the browser API facade. It talks only to gateway-owned `/api/...` surfaces, not directly to databases or service-private ports. It covers Auth, Catalog, Reader, Progress, Social/Library, Notifications, Scraper, Media, Lifecycle and Database Protection.

### IndexedDB is actively used

IndexedDB is not dead code. There are **two active browser persistence roles**:

1. **Reading command journal** — `frontend/src/reading/indexedDB.ts`
   - DB: `mreader-reading-v1`
   - object store: `accounts`
   - instantiated in `frontend/src/reading/browser.ts`
   - account/origin-scoped state is coordinated across tabs with `BroadcastChannel('mreader-reading-v1')`
   - protects pending open/checkpoint commands across refresh/offline/timeout races
   - synchronization remains fenced by server revision/session-generation/command-sequence rules

2. **Protected encoded page cache fallback** — `frontend/src/reader/protectedAssetCache.ts`
   - CacheStorage is preferred on secure origins
   - IndexedDB fallback DB: `mreader-protected-assets-v1`
   - store: `assets`
   - key is a token-independent immutable asset identity
   - stores only still-encoded v4 page bytes; decoded image output is not persisted here
   - storage failure/quota pressure is deliberately best-effort and must not break reading

The focused behavioral suite currently passes 31/31, including the production IndexedDB cross-instance transaction test. The browser acceptance source contract also passes and includes IndexedDB quota/two-tab/offline scenarios. Real Playwright execution remains a separate runtime gate.

### Web reader pipeline

Key files:

- `frontend/src/pages/Reader.tsx` — chapter navigation, reading-state capture, chapter grant refresh
- `frontend/src/reader/ProtectedPage.tsx` — protected-byte load/cache/retry path
- `frontend/src/reader/codec.ts` — v4 protected page decode; worker preferred
- `frontend/src/reader/codec.worker.ts` — sequential OffscreenCanvas worker decode
- `frontend/src/reader/protectedAssetCache.ts` — persistent encoded-byte caching
- `frontend/src/reading/*` — local durable reading intent and synchronization

High-level flow:

```text
Reader route
  -> GET /api/reader/{series}/{chapter}
  -> manifest + chapter_token + encoded page metadata
  -> ProtectedPage checks persistent encoded-byte cache
  -> otherwise GET /images/... with current chapter grant
  -> decode v4 in worker/main-thread fallback
  -> render
  -> ReadingRepository records open/checkpoint locally first
  -> POST /api/progress/.../open or /commit
  -> reconcile only accepted/duplicate canonical response
```

## 4. Android application map

Navigation is defined in `ui/MReaderApp.kt` with Catalog, Search, Library, Notifications, Login/Register, Settings, Series, native Reader, and explicit WebReader fallback.

Core layers:

| Layer | Main code | Role |
|---|---|---|
| UI | `ui/screens/*`, `ui/components/*` | Compose screens/components |
| View model | `ui/AppViewModel.kt` | Session/content coordination |
| API | `core/network/MReaderApiAdapter.kt`, `MReaderApiService.kt` | Gateway API integration |
| Domain repository | `core/repository/MReaderRepository.kt` | Main client-side orchestration |
| Reading journal | `ReadingJournal.kt`, `ReadingRepository.kt` | Durable/pending native reading synchronization |
| Protected reader | `ProtectedPageDecoder.kt`, `ProtectedCodecMath.kt` | Native v4 decode |
| Protected byte cache | `ProtectedAssetStore.kt` | Encoded-byte RAM/disk cache; signed-in persistent window |
| User snapshot | `EncryptedUserSnapshotStore.kt` | Android Keystore-backed encrypted profile snapshot |
| Other caches | `MobileContentCacheStore.kt`, `CoverImageStore.kt`, `LocalProgressStore.kt` | Native cache/support state |

Android does **not** use browser IndexedDB. Its equivalent durability is implemented with native encrypted/shared storage and app-cache files. `ProtectedAssetStore` keeps encoded protected bytes, never decoded bitmaps, and bounds retention/cache size.

## 5. Canonical backend service map

The route ownership contract currently contains **139 canonical routes**.

| Owner | Routes | Runtime | Main responsibility |
|---|---:|---|---|
| Auth | 6 | FastAPI | registration/login/logout/profile/admin user count |
| Catalog | 26 | Go/chi | catalog read models, curation, series/chapter mutation, internal publication commit |
| Database Protection | 7 | FastAPI facade in scraper deployment | recovery-point listing, backup/snapshot/drill/restore queue, download bridge |
| Media | 12 | FastAPI + workers | chapter/thumbnail ingestion jobs, media operation state, lifecycle/admin download |
| Notifications | 6 | Fastify in Social service | notification query/read/admin retention |
| Progress | 5 | Go/chi | reading open/commit/history/series-state |
| Reader | 6 | Go/chi | chapter manifest/grant, mobile protected page adapter, image delivery |
| Realtime | 1 | Go/WebSocket | `/api/realtime/ws` |
| Scraper | 53 | FastAPI | discovery/staging/edit/publish/batch/new-series operations |
| Social | 17 | Fastify | bookmarks, subscriptions, smart library, ratings, comments |

### Auth — `services/auth_service`

Layered Python service (`application`, `domain`, `infrastructure`, `routers`). Session state uses the critical Valkey/session infrastructure; durable user/profile truth is PostgreSQL `users`.

### Catalog — `services/catalog_go`

`internal/httpapi/api.go` defines both public/admin routes and internal publication routes. The same image is deployed twice:

- `catalog-go` in user plane with writes disabled
- `catalog-admin` in admin plane with writes enabled

Internal publication/series/cover mutation requires internal token + requesting admin actor + enabled writes. Catalog is the final authority that mutates production series/chapter/page state.

### Reader — `services/reader_go`

Owns chapter manifests, chapter grants, image authorization/delivery and mobile protected-page delivery. It reads catalog/page metadata from PostgreSQL, grants from cache Valkey, can proxy the NAS-backed image path through Image Edge, and maintains derived trending analytics.

### Progress — `services/progress_go`

Owns canonical reading state. The key server stores are `reading_progress`, `chapter_reads`, and view `reading_state_v1`. Accepted commands are ordered/fenced by revision, session generation, sequence and command identity. Changed reading projections enqueue `progress.updated` v2 in the transactional outbox.

### Social/Notifications — `services/social_ts`

Fastify service for bookmarks, subscriptions, Smart Library, ratings, comments and notification query/read surfaces. Comment mutations publish lightweight Valkey pub/sub signals for realtime acceleration; PostgreSQL remains canonical.

### Realtime — `services/realtime_go`

WebSocket hub with two acceleration sources:

- RabbitMQ ephemeral queue bound to `notification.batch.created`; it re-reads canonical notification rows from PostgreSQL before broadcasting
- Valkey pub/sub `social:comments:*` for comment change signals

Realtime signal loss is intentionally recoverable by normal HTTP refresh; realtime is not durable truth.

### Scraper — `services/scraper_service`

Large FastAPI/admin subsystem for source adapters, browser fetches, discovery, drafts, staging, batches, editing, retries, operations and publication coordination. Unpublished bytes live on `scraper-staging` PVC and are referenced by PostgreSQL workflow tables.

### Media/Image — `services/image_service`

FastAPI API plus worker entrypoints. Durable work is `media_operations`; ingestion authority is fenced through `ingestion_operations`. Media transforms raw staged chapter input into protected v4 published assets and obtains Catalog commit receipts. `thumbnail_transformer` is a small authenticated pyvips service used for bounded WebP transformation.

### Outbox Relay — `services/outbox_relay`

Claims due rows from `event_outbox`, publishes to RabbitMQ with publisher confirms, and then marks the row published. A broker-confirmed/DB-ack failure intentionally yields at-least-once redelivery, so consumers must remain idempotent.

### Notification Worker — `services/notification_worker`

Consumes `chapter.published`, `notification.requested`, and worker retry routing. Creates deduped notification rows and emits `notification.batch.created` through the outbox for realtime fanout.

## 6. Data ownership map

Primary durable stores:

| State | Canonical owner/location |
|---|---|
| users/profile | PostgreSQL `users` / Auth |
| series/chapters/pages/curation | PostgreSQL / Catalog |
| current resume | `reading_progress` / Progress |
| exact chapter evidence | `chapter_reads` / Progress |
| Smart Library projection | `reading_state_v1` + Social query composition |
| bookmarks/subscriptions/ratings/comments | PostgreSQL / Social |
| notifications | PostgreSQL / Notifications + worker |
| transactional integration events | `event_outbox` |
| scraper drafts/batches/events/storage attempts | PostgreSQL / Scraper |
| canonical ingestion fence | `ingestion_operations` |
| durable media jobs | `media_operations` |
| cleanup work | `lifecycle_cleanup_jobs` |
| unpublished raw bytes | Kubernetes `scraper-staging` PVC |
| published encoded media/covers | NAS SeaweedFS |
| sessions/non-evictable coordination | critical Valkey |
| chapter grants/derived caches | cache Valkey |
| event/work transport | RabbitMQ |
| DB protection bundles/control | host `~/.mreader/database-protection` |
| Web pending reading journal | browser IndexedDB `mreader-reading-v1` |
| Web encoded-page persistent cache | CacheStorage, then IndexedDB fallback `mreader-protected-assets-v1` |
| Android encoded-page cache | native app cache via `ProtectedAssetStore` |

The PostgreSQL role contract separates capability roles from per-workload login roles. Production write access is narrow: Auth -> users; Progress -> reading state; Social -> social/notification user surfaces; Catalog -> catalog mutations; Scraper -> scraper/ingestion workflow state; Media -> media/ingestion/lifecycle state; dedicated worker exceptions are explicitly documented.

## 7. Event map

Registered event types include chapter/media/series/progress/notification/subscription/cache/account/audit events. The code paths visibly active in this checkpoint include:

```text
Catalog commit
  -> event_outbox chapter.published / series.updated

Progress accepted mutation
  -> event_outbox progress.updated v2

Media accepted/terminal mutation
  -> event_outbox media.uploaded / media.processed

Outbox relay
  -> RabbitMQ topic exchange

Notification worker
  consumes chapter.published + notification.requested
  -> writes notification rows
  -> event_outbox notification.batch.created

Outbox relay
  -> RabbitMQ notification.batch.created

Realtime
  -> reads canonical rows by source_event_id
  -> WebSocket notification.created
```

The registry is broader than the currently obvious active producers/consumers; treat `contracts/events/registry.tsv` as the schema registry, not proof that every listed event family is active on every path.

## 8. Critical end-to-end flows

### A. Normal reading

```text
Web/Android -> Catalog/Series UI
           -> Reader manifest
           -> chapter-scoped grant
           -> encoded page bytes
           -> client-side v4 decode
           -> render
           -> local pending open/checkpoint
           -> Progress command
           -> PostgreSQL commit + outbox event
           -> canonical response reconciles local journal
```

### B. Scrape -> publish

```text
Admin UI
 -> Scraper discovery/draft
 -> staged raw bytes on scraper-staging PVC
 -> ingestion_operations publication fence
 -> Media operation + queue
 -> media-worker v4 transform
 -> publish assets to NAS SeaweedFS
 -> internal Catalog publication command
 -> Catalog validates generation/revision/idempotency
 -> Catalog atomically commits production chapter/pages + receipt + event effects
 -> Scraper/Media reconcile receipt as completed
 -> Lifecycle later cleans safe staging/obsolete generations
```

Catalog, not Scraper or Media, is the final production catalog writer. Media owns final transformed bytes/evidence. Scraper owns editable staging and ingestion intent.

### C. Notification fanout

```text
Catalog chapter.published
 -> event_outbox
 -> outbox-relay
 -> RabbitMQ
 -> notification-worker
 -> notifications table + dedupe receipt
 -> notification.batch.created outbox event
 -> RabbitMQ
 -> realtime-go re-reads notification rows
 -> user WebSocket
```

### D. DB protection/restore

```text
Admin Database UI
 -> /api/admin/database facade
 -> serialized database_operations
 -> backup-agent / host recovery root
 -> verified manifests + checksums
 -> restore-generation/fencing controls
 -> quiesced writer deployment path
 -> shared migration + role reconciliation + readiness sequence
```

The current branch has extensive source/static fencing but real destructive/runtime restore qualification remains a release gate.

### E. One-command diagnostics checkpoint

`./diagnose-mreader.sh` delegates to `scripts/diagnostics/run-diagnostics.sh`.

Flow:

```text
host preflight
 -> build API test image + dedicated diagnostics image
 -> capture pre-test runtime evidence
 -> launch diagnostics container on stateful network
 -> route ownership audit
 -> pytest collect
 -> full or bounded API/functionality suite
 -> mark container-test sentinel
 -> host post-test runtime evidence
 -> report analyzer (redaction + issue classification)
 -> report builder
 -> REPORT.md / REPORT.json / issues.json / endpoint-results.tsv / REPORT_BUNDLE.zip
```

Evidence collectors cover Kubernetes/Docker state, PostgreSQL connectivity/schema/outbox/workflow rows, RabbitMQ queues, Valkey, user/admin gateway health and SeaweedFS. Failures in one diagnostic stage are recorded without suppressing later evidence/report generation.

## 9. Deployment/runtime topology

### Kubernetes `mreader-user`

- `auth-service`
- `catalog-go`
- `reader-go`
- `progress-go`
- `social-ts`
- `frontend`
- `notification-worker`
- `realtime-go`
- `user-gateway`
- HPA: Catalog + Reader
- KEDA: Notification Worker

### Kubernetes `mreader-admin`

- `scraper-service`
- `image-service`
- `outbox-relay`
- `scraper-batch-worker`
- `scraper-series-worker`
- `media-worker`
- `media-thumbnail-worker`
- `lifecycle-worker`
- `scraper-browser` (normally scale-to-zero/default 0)
- `admin-frontend`
- `auth-admin`
- `catalog-admin`
- `admin-gateway`
- KEDA for scraper/media/outbox/lifecycle workers
- `scraper-staging` PVC

### Docker Compose stateful backbone

- PostgreSQL 16
- critical Valkey
- cache Valkey
- RabbitMQ + management
- Nginx Image Edge/cache
- backup-agent
- migration helper profile

Each Kubernetes namespace receives `db`, `redis`, `redis-cache`, and `rabbitmq` ExternalName services pointing back to the Docker host.

### External

- NAS SeaweedFS for published media
- optional Cloudflare Quick Tunnel for public development user edge
- Tailscale Funnel is also supported by project design, but only user gateway :8080 is public; admin :8081 stays local/private

## 10. Important architectural invariants

1. PostgreSQL is durable application truth; RabbitMQ is transport, not job truth.
2. Catalog alone commits production catalog/chapter/page state.
3. Media owns final v4 transformation and media operation evidence.
4. Scraper owns editable staging/discovery/publication intent, not final catalog rows.
5. Progress owns reading state; client journals are pending/offline acceleration, never canonical counts.
6. Browser/Android decode protected v4 bytes client-side; persistent caches contain encoded bytes only.
7. Public gateway blocks admin/scraper/upload and Catalog write surfaces at the network layer before service RBAC.
8. User Catalog deployment is read-only; admin Catalog deployment enables writes.
9. Realtime is an acceleration layer; missed signals recover from PostgreSQL/API state.
10. Restore/deploy paths are fail-closed around generation, quiescence, migrations, grants and readiness.

## 11. High-value navigation index

For future changes, start here by domain:

| Change | Start files |
|---|---|
| Web reader/scroll/prefetch | `frontend/src/pages/Reader.tsx`, `frontend/src/reader/ProtectedPage.tsx` |
| Browser IndexedDB reading durability | `frontend/src/reading/indexedDB.ts`, `repository.ts`, `browser.ts`, `accounts.ts` |
| Protected browser cache | `frontend/src/reader/protectedAssetCache.ts` |
| Reading server semantics | `services/progress_go/internal/httpapi/api.go`, `internal/progress/service.go`, `internal/store/*` |
| Reader manifest/token/image | `services/reader_go/internal/httpapi/api.go`, `internal/store/store.go`, `internal/imagetoken/*` |
| Catalog writes/publication | `services/catalog_go/internal/httpapi/api.go`, `internal/store/publication.go`, `events.go` |
| Scraper stage/publish | `services/scraper_service/app/main.py`, `series_drafts.py`, `publication_bridge.py`, `staging_store.py` |
| Media publish | `services/image_service/app/worker.py`, `media_operations.py`, `catalog_publication.py` |
| Lifecycle cleanup | `services/image_service/app/lifecycle_worker.py`, `lifecycle_cleanup.py` |
| Social/Library/comments | `services/social_ts/src/routes.ts` |
| Notifications | `services/notification_worker`, `services/social_ts/src/routes.ts` |
| Realtime | `services/realtime_go/internal/sources/*`, `hub/*` |
| DB protection | `services/scraper_service/app/database_facade.py`, `database_protection.py`, `scripts/backup/*` |
| Hybrid deployment | `scripts/hybrid/*`, `deploy/docker-desktop-hybrid/*`, `deploy/compose/*` |
| Diagnostics | `diagnose-mreader.sh`, `scripts/diagnostics/*`, `tests/diagnostics/*` |
| API ownership audit | `contracts/ownership/routes.v1.json`, `scripts/tests/ownership-route-audit.py` |
| PostgreSQL least privilege | `contracts/ownership/postgres-roles.v1.json`, P09 role scripts |

## 12. Verification performed while building this map

- Drushti runtime restored and `Drushti doctor` passed for Ripwire, Caveman, Headroom, RTK and Graphify availability.
- Ripwire repository mapping used on full architecture, IndexedDB/reader, and diagnostics domains.
- Supported Web reading behavioral command: **31/31 PASS**.
- Browser reading acceptance source contract: **PASS**.
- Diagnostics Python unit suite: **16/16 PASS**.
- Diagnostics harness static: **PASS**.
- Diagnostics evidence static: **PASS**.
- Diagnostics dependency snapshot static: **PASS**.
- The temporary Python ZIP extraction initially dropped Unix executable bits; the original ZIP was checked and does record `rwxr-xr-x`. Restoring the recorded mode bits in the temporary analysis tree made the executable-bit-sensitive diagnostics tests pass. This is an analysis-extraction artifact, not a package defect.
- Fresh Graphify build was not started because no `graphify-out/graph.json` is packaged and Drushti explicitly keeps a new graph build opt-in; the installed Graphify runtime is available but reports fresh AST extraction limited by unavailable tree-sitter parser dependencies in this sandbox.
- Real Docker Desktop/Kubernetes/PostgreSQL/Playwright/Android runtime qualification was not performed in this sandbox.

## 13. Current continuation position

Runtime and actor-journey acceptance remain distinct from static/source mapping. Use the generated development reference plus `REPORT_BUNDLE.zip` evidence to connect real failures back to the owning source surface.
