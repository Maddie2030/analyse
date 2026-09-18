# RC4.85 Sequential Review — PostgreSQL Table Disposition

This is the P01.4 table-by-table inventory. It distinguishes desired canonical owner from **current source-observed writers**. A desired owner label is not evidence that competing code has already been removed. Direct SQL inspection is supplemented with ORM/Prisma inspection so a text-only SQL search is not used as proof of writer absence.

Migration/init inspection through migration 060 now finds 39 shipped `CREATE TABLE` identities, with `backup_requests` subsequently dropped by migration 050. Historical `reading_history` is also explicitly dropped by migrations 047/048. The effective current sequential set is 38 tables, plus those two retired/historical identities documented below. P01 originally audited the Milestone-1 baseline; this inventory is kept current as authorized support tables and technical recovery-control state are introduced.

| Table | Canonical owner / role | Current source-observed readers/writers | RC4.85 disposition |
| --- | --- | --- | --- |
| `users` | Auth | **Writer:** `services/auth_service/app/infrastructure/user_repository.py` via SQLAlchemy `User` ORM. Readers include Auth plus Social/Progress/Realtime authorization/profile joins. | Keep. Auth mutation authority; other domains read declared identity/session facts only. |
| `genres` | Catalog taxonomy | **Competing writer:** `services/scraper_service/app/series_drafts.py`; Catalog reads/owns taxonomy in `services/catalog_go/internal/store/store.go`. | Keep; P06.4 must route new-series taxonomy mutation through Catalog. |
| `series` | Catalog | **Writers today:** `services/catalog_go/internal/store/store.go`; **Competing writer** `services/scraper_service/app/series_drafts.py`; Media ORM in `services/image_service/app/services/chapter_ingestion.py` mutates `series.updated_at`. Many domains read. | Keep; remove non-Catalog production mutation during P06. |
| `series_genres` | Catalog taxonomy | Catalog writer plus **Competing writer** `services/scraper_service/app/series_drafts.py`. | Keep; P06.4 cutover. |
| `tags` | Catalog taxonomy | Catalog writer plus **Competing writer** `services/scraper_service/app/series_drafts.py`. | Keep; P06.4 cutover. |
| `series_tags` | Catalog taxonomy | Catalog writer plus **Competing writer** `services/scraper_service/app/series_drafts.py`. | Keep; P06.4 cutover. |
| `chapters` | Catalog | **Writer:** `services/catalog_go/internal/store/store.go`; **Competing writer:** `services/scraper_service/app/publication.py`; **Competing ORM writer:** `services/image_service/app/services/chapter_ingestion.py`. Reader, Progress, Social and Media read. | Keep; central P06 blocker. Catalog becomes sole production metadata writer. |
| `pages` | Catalog | **Competing writer:** `services/scraper_service/app/publication.py`; **Competing ORM writer:** `services/image_service/app/services/chapter_ingestion.py`; Reader/Media/Catalog read. | Keep; page commit must move behind Catalog publication command/receipt transaction in P06. |
| `reading_progress` | Progress | Writer paths `services/progress_go/internal/store/commands.go` and legacy-compatible store implementation in `internal/store/store.go`; Social/clients consume Progress-owned projection rather than write. | Keep; P02/P05 verify one atomic command owner and remove obsolete write mechanisms. |
| `chapter_reads` | Progress | Writer paths in `services/progress_go/internal/store/commands.go`/`store.go`. | Keep exact chapter evidence; P02/P05 verify ordering/provenance. |
| `series_trending_hourly` | Derived Trending | Writer `services/reader_go/internal/analytics/tracker.go`; Catalog reads. | Keep as explicitly derived aggregate, never personal reading history. |
| `editor_picks` | Catalog curation | Writer `services/catalog_go/internal/store/store.go`. | Keep. |
| `announcements` | Catalog curation | Writer `services/catalog_go/internal/store/store.go`. | Keep. |
| `bookmarks` | Social | Prisma writer `services/social_ts/src/routes.ts` (`bookmark.create/delete`); Catalog/notification paths may read for projection/notification purposes. | Keep; Social command owner. |
| `subscriptions` | Social | Prisma writer `services/social_ts/src/routes.ts` (`subscription.create/delete`); notification/realtime consumers read. | Keep; Social command owner. |
| `notifications` | Notification creation + Social read-state exception | Notification Worker inserts in `services/notification_worker/internal/store/store.go`; Social mutates `is_read` in `services/social_ts/src/routes.ts`; Social maintenance prunes under scoped responsibility. | Keep with column/operation-specific grants; creation and read-state ownership must remain distinguishable. |
| `comments` | Social | Prisma `comment.create/delete` in `services/social_ts/src/routes.ts`; realtime observes/signals. | Keep series/chapter scoped comments and reply/delete rules. |
| `lifecycle_cleanup_jobs` | Lifecycle durable cleanup queue/status | Producers currently include Catalog `internal/store/store.go` and Scraper `batch_queue.py`/`storage_attempts.py`; Lifecycle implementation `services/image_service/app/lifecycle_worker.py` executes/updates/deletes; admin retry route in `app/routers/lifecycle.py`. | Keep. Producers may enqueue through defined transactional contract; Lifecycle alone performs production-object deletion. P07 validates generations and legacy jobs. |
| `ingestion_operations` | Scraper ingestion coordinator overall operation/fence authority | Migration 055 introduces the canonical operation header. Catalog P06.3 reads/locks actor, source revision, lease generation and cancellation state before a new publication commit; entry-point writers are still P07 work. | Keep. P06.3 prerequisite only establishes the authority record; P07 must wire manual/batch/existing/new-series coordinators, lease transitions, status/counts and acknowledgement semantics. |
| `scraper_history` | Legacy Scraper workflow history | Writer/reader `services/scraper_service/app/storage.py`; API still exposed. | Keep temporarily for migration/reconciliation; P07/P05.6 must migrate useful provenance then retire table/API without replaying completed work. |
| `scraper_drafts` | Scraper workflow detail | `services/scraper_service/app/drafts.py`, `storage_attempts.py`; Catalog/Media may read target/detail context. | Keep editable existing-series workflow detail; later link to `ingestion_operations`. |
| `scraper_batch_uploads` | Scraper batch detail | `services/scraper_service/app/batch_queue.py`, `storage_attempts.py`. | Keep batch/group state; overall lifecycle later derives from `ingestion_operations`. |
| `scraper_batch_items` | Scraper batch item detail | `services/scraper_service/app/batch_queue.py`, `storage_attempts.py`; Media/Catalog inspect where required. | Keep conflict/item detail. |
| `scraper_series_drafts` | Scraper new-series workflow detail | `services/scraper_service/app/series_drafts.py`, `storage_attempts.py`; Media/Catalog inspect context. | Keep editable detail; production Catalog writes must be removed from this workflow in P06. |
| `scraper_series_draft_chapters` | Scraper chapter workflow detail | `services/scraper_service/app/series_drafts.py`, `storage_attempts.py`; Media/Catalog inspect context. | Keep; subordinate to future ingestion header. |
| `scraper_staging_spool_registry` | Scraper staging identity safeguard | Scraper `staging_store.py`; Lifecycle worker also records/validates spool identity. | Keep as storage identity safeguard, not overall ingestion status. P07 validates ownership/fence semantics. |
| `scraper_storage_attempts` | Scraper storage/ambiguous-outcome evidence | Scraper `storage_attempts.py`/`batch_queue.py`; Lifecycle worker reads/updates reconciliation state. | Keep; P07 formalizes exact object ownership, ambiguous outcomes and cleanup handoff. |
| `schema_migrations` | Migration role | Migration scripts/diagnostics only; runtime services must not become schema writers. | Keep serialized migration authority. |
| `series_ratings` | Social | Prisma `seriesRating.upsert/deleteMany` in `services/social_ts/src/routes.ts`; Catalog may read aggregate projection. | Keep; Social owner. |
| `event_outbox` | Domain transaction append + Outbox Relay delivery fields | Domain-specific event helpers append alongside mutations; `services/outbox_relay/internal/outbox/store.go` claims/updates delivery state. Diagnostics/tests read. | Keep one delivery protocol; P09 grants distinguish producer append from relay delivery mutation. |
| `media_operations` | Media transformation task/evidence | Writer `services/image_service/app/media_operations.py`; workers/routers use it. | Keep. P06.3 extends durable immutable completion evidence; it must not become publication authority. |
| `catalog_mutation_receipts` | Catalog durable mutation/idempotency evidence | Writer/read-replay boundary `services/catalog_go/internal/store/publication.go`; created by migration 054. | Keep as Catalog-owned receipt authority. It is not ingestion status and survives later Catalog entity deletion. |
| `notification_event_receipts` | Notification Worker dedupe | `services/notification_worker/internal/store/store.go`. | Keep event idempotency evidence. |
| `scraper_operation_events` | Scraper audit/events | Writer `services/scraper_service/app/operation_events.py`. | Keep audit trail; link to canonical operation header later, never a second overall status owner. |
| `database_operations` | Protection operation queue/status | API facade `services/scraper_service/app/database_protection.py`; host backup agent `scripts/backup/backup-agent.sh` claims/updates/recovers operations. | Keep as the one normal DB Protection queue. |
| `database_protection_runtime` | Protection runtime capability/state | Backup agent writes; facade reads. | Keep runtime capability state; P08/P09 narrow transport and credentials. |
| `database_recovery_points` | Rebuildable recovery inventory projection | Writer `scripts/backup/sync-local-recovery-catalog.sh`; reader `services/scraper_service/app/local_recovery_catalog.py`. | Keep as rebuildable projection of host manifests, not backup-byte authority. P08 later aligns private facade/download and inventory refresh semantics. |
| `database_restore_state` | DB Protection committed restore-generation mirror | Writer `scripts/backup/backup-agent.sh` after validated cutover/reconciliation; schema migration 060 seeds the singleton. Runtime readers use the host-owned restore control as the offline authority and PostgreSQL only as the post-cutover mirror. | Keep as singleton technical fencing state. It is not a business-operation queue or backup-byte authority; the host control/journal remains authoritative while PostgreSQL is offline/replaced. |
| `backup_requests` | Retired legacy DB Protection queue | Historical migrations 036/037; migration 050 migrates rows into `database_operations` then `DROP TABLE backup_requests`; `services/scraper_service/app/backup_requests.py` is absent and regression checks enforce absence. | **Retired.** Reconcile historical terminal/uncertain work before release qualification; never restore as a normal runtime queue. |
| `reading_history` | Retired legacy reading history | Historical upgrade evidence only; migrations 047/048 `DROP TABLE IF EXISTS reading_history`. | **Retired after one-time preservation.** Normal runtime must use Progress-owned `reading_progress`, `chapter_reads`, and `reading_state_v1`; P05 proves preservation on old databases. |

