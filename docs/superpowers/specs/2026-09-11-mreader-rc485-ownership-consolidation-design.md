# MReader RC4.85 — ownership and UI-state consolidation

Date: 2026-09-11

Status: high-level design approved; this detailed specification awaits review.

Revision note: incorporates the user's follow-up about immediate local reading state with background synchronization.

Target release: `1.3.0-rc4.85`; Android remains **Mreader / ver.1.1.0**, with build code 485.

Deliverable status: design only. No application changes, migration executions, deployment, or restore are represented as completed by this document.

## 1. Decision and scope

Preserve MReader's guest, reader, and administrator capabilities while removing competing owners of the same facts. Keep the existing microservice deployment. Do not add a dedicated UI-backend service, a second application database, another broker, or a materialized Smart Library table.

The user approved the canonical-owner approach and explicitly selected removal of legacy runtime paths after one-time data migration. Compatibility belongs in upgrade and recovery tools, not in normal request handling.

This is a coordinated architectural change, delivered in independently testable work packages. The final release is qualified only when all affected service, client, migration, and deployment contracts agree. A passing static audit alone is not release qualification.

### Fixed constraints

- Retain Docker Desktop Kubernetes for stateless user/admin planes; Compose for PostgreSQL, critical Valkey, cache Valkey, RabbitMQ, Image Edge, and the existing backup agent; external NAS SeaweedFS for published media.
- Retain KEDA/HPA and the existing resource limits. Browser scraping remains on demand. Do not introduce Azure deployment changes in this release.
- Keep the public gateway separate from the private admin gateway. Preserve both configured development-edge options; expose only the gateway.
- Preserve current NAS object identities and protected-image encoding metadata. Recovery validation must not rewrite NAS content.
- Keep chapter grants and protected v4 delivery. Unknown/unsupported clients or formats receive a clear contract error, not legacy fallback behavior.
- Preserve existing data, configuration, and authoritative volume selections. Removing duplicate code is not authority to reset storage.
- No live production restore or destructive migration is executed merely to test this release. Use isolated fixtures and explicit operator procedures.
- This design aims for consistent, observable behavior under defined failures; it does not promise that distributed services can never fail.

## 2. Evidence and source selection

The uploaded packages are not a linear sequence of supersets. Archive suffixes and source timestamps cannot determine whether a capability is present.

| Source | Role in consolidation | Evidence to retain |
| --- | --- | --- |
| RC4.81 history/public-metrics package | Behavioral reference, not replacement source | User/admin capabilities, public aggregates, read/history continuity, notifications, scraping, restore workflows |
| RC4.84-r2 | Application and upgrade-recovery corrections | Recently Opened on both clients, explicit URL-backed staging repair, furthest-reading preservation intent, local pre-upgrade safeguard, environment continuity |
| RC4.84-r4 | Intermediate infrastructure comparison | Explains the transition in volume-adoption behavior; not an independent runtime mode |
| RC4.84-r5 | Starting source tree | Current labeled distribution and explicit legacy-volume recovery policy; not assumed to contain r2 fixes |

The future working tree starts from r5. Port capabilities and safeguards from r2 with tests; do not overwrite whole directories or import older runtime mechanisms from RC4.81. The original archives stay unchanged.

### Source-confirmed issues affecting this design

| Finding | Source evidence | Required design consequence |
| --- | --- | --- |
| Recently Opened was restored in r2 but is absent in r5 | `frontend/src/pages/Library.tsx`; Android `ui/screens/LibraryScreen.kt` | Restore the capability through the consolidated Library response, not by copying a second client fetch |
| One Progress owner still has split persistence timing | `services/progress_go/internal/progress/service.go`: synchronous activity write, then Redis-stream resume update | A successful save must mean the canonical PostgreSQL reading transaction committed |
| Progress and Social calculate reading views separately | Progress `internal/store/store.go`; Social `src/routes.ts` | One Progress-owned read view and one vocabulary for last opened, resume, furthest, and completion |
| Earlier migrations may lose furthest evidence or associate a different chapter's checkpoint | `db/migrations/047_consolidate_reading_state_rc482.sql`; `048_rc483_current_baseline.sql` | Pre-drop preservation and forward-only repair; require chapter-ID equality when using checkpoint evidence |
| Tests have been partially renamed without preserving their meaning | `tests/api/test_17_smart_library.py` queries `chapter_reads.furthest_chapter_id`, absent from migration 039; another test expects history from progress alone | Correct tests against the approved contract and execute them against PostgreSQL |
| Production metadata has several mutation implementations | Catalog `internal/store/store.go`; Scraper `app/publication.py` and `series_drafts.py`; Media `app/services/chapter_ingestion.py` | Catalog is the only owner of production series/chapter/page commits |
| Two queues can request the same backup capability | Scraper `app/main.py`, `backup_requests.py`, `database_protection.py`; `scripts/backup/backup-agent.sh` | Migrate and retire `backup_requests`; retain one `database_operations` queue |
| Durable recovery artifacts still use NAS inventory/storage | Backup agent; `.env.example`; stateful Compose | Replace recovery storage/inventory ownership with host-home directories; retain the guarded restore engine |
| Pre-upgrade protection can be skipped in r5 when NAS proof is unavailable | `scripts/hybrid/stateful-up.sh` | Mandatory local safety recovery point before destructive schema work, independent of NAS backup proof |
| Android can retain invisible origin overrides after an APK update | `core/settings/ServerConfigStore.kt` | Remove legacy origin preferences once and consistently use the build-configured gateway |
| Local checkpointing exists but is not one shared, account-safe synchronization contract | Web `Reader.tsx` uses unscoped `mreader:progress:<series>/<chapter>` keys and exit-only sending; Android has `LocalProgressStore` and separate overlay logic | Consolidate local pending state, acknowledgement, and account isolation instead of adding another independent fallback |

These findings come from source inspection, not a live deployment test. They must become reproductions or contract fixtures before implementation changes are marked verified.

## 3. What “one owner” means

An owner is a domain module and its authorized processes, not necessarily one pod or one SQL statement. Multiple replicas may execute the same domain command. Different domains must not independently implement that command.

- **Canonical facts:** persisted by their domain owner.
- **Read projections:** derived from canonical facts, read-only to consumers.
- **Transport:** routes commands/events; does not invent business state.
- **Caches and realtime:** disposable acceleration/signals; not competing truth.
- **UI pending state:** clearly unconfirmed local intent; never merged into durable counts as though acknowledged.

