# MReader RC4.85 — development and change-impact reference

**Source checkpoint:** recorded dynamically in the package-generated `REFERENCE-MANIFEST.md`
**Canonical branch recorded by package:** `sequential/p06.4-caller-cutover`
**Purpose:** make future development and issue repair start from the real ownership/dependency graph instead of rediscovering the repository.

## 1. How to use this reference

For an issue, do not start by editing the first UI file that looks related. Use this order:

```text
symptom
  -> classify domain in ISSUE-TO-CHANGE-INDEX.md
  -> Graphify query on development-graph.json
  -> Graphify explain the first concrete file/service/route
  -> Graphify affected on the candidate change
  -> inspect route/reading/catalog/event contract involved
  -> inspect the listed focused tests
  -> patch the owning layer only
  -> run focused tests + affected tests + ownership/static gates
  -> re-run Graphify affected if the change moves a boundary
```

Prefer the issue-oriented graph first. Use the deeper code graph only after the domain is known.

## 2. Canonical runtime topology

```text
USER PLANE
User Web / Android
       |
       v
 user-gateway :8080
       |
       +--> Auth ---------> PostgreSQL + critical Valkey sessions
       +--> Catalog ------> PostgreSQL + cache
       +--> Reader -------> PostgreSQL + cache Valkey + Image Edge -> SeaweedFS
       +--> Progress -----> PostgreSQL + event_outbox
       +--> Social -------> PostgreSQL + Valkey comment signals
       +--> Realtime <----- RabbitMQ notification batches / Valkey comment signals

ADMIN / INGESTION PLANE
Admin Web
   |
   v
 admin-gateway :8081
   |
   +--> Scraper ---------> PostgreSQL + scraper staging PVC
   |        |
   |        v
   |      Media/Image ----> protected-v4 transform -> NAS SeaweedFS
   |                               |
   |                               v
   +--------------------------> Catalog Admin -> PostgreSQL canonical commit

ASYNC PATH
Catalog / Progress / Social durable mutation
        -> PostgreSQL event_outbox
        -> Outbox Relay
        -> RabbitMQ
        -> Notification Worker
        -> PostgreSQL notifications + notification.batch.created
        -> Realtime
```

Stateful Docker Compose backbone remains PostgreSQL, critical/cache Valkey, RabbitMQ, Image Edge, backup agent. Stateless application services/workers run in Docker Desktop Kubernetes. SeaweedFS remains external on the NAS.

## 3. Hard ownership boundaries

These boundaries should be treated as design constraints during repairs:

| Capability | Canonical owner | What not to do |
|---|---|---|
| User identity/session | Auth | Do not make UI or another service mutate users directly. |
| Catalog production state | Catalog | Do not let Scraper/Media write production series/chapter/page rows directly. |
| Editable/unpublished ingestion | Scraper | Do not make Catalog own staging/editor workflow state. |
| Final protected-v4 media transform | Media/Image | Do not duplicate transformation in Scraper or Catalog. |
| Reading canonical state | Progress | IndexedDB/Android journal are durable client intent, not server truth. |
| Chapter manifest/grant/image authorization | Reader | Do not move token/grant logic into the browser. |
| Durable async delivery | PostgreSQL outbox + Outbox Relay | RabbitMQ is transport, not source of truth. |
| Published media bytes | NAS SeaweedFS | Do not make DB blobs or staging PVC the published-media authority. |
| Database recovery engine | Database Protection + host recovery root | Do not expose host paths through public routes. |

## 4. Client persistence map

### Web

```text
frontend/src/reading/indexedDB.ts
        -> IndexedDB `mreader-reading-v1`
        -> durable pending reading commands / account-scoped reading journal
        -> frontend/src/reading/browser.ts
        -> frontend/src/reading/repository.ts
        -> Progress API

frontend/src/reader/protectedAssetCache.ts
        -> CacheStorage preferred
        -> IndexedDB `mreader-protected-assets-v1` fallback
        -> encoded protected-v4 bytes only
        -> never intentionally persists decoded final page pixels
```

Graphify confirms `frontend/src/reading/browser.ts` imports `indexedDB.ts`, and the blast radius reaches `Reader.tsx`, `Library.tsx`, `Catalog.tsx`, `SeriesDetail.tsx`, auth/session hooks, and the reading synchronization layer.

### Android

```text
ReadingJournal.kt / ReadingRepository.kt
        -> native durable reading synchronization

ProtectedAssetStore.kt
        -> encoded protected-page persistence/cache

EncryptedUserSnapshotStore.kt
        -> Keystore-backed user snapshot
```

Android does not use browser IndexedDB.

## 5. Main end-to-end flows

### Reading