## New RC4.85 table allowance

The approved design permits only two additional persistent business-support tables beyond the current baseline:

- `catalog_mutation_receipts` — Catalog-owned durable idempotency/publication result evidence (P06).
- `ingestion_operations` — Scraper ingestion coordinator-owned overall operation header (P07).

Both authorized support tables are now present in the sequential source: `catalog_mutation_receipts` via migration 054 and `ingestion_operations` via migration 055. This does not mean P07 is complete: only the canonical ingestion authority header has been pulled forward as a P06.3 prerequisite; coordinator entry-point wiring and lease/cancellation lifecycle behavior remain P07.

The P08.8 `database_restore_state` singleton is a technical post-cutover mirror of host-owned restore fencing state, not an additional business-support table or competing recovery authority. Its fact is limited to the committed installation fingerprint/generation/source operation after a validated restore cutover.

## Writer conflicts requiring later removal

The source audit confirms P06 is a real architectural change rather than documentation cleanup:

- `services/scraper_service/app/publication.py` directly mutates production `series`/`chapters`/`pages` paths.
- `services/scraper_service/app/series_drafts.py` directly creates/updates production series/taxonomy relationships.
- `services/image_service/app/services/chapter_ingestion.py` creates `Chapter`/`Page` ORM rows and updates the `Series` ORM object.
- `services/catalog_go/internal/store/store.go` already owns Catalog admin/publication mutations and transaction/outbox logic.

P06 must replace the competing writers through one Catalog command implementation before restrictive P09 grants can be enforced.