The retained shared PostgreSQL database is a deliberate coupling. RC4.85 enforces write isolation and versioned read interfaces within that database; it does not claim database-per-service isolation. Read projections use primary PostgreSQL to satisfy read-after-write behavior. Read replicas are outside this release.

### Ownership registry

| Domain | Canonical facts and tables | Authorized execution surface | Read consumers |
| --- | --- | --- | --- |
| Auth | `users`; versioned session contract | Auth user/admin instances; inactive accounts cannot authenticate | All session consumers; profile UI |
| Catalog | `series`, `chapters`, `pages`, `genres`, `series_genres`, `tags`, `series_tags`, `editor_picks`, `announcements` | Catalog admin writer; public Catalog has read-only database privileges | Browse/Search/Series, Reader, ingestion validation, declared read projections |
| Reading | `reading_progress`, `chapter_reads`; read-only `reading_state_v1` | Progress only | Reader checkpoint APIs, Series markers, History, Social Library |
| Social | `bookmarks`, `subscriptions`, `series_ratings`, `comments`; public aggregate view | Social commands | Guest metrics/comments, signed-in relationship state, Library |
| Library presentation | No persistent membership/state table | Social's Library query module | Web and Android, including Browse Continue Reading |
| Notifications | `notifications`, `notification_event_receipts` | Worker creates/deduplicates; Social notification module marks read and prunes under explicit field/operation grants | Inbox and unread counts; Realtime signals |
| Reader delivery | Manifests and chapter grants; no personal reading writes | Reader and existing native mobile adapter | Web/native/WebView reader paths |
| Trending | `series_trending_hourly`, explicitly derived | Existing Reader analytics collector writes; Catalog reads | Trending shelves; never a personal-history source |
| Ingestion workflow | `ingestion_operations` plus existing scraper workflow detail tables | Ingestion module in existing Scraper API/workers | Unified admin operation state; manual/scraper/batch entry points |
| Media transformation | `media_operations`; immutable encoded outputs and storage-attempt evidence | Existing Media/thumbnail workers | Ingestion coordinator, exports, Catalog publication validation |
| Media lifecycle | `lifecycle_cleanup_jobs`; deletion attempts and results | Lifecycle module; producer commands may enqueue transactionally using one defined contract | Admin cleanup status; retry controls |
| Database Protection | `database_operations`, `database_protection_runtime`; host recovery manifests and cutover journal | Dedicated protection module and existing backup agent | Private DB Protection page and CLI |
| Event delivery | `event_outbox` and delivery metadata | Each domain appends its events within its transaction; Outbox Relay changes delivery fields only | RabbitMQ workers |
| Schema | `schema_migrations`, indexes, grants, read views | Migration role only | Readiness and release diagnostics |

Catalog publication receipts are a new `catalog_mutation_receipts` table, owned by Catalog. They record durable idempotency outcomes and are not a second ingestion-status table.

### Enforceable boundaries

Use separate, non-superuser runtime credentials and explicit table/column/function grants. Migration and protection privileges remain separate from application runtime privileges. The registry declares the narrow exceptions: notification field owners, outbox append/delivery roles, transactional cleanup enqueue, and foreign-key cascades resulting from an authorized Catalog/Auth deletion.

Do not call broad superuser access “one writer” just because a text search finds only one current caller. Verification must exercise both permitted writes and forbidden writes, including ORM paths. A required owner migration or grant failure makes the affected service unready; it must not silently fall back to broader credentials.

## 4. Reading and Smart Library contract

### 4.1 Facts must stay distinct

| Concept | Meaning |
| --- | --- |
| Last opened | Most recent accepted chapter-open action; changes when an older chapter is reopened |
| Resume | One active chapter/checkpoint for a user and series, held in `reading_progress` |
| Furthest reached | Highest chapter-number evidence in the ledger, including explicitly labeled migrated reach evidence; not proof every earlier chapter was read |
| Read marker | Evidence for that exact chapter, not all chapters below furthest |
| Completion | Explicit end-of-chapter completion, or valid historical evidence for the same chapter; monotonic on reread |
| Updates / caught up | Published chapters after furthest / no published chapters after furthest; not an “all chapters completed” claim |
| Not started | Saved/followed membership with no reading evidence |

Retain the RC4.81 meaning of Updates. A missing earlier chapter is not counted as a new chapter after furthest. Public UI wording must make this distinction clear. A series with no published chapters has an unavailable reading action, not a fabricated link or a false completion claim.

`reading_state_v1` is a normal, non-materialized PostgreSQL view owned by Progress. It exposes one row per user/series with history presence, last-open target, current checkpoint, furthest evidence, and revision. Consumers use this view rather than copying its ranking SQL. Exact read/completion markers remain a Progress endpoint over the exact chapter ledger. All user-specific reads are authorized and scoped to the current user.

### 4.2 Acknowledgement and ordering

Keep `/api/progress/{series}/{chapter}/open` and `/commit`. Both execute through one Progress command module:

1. Authenticate, compare the queued `X-MReader-Account-ID` freshness fence with that authenticated user before target lookup, validate the published target, and validate bounded page/scroll values. The header never supplies identity; a missing or different header on a mutation is `account_mismatch`. Progress GET/history/state routes also reject a supplied mismatch but remain compatible with headerless direct reads.
2. Resolve the command against the current per-series reading revision.
3. Commit the checkpoint/ledger effects and any required outbox record in a single PostgreSQL transaction.
4. Return the accepted canonical state and revision only after commit.

Retire the Progress Redis-stream write-behind path from normal runtime. Keep scrolling updates local and coalesced; do not write to the server on every scroll pixel or image decode. The local-first follow-up adds the bounded dirty-checkpoint background policy in section 4.4 to the existing exit/end flushes. A database failure returns an unsaved/retryable response, not success from a cache write.

Add a server-issued reading-session generation and monotonically increasing command sequence to existing reading rows. An open request carries its last observed revision; a conflicting concurrent open returns the current state and requires reconciliation, not an automatic override. Checkpoints identify their accepted session and sequence. A delayed checkpoint from an older session cannot replace the current resume chapter or reorder Recently Opened; it can contribute validated exact-chapter completion evidence without taking ownership of resume.