```text
Web Reader / Android Reader
  -> GET /api/reader/{seriesSlug}/{chapterSlug}
  -> Reader Go
  -> catalog/page metadata + chapter grant
  -> encoded protected bytes via image path
  -> client protected-v4 decode
  -> persistent encoded-byte cache
  -> local reading journal
  -> POST /api/progress/.../open or /commit
  -> Progress Go
  -> PostgreSQL reading state + transactional progress.updated event
```

Graphify path evidence: `User Web -> GET /api/reader/... -> service:reader_go` is two hops; `User Web -> GET /api/progress/history -> service:progress_go` is two hops.

### Publication

```text
Admin Scraper UI
  -> Scraper drafts/staging
  -> staging PVC
  -> ingestion operation / revision + generation fences
  -> Media/Image job
  -> protected-v4 transform
  -> NAS SeaweedFS
  -> internal Catalog publication command
  -> Catalog transaction
  -> production series/chapter/page rows + receipt + event_outbox
```

Graphify service path: `service:scraper_service -> service:image_service -> service:catalog_go`.

### Publication notification

```text
Catalog
  -> Outbox Relay
  -> RabbitMQ
  -> Notification Worker
  -> canonical notification rows / notification.batch.created
  -> Realtime
```

Graphify path from Catalog to Realtime is three service/transport hops in the issue-oriented graph.

### Database protection

```text
AdminDatabase.tsx
  -> /api/admin/database...
  -> Database Protection capability/facade
  -> PostgreSQL tools + host recovery root
  -> verified backup/snapshot/catalog
  -> restore/drill with fencing and recovery journal
```

## 6. Route ownership reference

`contracts/ownership/routes.v1.json` is the canonical route map. At this checkpoint it classifies **139 routes**:

| Owner | Route count |
|---|---:|
| Scraper | 53 |
| Catalog | 26 |
| Social | 17 |
| Media | 12 |
| Database Protection | 7 |
| Auth | 6 |
| Reader | 6 |
| Notifications | 6 |
| Progress | 5 |
| Realtime | 1 |

When an API issue arises, inspect the route entry before modifying gateway or service code. It records owner, handler, access plane, consumers, dependencies, permitted writes, event effects and acceptance evidence.

## 7. High-risk graph hubs

Graphify's issue-oriented graph reports the biggest architectural hubs as regression tests, scripts, Scraper, Web, Android, PostgreSQL, Catalog, Media, API tests, Auth, Social, Reader, Notification, Progress, event contracts and Kubernetes deployment.

This is useful operationally: changes to Scraper/Catalog/Media, shared client API/state, PostgreSQL schema, or deployment scripts should be assumed to have a broad blast radius until `graphify affected` proves otherwise.

## 8. Graph levels

### Issue-oriented graph — use first

`graphify-out/development-graph.json`

- 957 nodes
- 1,754 edges
- all 139 route ownership records
- source files/imports
- clients/services/storage/infrastructure
- publication and notification boundaries
- route handlers, consumers, dependencies, permitted writes and evidence tests
- explicit Web/Android persistence concepts

### Deeper code graph — use second

`graphify-out/code-graph.json`

- 4,675 nodes
- 10,123 edges
- 725 repository files indexed
- file/import graph
- Python AST functions/classes where available
- Go/TypeScript/Kotlin declaration/call heuristics
- routes, environment variables, tables, storage/broker concepts and test references

The deeper graph is intentionally noisier and is for file/symbol-level exploration after the owning subsystem is identified.

## 9. Change discipline for future Drushti runs

Before editing:

1. `graphify query` the symptom/domain on `development-graph.json`.
2. `graphify explain` the likely owning service/file.
3. `graphify affected` the exact file at depth 2–4.
4. Inspect the relevant canonical contract (`routes`, reading, catalog publication, events, session).
5. Use Ripwire for reuse/quality/affected-test hints.
6. Apply Superpowers systematic debugging/TDD before structural refactors.

After editing:

1. Run the smallest behavioral test first.
2. Run tests surfaced by Graphify affected and the issue index.
3. Run ownership/static gates if route, DB, event, gateway or deployment behavior changed.
4. Run `git diff --check` and source-format/build checks.
5. Regenerate/update Graphify artifacts when parser support is available; until then regenerate the deterministic reference graph if structural paths changed.
6. Record the new source checkpoint in the generated reference rather than silently reusing an older graph.

## 10. Graph provenance limitation

`Drushti doctor` reports Graphify 0.9.63 healthy for query/path/explain/affected/god-nodes, but fresh native AST extraction is limited in this sandbox because Tree-sitter parser packages are unavailable. `graphify update . --no-cluster` was attempted and failed specifically on the missing Tree-sitter dependency.

Therefore the bundled graphs are not falsely represented as a native Graphify AST extraction. They were built deterministically from this repository using source imports, Python AST where available, route ownership contracts, deployment/config references and explicit architecture boundaries, then validated through Graphify's actual navigation and blast-radius commands. Every manually inferred boundary is tagged `INFERRED` in the graph; direct contract/import relationships are tagged `EXTRACTED`.