Clients allocate a fresh UUID for every new command and keep a transmitted retry immutable. A duplicate of the latest checkpoint identity/payload retained on that chapter is a no-op; the same retained sequence/ID with different submitted content is a conflict, even when normalization would store the same clamped page. Sequences are compared inside the transaction. Use per-chapter ledger fields for completion/checkpoint deduplication and the per-series row for current-session ordering, not a second permanent reading-command log. The latest open identity is retained per chapter, and repeating it does not create new recency. Older exact retries remain fenced by revision/session/sequence, but once an ID is superseded, reuse with a new sequence/revision is outside the server's historical-uniqueness guarantee. Clients never automatically turn a stale request into a fresh open.

An open of the current resume chapter preserves its existing checkpoint. An explicit open of a different chapter selects that chapter and starts at its valid initial position unless a matching canonical checkpoint is available; it does not borrow another chapter's page number. Migration persists a ledger-only or newer-ledger selected checkpoint back to that exact chapter so it survives an away-and-back open. Client clock values are not authoritative ordering keys. Locally unsynced checkpoints remain account-scoped and visible as pending; a timeout is reconciled before retry. Logout never replays one account's pending state into another.

Authoritative personal reads bypass stale reading cache entries. Revisions protect in-flight responses; cache TTL alone is not a consistency mechanism. Successful commits invalidate the relevant client queries, and both clients fetch the server projection. Media/manifest failure must not invent reading completion. Prefetching is not opening a chapter.

### 4.3 One Library response

Retain `GET /api/social/library` and current scope/state/sort meanings. The response has:

- `contract_version: 1`, `generated_at`, and request identity metadata;
- `items`, `total`, `offset`, `limit`, `has_more`;
- `summary` with all/bookmark/following/history and reading-state counts;
- `recently_opened` with a bounded item list and unique-series total;
- per-item canonical reading revision, reading state, availability, and typed action targets.

Select items, totals, summary, and recent history in one SQL statement or one explicitly consistent read transaction. No independently refreshed History “floor.” The recent rail uses global history ordered by last-open evidence, limited to 12; it is displayed only in All/History when the reading-state filter is All. Its count is not the number of cards on the current page.

Browse Continue Reading also uses this canonical Library history projection. `/api/progress/history` may remain as a purposeful read API over the same view for direct History consumers and contract tests; it is not a second owner and is not fetched alongside Library to reconstruct Library truth.

Use stable unique tie-breakers including `series_id` for every sort. Keep bounded server pagination and reset pagination when scope/sort/filter/account changes. Request-generation checks discard late responses. A refresh replaces the current result set atomically; loading another page must not overwrite summary/recent data with an older response. De-duplicate IDs when the underlying catalog changes and invalidate/reload after personal mutations. Offset pagination is not represented as a frozen snapshot across concurrent server changes.

### 4.4 Immediate local UI with background synchronization

The user's local-storage proposal is compatible with canonical backend ownership. Local responsiveness and server consistency solve different problems: the first avoids waiting on the network for rendering; the second ensures acknowledged facts agree across screens and devices.

The client maintains one reading-state repository with a **confirmed server snapshot** and a **pending local command overlay**. Reader, Continue Reading, Recently Opened, and the affected Series/Library card subscribe to that repository. They do not each keep an unrelated reading-history reconstruction.

| Stage | Local behavior | Server meaning |
| --- | --- | --- |
| User reads or changes position | Update memory immediately; persist the bounded checkpoint asynchronously; show local position | No claim of server persistence |
| Save is pending/offline | Show the affected resume/read preview with `Saving` or `Saved on this device` | Other devices may still show the last confirmed position |
| Background request runs | Send a coalesced versioned command; do not block rendering | Progress validates and commits the canonical transaction |
| Acknowledgement arrives | Save returned canonical state; remove only the acknowledged pending generation | Ledger/checkpoint state is confirmed and normal projections can refresh |
| Failure/conflict occurs | Preserve retryable local intent; reconcile stale versions; show sync problem when needed | No false saved state and no unconditional overwrite of another device |

Use IndexedDB for the Web reading snapshot/outbox so asynchronous updates and conditional acknowledgement cleanup can share transactions. Keep only small preferences in `localStorage`; retire the old writable unscoped Progress keys once the new store is established. Old unscoped checkpoints cannot be assigned to a signed-in user without provenance: they may remain guest-only local evidence but must not be uploaded into whichever account logs in next. `localStorage` is synchronous; IndexedDB is the asynchronous option appropriate for this queue. [Web Storage documentation](https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API)

Android reuses and consolidates the existing local checkpoint repository behind the same logical contract. Persistence runs off the UI thread. Do not add a new server database or a second native synchronization subsystem solely for this behavior.

Persist only necessary reading metadata: origin/installation scope, account or guest scope, series/chapter IDs and route labels, checkpoint, exact completion intent, session generation, command ID/sequence, expected server revision, and sync status. Local state is untrusted input: the server derives the user from the authenticated session and validates the target and values. Do not copy session secrets or image-grant tokens into the reading queue.

Coalesce repeated position changes within one chapter/session to its latest dirty checkpoint, while retaining distinct chapter-open and completion intents. Local persistence is debounced to at most one write per second during activity, with immediate best-effort persistence at navigation/end. The default active-reading network checkpoint interval is 30 seconds while dirty, plus end/chapter/app exit; these are maximum-frequency bounds, not guarantees when the browser is suspended. Do not send clean-state heartbeats. Permit one in-flight sync per series/session, use exponential retry backoff capped at 60 seconds with jitter, and retry on reconnect/app foreground. Authentication failures pause upload until the same account is reauthenticated; validation/deleted-target failures require reconciliation rather than infinite retries.

Bound the local journal to 500 pending chapter/session records and 5 MiB of serialized reading data per account. Compact redundant checkpoints, prune confirmed cache entries, and never silently discard an unacknowledged distinct chapter/completion intent. If the pending bound or storage quota is reached, continue reading in memory, attempt sync, and clearly report that crash-safe local saving is unavailable; do not claim all subsequent activity is durable. Confirmed local cache entries may expire after 7 days; dirty entries are not TTL-deleted while that account remains active. Explicit logout/clear-data removes private local state after warning about unsynced changes when present.

Across Web tabs, coordinate through the transactional store and notifications; racing requests remain safe through server idempotency/revision rules. An acknowledgement for generation N must never delete the newer generation N+1 produced while the request was in flight. If an open is created offline, its dependent checkpoint waits for that open to be accepted and assigned a server generation. A conflicting later open on another device is reconciled rather than automatically rebased by the background sender.

The overlay can immediately show the affected card's local chapter/position and a pending recent entry. It must not manufacture global History totals, unseen filtered result sets, unread counts, or completed chapters. After acknowledgement, fetch the authoritative Library projection and retire the overlay. This avoids reintroducing RC4.81's independent safety-floor merge under a new name.

Browser background execution is best effort, not guaranteed after close. Treat service-worker Background Sync as an optional enhancement, not a dependency; resume pending work when the app next opens. `sendBeacon` returning true means queued for sending, not a server acknowledgement, so it must not clear the pending record. [Background Sync](https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API), [sendBeacon](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/sendBeacon)

## 5. One production publication owner

Scraper owns discovery, editable private staging, selection, retries, cancellation, and workflow progress. Media owns conversion, v4 encoding, immutable output objects, and transformation execution. Catalog owns production metadata, publish visibility, revisions, and associated events.

### 5.1 Canonical commit boundary

Create a private, versioned Catalog command interface under `/internal/v1/catalog`. It is not exposed by either public gateway. Ingestion calls it with authenticated workload credentials; the Catalog command validates the service identity and retained requesting-admin identity. Being inside the network is not authorization.

Series creation, cover changes, chapter creation/replacement/publication, and explicit metadata edits all use Catalog domain commands. Public admin routes can remain distinct entry points but must invoke the same domain implementation. There is no direct Scraper or Media write permission on production Catalog tables.

A chapter publication command includes operation ID, source revision, stable idempotency key, payload digest, series/chapter identity, expected Catalog revision for replacement, and a bounded page manifest. Pages include dimensions, exact immutable primary/responsive object paths, checksums, and v4 decoding metadata. No caller-provided arbitrary filesystem paths or fetch URLs are accepted as output evidence.

Media records a durable completion receipt before Catalog commit. Catalog validates that receipt and its manifest digest using a declared read contract, validates current target ownership and page count, and rejects incomplete/unverified output. No half-published chapter is observable. Large file conversion/upload happens before the short Catalog transaction; no database locks are held during network image processing.

Catalog commits chapter/pages, the series revision/update, the idempotency receipt, and relevant outbox/cleanup effects atomically. An identical retry returns the recorded result; the same key with different content returns a conflict. Expected-revision checks serialize explicit overwrites. An ambiguous response is resolved using the receipt; callers do not infer that a timeout means “nothing committed.”

`chapter.published` is emitted once for the defined publication revision. Notification uniqueness includes that source revision. A retry is not a new publication. A metadata-only edit is not a new chapter notification. New-series identity uses normalized uniqueness and locked/idempotent Catalog creation; client-side title checks remain hints, not the concurrency guarantee.

### 5.2 Ingestion operation state

Add one `ingestion_operations` header for user-visible ingestion lifecycle. Its owner is the ingestion coordinator in existing Scraper processes. Manual upload routes, batch ingestion, existing-series scrape, and new-series scrape all establish or retrieve an operation before scheduling their work. Media status remains a transformation subtask, not a competing definition of “published.”

The header records operation ID, source kind, requesting actor, parent/batch link, status, phase, revision, selected/staged/published/failed counts, cancellation request, lease/fencing generation, and a safe error code. Existing draft/batch records keep detailed editable data. Their local statuses may describe their specific subtask, but only the coordinator determines the overall operation response.

| Status | Meaning and allowed continuation |
| --- | --- |
| `queued` | Accepted durably; worker may claim a lease |
| `running` | Discovery, staging, encoding, publication, or reconciliation in progress |
| `needs_review` | Waiting for a deliberate admin review/edit/publish decision |
| `cancel_requested` | No new work is scheduled; outstanding work must resolve ownership |
| `cancelled` | No worker can still publish; operation-owned private cleanup is tracked |
| `completed` | All selected publish targets have authoritative Catalog receipts |
| `completed_with_errors` | Successful targets remain published; failed targets and retry actions are explicit |
| `failed` | Operation cannot progress without retry or correction; no guessed success |

Acknowledgement is a visibility field, not deletion or a second completion state. Refresh/reconnect reads the persisted operation, not local component memory. RabbitMQ redelivery and KEDA scaling never bypass lease/fencing and idempotency checks.

Cancellation racing with a commit has a defined winner. If Catalog committed, retain that published content and report it. If no commit is proven, stop future scheduling and clean only owned private/output attempts. If commit outcome is unknown, enter reconciliation and preserve objects. Never mark cancelled while a worker can still commit.

### 5.3 Staging and thumbnail consolidation

Retain the canonical Scraper staging PVC and its identity checks. Explicit Stage/Retry may reconstruct URL-backed missing files. Missing manual uploads require re-upload. Publish and Preview stay strict readers of the canonical staging store; neither silently downloads substitute content. Repaired bytes are committed only if the draft revision and worker fence still match, so repair cannot resurrect cancelled or overwritten staging.

Manual media input objects retain their declared Media staging namespace; they are not mislabeled as Scraper PVC files. The operation records each storage class and owner. Different storage classes are legitimate, duplicate location guesses are not.

Consolidate thumbnail conversion behind one Media transformation command. Dashboard, Series Detail, and scraping may remain different UI entry points. Catalog alone attaches the verified cover reference. An inline convenience route must invoke the same durable command, with an explicit queued/running result if work is unfinished.

## 6. Deletion, events, and failure isolation

Catalog deletion first removes public metadata visibility and records cleanup intent in the same transaction. Capture exact primary/responsive/cover output references and entity generation before metadata is removed. The lifecycle worker is the sole executor of production-object deletion. A cleanup event and a cleanup job must not become two independently authoritative queues: the durable job owns status; broker delivery is a wake-up signal.

The UI distinguishes **removed from catalog** from **storage cleanup pending/failed/completed**. NAS failure must not make deleted content reappear, and deleting a series must not claim bytes were removed before cleanup succeeds. Retry is idempotent and must verify that no current object reference or generation is being deleted. Broad recursive deletion of a series prefix is forbidden when it could include another operation's output.

Retain transactional outbox delivery and consumer receipts. A publisher appends an event with its state mutation; Outbox Relay publishes with confirmation and retries safely. Consumers deduplicate by event ID and apply ordering rules per aggregate revision. Notification acknowledgement/read fields and retention have separate declared permissions from notification creation.

Keep dependency failures local where possible:

| Failure | Required visible behavior |
| --- | --- |
| Social unavailable | Browse Catalog still displays; metrics/relationships are unavailable, not zero/false |
| Progress unavailable | Reader content remains usable; save shows pending/error and retains account-scoped intent |
| Catalog commit unavailable | Ingestion remains retryable/reconciling; outputs are preserved; no false published state |
| Broker unavailable | Accepted work stays in its PostgreSQL ledger/outbox; UI can distinguish queued dispatch delay |
| Realtime unavailable | HTTP refresh on reconnect/focus and bounded reconciliation recovers state |
| NAS unavailable | Affected delivery/ingestion/cleanup reports storage failure; unrelated authentication or local DB backup is not disabled |
| Cache unavailable | Domain reads use their canonical source subject to normal resource/backpressure limits |

Critical Valkey sessions can remain an authentication dependency. “Cache failure isolation” does not mean bypassing authorization when session validation is unavailable. The retained single PostgreSQL instance remains a shared failure domain; separate credentials and services do not make it highly available.

## 7. Web and Android state rules

Preserve the user-facing options documented in section 12. Consolidation changes where facts come from, not whether a user can bookmark, follow, read, review staged pages, or restore a database.

- Separate guest/not-applicable, loading, known, and unavailable states. Known relationship values may be true or false; network failure is neither.
- Keep last successful data only for the same account, origin, query key, and contract version, and label it stale after a failed refresh.
- Clear account-specific caches and cancel in-flight requests at logout/account switch. Unknown contract versions must not be interpreted as empty data.
- Serialize conflicting mutations per entity; use idempotency/revision guards. A pending optimistic indicator does not update canonical totals until acknowledgement.
- Public metrics are independent of personal-session lookup. Missing aggregate data is distinct from a valid zero count.
- Preserve separate series and chapter comment scopes, same-scope replies, own-comment deletion, realtime signals, and HTTP recovery.
- Keep username/email read-only and avatar editing. Only authoritative authentication rejection clears the session; network/5xx errors show temporary unavailability.
- Keep responsive cards, stable shelf geometry, page/reset behavior, bounded image caches, top/bottom reader navigation, and absence of chapter page-count labels in Android browsing surfaces.

### Android origin and Reader alignment

Use one build-configured application origin. Remove `base_url` and `image_cdn_url` preferences through an explicit one-time settings migration. Changing the actual origin invalidates origin-scoped cookies, grants, API caches, and protected caches; no credentials are forwarded to the old origin. An obsolete Quick Tunnel origin requires a correctly configured build, not an invisible fallback.

Normalize the origin once and construct API/reader/image routes through one adapter. The native protected-page adapter and WebView reader may remain different renderers, but both use the same current manifest, chapter-grant, progress, authentication, and error contracts. Keep the v4-native path and the explicitly supported WebView fallback; do not restore per-page tokens, direct arbitrary-CDN protected requests, or old codecs.

Expired/revoked grants are reauthorized by Reader. Already downloaded encoded bytes do not grant continuing authorization by themselves. Cache deletion on logout prevents the next account inheriting protected content. Prefetch remains bounded and does not generate history.

## 8. Database Protection

### 8.1 Ownership and host path

There is one protection module, one `database_operations` queue, one backup agent, one inventory, and one guarded restore engine. Retire the old Dashboard backup request path. The Dashboard keeps only a compact status and link to Database Protection.

Use `MREADER_DB_PROTECTION_ROOT`, resolved once by bootstrap from the actual host user's home and persisted explicitly. Never derive it from the backup container's home or the current ZIP extraction directory. Linux default is `<host-user-home>/.mreader/database-protection`; Windows/Git Bash uses the corresponding absolute Windows user-profile path with validated Docker bind-mount conversion. An explicit existing configuration takes precedence. If the intended host user cannot be resolved reliably, stop setup with a clear path requirement.

| Relative directory | Contents |
| --- | --- |
| `dumps/automatic/` | Verified automatic logical bundles |
| `dumps/manual/` | Verified manually requested bundles |
| `dumps/pre-upgrade/` | Required pre-migration safety bundles |
| `dumps/pre-restore/` | Required pre-cutover safety bundles |
| `snapshots/` | Verified physical PostgreSQL snapshot bundles |
| `state/` | Rebuildable inventory index, operation recovery journal, locks, and cutover markers |
| `staging/` | Incomplete captures and isolated drill/cutover scratch directories |

Mount that explicit host root in the existing Compose backup-agent container at `/mreader-db-protection`. Protect credentials and artifacts with restrictive permissions or equivalent Windows ACL validation. No whole-home mount, Docker socket, or arbitrary-host-file API is introduced.

The private HTTP facade can remain in the existing API deployment, but its code belongs to a separate protection module under canonical `/api/admin/database` routes. It must not depend on scraper staging/NAS readiness. The backup-agent container provides a narrowly authenticated internal read-only inventory/download interface; this resolves the Compose-host/Kubernetes path boundary without mounting the user's home in Scraper pods. No new independently deployed service is required. Mutation requests still go through the single database operation queue; the internal file interface cannot run arbitrary commands or create an alternate queue.

### 8.2 Backup completeness

Logical bundles contain a full custom-format dump of the configured MReader database, cluster globals, manifest, and checksums. Do not select only Catalog tables. Include all application tables, data, schema, sequences, constraints, and required large objects. Ownership/global metadata is captured for disaster recovery; routine application restore maps permissions to the current approved runtime roles instead of blindly restoring old privileged credentials.

`pg_dump` covers one database, not every database in a PostgreSQL cluster. The manifest must say `scope=mreader_database_plus_globals`, with the exact database identity. Inventory other non-template databases and flag them as outside this logical bundle; never label them backed up by implication. Physical snapshots cover the PostgreSQL cluster using `pg_basebackup` with required WAL, and record their actual scope. These distinctions follow the PostgreSQL 16 documentation for [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html), [pg_dumpall](https://www.postgresql.org/docs/16/app-pg-dumpall.html), and [pg_basebackup](https://www.postgresql.org/docs/16/app-pgbasebackup.html).

The supported deployment is the dedicated MReader PostgreSQL instance. Additional application databases must be brought into an explicitly expanded backup policy before “whole instance protected” can be displayed. The UI's guarded restore restores the configured MReader database, even when its source is a physical snapshot; full-cluster disaster recovery remains a separately documented operator action using the preserved snapshot/globals.

PostgreSQL backup is not a backup of SeaweedFS image bytes, Valkey sessions, or RabbitMQ queues. Before a restore is declared usable, validate Catalog object references against NAS read-only. Previously deleted media can be absent from an old database recovery point; that is a blocking missing-media report, not permission to invent paths or silently claim complete application recovery. This release does not silently extend NAS retention or introduce a second NAS backup system.

### 8.3 Capture, verification, and retention

Use a fresh operation-scoped staging directory; capture, verify checksums/format, then publish the immutable recovery bundle by atomic rename within the mounted filesystem where supported and verified. Record manifest schema version, opaque recovery ID, type/scope, database/cluster identity, PostgreSQL major, MReader version, migration state, timestamps, byte counts, digests, and verification/drill status. An incomplete or malformed manifest never defaults to verified.

Logical retention is **4 days**; snapshot retention is **2 days**, measured from capture completion in UTC. Scheduling timezone affects execution time, not retention arithmetic. Preserve the existing daily logical schedule and configured snapshot cadence initially; the compact UI reports the actual next run and coverage gap if a scheduled attempt fails.

Retention exceptions are explicit safety rules: never prune an active restore source, the current pre-restore/pre-upgrade safety point, or artifacts referenced by an unresolved cutover journal. Pins expire when the dependent operation is reconciled; they are not hidden permanent retention. If pruning would remove the last verified recovery point, retain it and show degraded protection until a replacement is verified. Disk-full conditions block new destructive operations, not trigger deletion of unrelated files.

### 8.4 Recovery catalog and UI

The agent discovers complete bundles within the configured directories at startup, after capture/pruning/import, and on explicit refresh. The inventory index is rebuildable; recovery manifests/artifacts are authoritative. Manual file replacement, disappearance, duplicate IDs, traversal, symlinks escaping the root, invalid checksums, and unsupported PostgreSQL majors must be detected and surfaced without exposing internal paths to the browser.

Use compact, paginated rows with type, creation time, size, version, verification state, and contextual actions. Backend capabilities determine whether Drill, Restore, and Download are enabled. A missing agent/database is unavailable, not “zero recovery points.” Keep advanced operation history collapsed by default. The browser receives opaque IDs, safe error codes, and correlation IDs, not NAS addresses, host filenames, shell commands, or raw secrets.

All new HTTP routes belong to the private admin plane, retain role/active-user checks and CSRF/origin protection, and reject public access. Legacy `/api/scraper/admin/backups` and `/api/scraper/admin/database/*` are retired after clients and gateway mappings move together; do not keep aliases that introduce another workflow.

### 8.5 One guarded restore engine

For a dump or snapshot selected by opaque ID:

1. Re-resolve and pin the selected verified artifact; validate database identity, schema/major support, free space, checksums, and archive safety.
2. Stage it in isolation. A snapshot is booted in an isolated matching-major PostgreSQL instance, validated, and converted into the common logical restore source. Reject unsupported external tablespaces and unsafe archive members.
3. Apply forward migrations and current grants to the isolated candidate. Validate data/FKs, protected-page metadata, expected row evidence, and NAS references. A drill stops here and cannot publish events, notify users, or mutate production storage.
4. Require exact confirmation tied to recovery ID, target installation, and restore mode. Acquire the restore lock; fence writes from APIs, workers, schedulers, and old connections. Fail closed if fencing cannot be established.
5. Create a fresh verified full pre-restore dump of the fenced database and persist the cutover journal outside the database being replaced.
6. Perform the guarded database-name cutover using the existing engine. The multiple rename/reconnection steps are **not assumed to be one atomic SQL operation**. Journal every phase and resolve interruptions deterministically.
7. Reconcile operation audit state, reset stale delivery/cache generations, validate the new live database, and record the terminal result before writes resume. Imported pending jobs/outbox records do not automatically replay pre-restore side effects.
8. If validation fails, roll back using the retained database/safety point. Preserve ambiguous state and require operator intervention rather than guessing. Release pins and clean only proven operation-owned scratch artifacts after reconciliation.

Existing `database_operations` is the normal queue/status authority. The host cutover journal records only the critical recovery protocol needed when that database is offline/replaced; it is not another ordinary-operation scheduler. The agent reconciles it before accepting new destructive operations.

Restore changes the deployment's state generation: clear/invalidate only MReader-owned sessions, progress caches, grants, queues, and derived delivery state that could replay pre-restore actions. Fence old workers and ignore old-generation messages. Do not flush shared Redis instances or unrelated RabbitMQ queues. The operator CLI uses this same engine for recovery when the web/API cannot start; it does not implement a second restore algorithm.

## 9. Migration and retirement

### 9.1 Upgrade ordering and continuity

Resolve and preserve the existing installation configuration before adoption. r5's legacy-first behavior is an explicit recovery policy, not a promise that the legacy volume always has the newest data. An operator's established custom/authoritative selection wins; select once, validate PostgreSQL major compatibility, record the choice, and do not merge PGDATA volumes or silently switch them on every startup. A populated unsupported-major volume must not be opened by an incompatible database image or ignored as “empty.”

The controlled upgrade sequence is: resolve identity and source volumes; quiesce old writers/consumers; create and verify a local safety recovery point; capture legacy reading evidence; apply migrations under one migration lock; validate invariants and permissions; start current services; then resume work. When existing application data is present, a failed mandatory safety capture blocks destructive schema steps even if normal automatic backups are disabled.

Preserve already-shipped migration identities. The current migration runner records filenames, so a newly numbered late migration cannot rescue data that an earlier pending migration deletes first. Add an explicitly ordered, idempotent preservation step before 047/048 can run on an old database, plus a forward repair for already-upgraded databases. Test this ordering using the actual runner, including fresh installs and partially applied migration ledgers; do not rely on edited old migration files being rerun.

### 9.2 Reading evidence rules

- Import the old last-open chapter and independently preserve the furthest chapter before deleting `reading_history`.
- Use a checkpoint's page/scroll/completion only when its user, series, **and chapter** match the history evidence being migrated.
- Backfill canonical ledger evidence from valid surviving checkpoints during the one-time repair. Normal runtime never treats a missing ledger as permission to fabricate History from another table.
- Label inferred furthest-only evidence as migrated reach, not an exact open/completion event. It affects furthest position but must not manufacture Recently Opened timing or exact read markers.
- Actual exact ledger evidence wins over inferred migration data. Keep valid timestamps and make ties deterministic; do not invent a later activity date to force ordering.
- If earlier installed migrations already destroyed the only evidence, recover it from a selected, verified backup into isolated staging. Without that evidence, report the unrecoverable detail; neither client merge nor a migration can reconstruct it honestly.
- Only remove the legacy table when counts, identity links, last-open targets, furthest preservation, and completion invariants have passed in the migration transaction.

### 9.3 Existing table disposition

| Existing table(s) | Decision |
| --- | --- |
| `users` | Keep; Auth owner |
| `series`, `chapters`, `pages` | Keep; remove non-Catalog production writers |
| `genres`, `series_genres`, `tags`, `series_tags` | Keep; Catalog taxonomy |
| `editor_picks`, `announcements` | Keep; Catalog curation |
| `reading_progress`, `chapter_reads` | Keep; Progress facts plus required revision/provenance fields |
| historical `reading_history` | Migrate available evidence once, then remove; no runtime compatibility reads |
| `bookmarks`, `subscriptions`, `series_ratings`, `comments` | Keep; distinct Social capabilities |
| `notifications`, `notification_event_receipts` | Keep; distinguish creation/read-state/retention permissions |
| `series_trending_hourly` | Keep as derived Trending data, not personal history |
| `event_outbox` | Keep; one delivery protocol with explicit producer/delivery permissions |
| `media_operations` | Keep transformation task detail; not an independent publish-success owner |
| `lifecycle_cleanup_jobs` | Keep durable cleanup queue/status |
| `scraper_drafts`, `scraper_series_drafts`, `scraper_series_draft_chapters` | Keep editable workflow detail; link to canonical ingestion header |
| `scraper_batch_uploads`, `scraper_batch_items` | Keep batch/group/item detail and conflict resolution |
| `scraper_operation_events` | Keep audit/events; normalize operation links, not another status owner |
| `scraper_staging_spool_registry` | Keep canonical staging identity safeguard |
| `scraper_storage_attempts` | Keep ownership/ambiguous-commit cleanup evidence |
| `scraper_history` | Migrate useful history into ingestion operation/audit records, verify counts and provenance, then retire API/table |
| `backup_requests` | Reconcile/migrate into `database_operations` preserving IDs/status/audit links, then retire API/table |
| `database_operations`, `database_protection_runtime` | Keep; protection operation queue and agent capabilities |
| `schema_migrations` | Keep; serialized migration authority |

Only two new persistent business-support tables are authorized by this design: `ingestion_operations` and `catalog_mutation_receipts`. The reading view and recovery inventory are derived. Further tables require a documented fact/owner/lifecycle justification, not “just in case” expansion.

Legacy queued/running backup or scraper records are reconciled against actual artifacts/commit evidence before migration. Completed work is not requeued. Uncertain work receives an explicit recovery-required result. Old NAS recovery bundles are copied through an explicit one-time import that verifies checksums and records new local manifests; original NAS artifacts are not automatically deleted. Normal DB Protection no longer scans both storage locations as parallel authorities.

## 10. API, event, and diagnostics contracts

Add a machine-readable ownership/route manifest under `contracts/` covering operation ID, method/path, access plane, domain owner, handler, request/response version, authentication, allowed writers, dependencies, event effects, client consumers, and acceptance-test IDs.

Maintain versioned response schemas and representative fixtures for reading, Library, social viewer state, ingestion operation state, publication receipts, and recovery catalog/actions. Keep the existing session/event schema registry and extend it where the design requires revisions and restore-generation fencing. Domain errors include safe `code`, `request_id`, optional `operation_id`, and retryability; raw SQL, tokens, and storage paths stay out of client responses.

Contract checks compare declared routes with registered service routes, gateway policies, and Web/Android adapters. Removed routes are tested to reject rather than map to an unintended catch-all. A source string appearing in a file is not evidence that a request is routed or executed correctly.

Logs correlate request ID, operation ID, domain/phase, aggregate revision, retry attempt, duration, and error code. Measure stale-command rejections, unsaved Progress requests, outbox lag, dead-letter work, unknown publication outcomes, stalled cancellations, cleanup failures, and protection age/drill failures. Reuse existing structured logging and monitoring; no new observability stack is introduced. Errors in optional add-ons identify their owner without corrupting unrelated screen state.

README and deployment/ownership/test docs must reflect major changes. No Git hook is added that rejects every code change unless documentation changes alongside it.

## 11. Verification and release gates

Every test below has an explicit owner and expected result. Use disposable PostgreSQL, cache/broker fixtures, and isolated media/backup locations. A real restore drill must run the actual PostgreSQL tools; mocked shell output does not prove it works.

| Gate | Acceptance evidence |
| --- | --- |
| BASE-01 | Record source hashes and a capability-oriented r2/r5 merge ledger; original archives unchanged |
| OWN-01 | Registry covers every existing table and allowed write operation; forbidden writes fail using each runtime role, including ORM calls |
| API-01 | Registered handlers, both gateways, frontend adapter, and Android adapter agree on method/path/schema/access; internal/admin routes denied publicly |
| READ-01 | Open chapter 2, commit its checkpoint, then reopen chapter 1: resume/last-open become chapter 1, furthest stays chapter 2, no invented earlier read markers |
| READ-02 | Successful save followed immediately by Progress state, Browse, and Library reads returns consistent PostgreSQL state without waiting for Redis flusher/cache expiry |
| READ-03 | Duplicate, reordered, concurrent-device, stale-session, timeout/retry, and account-switch commands cannot overwrite newer resume state or duplicate completion |
| READ-04 | Last page merely becoming visible is not a fabricated completion; end-of-chapter evidence and one-page/very-tall-page cases use the same semantics on Web/Android |
| LOCAL-01 | Reader/Continue/affected Library card update immediately without network response; refresh restores the pending checkpoint and visibly distinguishes it from confirmed server state |
| LOCAL-02 | Offline reading across chapters, retry/redelivery, two tabs, acknowledgement racing a newer checkpoint, storage/quota failure, process exit, logout, and account/origin changes preserve ordering/privacy without losing queued intent silently |
| LOCAL-03 | Dirty checkpoint coalescing obeys local/network bounds; last-open/completion intents survive compaction; Beacon acceptance cannot clear unsynced state; other devices converge after actual acknowledgement |
| LIB-01 | Items, summary, total, recent rail, action targets, and pagination agree for all scopes/states/sorts; SQL empty/error responses cannot become false zero-success |
| UI-01 | Slow/out-of-order fetches, navigation, filter changes, logout/login, offline/reconnect, double clicks, and optional-service outages do not leak or corrupt state |
| AND-01 | Upgrade with saved obsolete gateway/CDN preferences removes them, uses one configured origin, isolates cookies/caches, and passes real Kotlin compilation/unit tests |
| PUB-01 | Manual ZIP/CBZ/PDF inputs supported by the existing workflow, optional boundary pages, existing/new-series scrape, and batch paths produce identical valid Catalog/Reader contracts |
| PUB-02 | Duplicate delivery, same-key/different-body conflict, two concurrent publishers, stale overwrite revision, and response loss produce one authoritative Catalog result and intended notification effect |
| ING-01 | Worker restart, scaling, expired lease, URL-source repair, missing manual file, cancel-versus-publish race, review, retry, acknowledge, and refresh recover from durable state |
| DEL-01 | Series/chapter deletion removes appropriate metadata and separately completes exact owned-object cleanup; outage/retry cannot delete replacement output or published content on scrape cancel |
| MIG-01 | RC4.81, each supplied RC4.84 variant, partial migrations, and fresh install converge using the actual runner; preserve last-open/furthest/checkpoint evidence and enforce grants |
| MIG-02 | Already-lost history is reported or recovered only from supplied verified evidence; completed backup/scrape operations are not replayed; old runtime tables/routes are absent |
| PATH-01 | Linux and Windows paths with spaces, explicit overrides, fresh environment, old configuration, invalid/missing mounts, and repeated bootstrap resolve one stable authority |
| DBP-01 | Actual full MReader dump plus globals and actual physical snapshot land under the host root; incomplete bundles stay unverified; 4/2-day retention and safety pins are exercised |
| DBP-02 | Agent discovery, paging, opaque ID resolution, authenticated downloads, missing/tampered artifacts, unsupported majors, archive traversal, and stale capabilities return safe deterministic responses |
| DBP-03 | Dump and snapshot drill restore data in isolation, run migrations/grants, validate references, and generate no production messages or media writes |
| DBP-04 | Isolated production-restore rehearsal fences writers and injects interruption before/after each rename/journal stage; recovers or rolls back without stale worker/event replay |
| PERF-01 | Library query plans restrict work to the requested user/series; caches/pools/queues/payloads remain bounded; no new per-scroll request pattern or increased resource limit |
| REL-01 | Current-release validator finishes; real Web/Social/Go/Python tests/builds and Android compile/tests run; exact commands, outputs, skips, and environment blockers are recorded |

Static checks and runtime tests have separate result categories. If Docker, Android tooling, NAS access, or a relevant dependency is unavailable, record the affected gate as **not run/blocked**, never passed. No unqualified “everything works” statement or verified-release ZIP is justified by skipped critical gates.

## 12. Capability checklist to preserve

| Surface | Required capabilities |
| --- | --- |
| Browse/Search | Title suggestions, URL-persisted advanced filters with existing matching semantics, Surprise Me, curation/announcements, Trending windows, latest/popular/new shelves, Continue Reading, public metrics, stable pagination |
| Series Detail | Metadata/taxonomy, start/continue, published chapter list and number filtering, exact read markers, bookmark/follow/rate, series comments, responsive layout |
| Reader | Current protected content, bounded prefetch/cache, resume, top/bottom previous/next, chapter navigation, completion handling, chapter comments, Library/Series return actions |
| Library | All/Bookmarks/Subscriptions/History, Updates/Caught up/Not started, all current sort choices, truthful counts/actions, Recently Opened |
| Account/Alerts | Login/signup/logout, avatar selection, locked username/email, admin indication, notifications/read-one/read-all/unread count and HTTP reconciliation |
| Admin content | Manual series creation/edit/status/tags/cover, manual upload and boundary pages, published-content deletion, export/download and cleanup retry |
| Admin ingestion | Existing-series and new-series discovery/staging, metadata/cover/page editing, reordering/add/remove/replace, chapter selection, individual/bulk publication, batch conflict resolution, progress/retry/cancel/acknowledge |
| Admin curation | Editor Picks and announcements with ordering, activation, scheduling, links, and dismissal behavior |
| Database Protection | One compact recovery catalog, logical/snapshot capture, download, drill, confirmed restore, operation status/history, correct host paths and retention |

Feature absence in a later archive is not approval to remove it. Conversely, an old API with no retained capability is not automatically protected simply because it once existed.

## 13. Delivery decomposition and review boundary

The implementation plan will break this specification into sequentially integrated work packages:

1. Baseline provenance, executable capability fixtures, ownership registry, and upgrade preservation prerequisites.
2. Progress persistence/view and Web/Android Library/state alignment.
3. Host-path DB Protection inventory, queue retirement, and restore/fencing verification.
4. Catalog publication authority, ingestion header, media/lifecycle integration, and legacy workflow retirement.
5. Cross-plane/client contracts, constrained resource testing, full migration/restart rehearsals, documentation, and release packaging.

Database protection/preservation is established before destructive retirement. Domain credentials become restrictive only as their replacement command paths pass tests. Mixed-version mutation services are not permitted during the final maintenance-window cutover. Work-package success does not qualify an incomplete combined release.

The final package must include current source, migrations, contracts, focused documentation, deployment/teardown entry points, and essential tests; exclude credentials, dependency caches, old release packages, generated runtime state, and superseded launchers. Generate checksums from the exact qualified source. Update the release/version references together, including Android build code. Preserve original uploaded artifacts as the audit baseline.

This specification was self-reviewed for ownership conflicts, source provenance, migration ordering, restore scope, path alignment, and testability. Approval of the written specification authorizes the next implementation-planning step; it does not imply that any runtime gate above has already passed.

## Appendix A — source archive provenance

| Uploaded filename | SHA-256 |
| --- | --- |
| `mreader-rc481-history-public-metrics-reliability(6).zip` | `1188d087c7335bb0cda45218ff474fe8b6dc2751d67775ecac6c14deb41b65fb` |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r2(1).zip` | `98aca244ba406b46c04392763bf2b9ff16a0714988f0ab411bd92c11f4921de7` |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r4(1).zip` | `fe302f271e3929b78f89f0577d8eab366c943a8fa24ab0556fd7b269c3dff27e` |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r5(1).zip` | `ab48e524e80c803913a992a3c46f2e936a4bcf238c43ada3975de79227885376` |

Repository-relative paths in this document refer to the r5 starting tree unless another source is named. Planned paths, tables, fields, and contracts are requirements for RC4.85, not claims that they already exist.
