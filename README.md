# MReader v1.3.0-rc4.84

MReader is a manga/manhwa platform with a React web client, native Android client, protected v4 chapter delivery, scraper/admin workflows, durable media processing, Progress/History, Smart Library/social features, realtime notifications, and NAS-backed published media.

RC4.84 keeps the cleaner RC4.83 runtime ownership model but repairs upgrade/data continuity. Historical compatibility now lives in **one-time adoption and recovery tooling**, not in normal request paths.

This checkout also contains the **RC4.85 ownership-consolidation work in progress**. Start with [00-START-HERE.md](00-START-HERE.md) for the current source test milestone. The [approved design](docs/superpowers/specs/2026-09-11-mreader-rc485-ownership-consolidation-design.md) and [reading command contract](contracts/reading/v1/README.md) describe the changes. The new Progress protocol requires matched clients and migrations through 052 using the shared migration runner. The user has authorized application source packages at major blocker milestones; these are test checkpoints. A qualified release still requires actual PostgreSQL migration/restore, client builds and the remaining ownership gates.

## Canonical working topology

- **Windows 10/11 + Docker Desktop + Git Bash** on the application host.
- **Docker Desktop Kubernetes** for stateless user/admin services and workers.
- **Docker Compose** (`deploy/compose/docker-compose.hybrid-stateful.yml`) for PostgreSQL, critical/cache Valkey, RabbitMQ, Image Edge and PostgreSQL backup tooling.
- **External NAS SeaweedFS** for published covers/pages/chapters.
- **Host-local PostgreSQL recovery** under the resolved user's `~/.mreader/database-protection`, with dedicated dump, snapshot, state, and staging directories. Logical dumps retain four days and physical snapshots two days; the backup container uses an explicit host bind mount.
- **KEDA + HPA** for bounded autoscaling.
- User gateway: `127.0.0.1:8080`.
- Admin gateway: `127.0.0.1:8081`, local/private.
- Optional public-development user edge: Tailscale Funnel and/or Cloudflare Quick Tunnel.

No full-stack Compose, Helm, platform/multicloud or generic-gateway runtime is supported in RC4.84.

## First start / upgrade start

```bash
cp .env.example .env      # only for a genuinely new install
kubectl config use-context docker-desktop
./scripts/bootstrap.sh
./hybrid-up.sh
```

RC4.85 resumes database-using workloads through one fail-closed sequence: quiesce writers/autoscalers, capture the pre-upgrade safety point, migrate, reconcile the P09.3 PostgreSQL role contract, pass the P09.4 schema/grant/credential/restore-generation readiness gate, apply generation-stamped workload templates, prove rollout, and only then restore HPA/KEDA. A production database restore first completes the P08.8 fenced restore/generation commit and then rejoins this same hybrid deploy sequence; the restore script no longer owns a second direct `kubectl apply` path.

The real permission/readiness runtime gates are explicit qualification commands, not ordinary startup shortcuts. `scripts/test/p09-3-postgres-grants-gate.sh` uses a disposable PostgreSQL target. `scripts/test/p09-4-runtime-gate.sh` requires `MREADER_P09_4_RUNTIME_CONFIRM=current-hybrid` and the actual pre-restore generation in `MREADER_P09_4_EXPECT_PREVIOUS_GENERATION`; it never advances restore generation itself. Missing Docker/Kubernetes/PostgreSQL prerequisites or missing authorized N→N+1 evidence produce exit 2 (**BLOCKED**), which is not PASS.

For an extracted upgrade beside an older release, `hybrid-up.sh` can reuse the previous `.env`. Before Compose starts PostgreSQL, `scripts/hybrid/adopt-existing-stateful-volumes.sh` records the authoritative durable volume names in `.env`.

### Stateful volume continuity

Fresh installs use:

- `mreader_pgdata`
- `mreader_redis_data`
- `mreader_rabbitmq_data`
- `mreader_image_cache`

Older Compose releases may have created names such as `mreader-hybrid-stateful_pgdata`. RC4.84 does **not** keep both names active at runtime. The adoption helper selects one name once and persists it as `HYBRID_*_VOLUME_NAME` in `.env`.

An explicit configured volume selection is preserved. Without one, the adoption helper performs a structural PGDATA probe and prefers populated legacy `mreader-hybrid-stateful_*` volumes under the configured legacy-first policy. It does not automatically compare catalog contents or merge volumes. Critical Redis, RabbitMQ and image-cache legacy volumes are also preferred when populated. Set `MREADER_PREFER_LEGACY_STATEFUL_VOLUMES=false` only when deliberately selecting canonical volumes. `./scripts/hybrid/inspect-postgres-volumes.sh` is the separate clone-based inspection tool. PostgreSQL-major and full upgrade rehearsals remain qualification gates.

PostgreSQL recovery uses `MREADER_DB_PROTECTION_ROOT`, not a named backup-spool volume. Automatic adoption no longer probes or selects old backup spools; they remain available for deliberate recovery/import inspection. See the [current protection guide](docs/operations/POSTGRES_BACKUP_AND_RESTORE.md) for path and one-time retention configuration.

## Existing NAS library recovery

Published NAS objects are only useful when PostgreSQL still has the matching:

```text
series -> chapters -> pages
                    ├── image_path
                    ├── responsive_image_path
                    ├── encoding_version = 4
                    ├── encoding_rows / encoding_columns
                    └── encoding_seed
```

RC4.84 therefore ships a permanent **catalog-only recovery subsystem** for disaster recovery from historical backups without restoring obsolete runtime state.

Supported recovery inputs for the `catalog-v4-v1` contract:

- PostgreSQL custom-format `.dump` backups.
- MReader physical snapshot `.tar` backups containing `base.tar.gz` and `pg_wal.tar.gz`.

Check a backup without changing current PostgreSQL:

```bash
./scripts/recovery/catalog-restore.sh --source /path/to/mreader.dump --check
```

Import after a successful check:

```bash
./scripts/recovery/catalog-restore.sh --source /path/to/mreader.dump --import
```

Only these donor tables are imported:

- `series`
- `chapters`
- `pages`
- `genres`
- `series_genres`
- `tags`
- `series_tags`

Users, bookmarks, subscriptions, ratings, comments, reading state, notifications, scraper jobs, Media jobs, Redis and RabbitMQ state are **not** imported.

NAS SeaweedFS is read-only during recovery. Primary page objects must exist before import. Existing paths and encoding seeds are preserved exactly. Import requires an empty target catalog, creates a full pre-import PostgreSQL safety backup, and commits the seven-table catalog atomically.

See `docs/recovery/CATALOG_RECOVERY.md`.

## Canonical data ownership

- **PostgreSQL** — durable relational truth.
- **`reading_progress`** — current resume/checkpoint per user+series.
- **`chapter_reads`** — durable exact chapter read/history/completion ledger.
- **Critical Valkey** — sessions and non-evictable coordination. Progress stream processing is confined to the explicit maintenance drain.
- **Cache Valkey** — derived caches and Reader chapter grants (`imgtoken:*`). Lifecycle revokes grants from this same cache owner.
- **RabbitMQ** — work/event transport, not durable job truth.
- **`media_operations`** — durable Media job status.
- **Kubernetes `scraper-staging` PVC** — unpublished scraper bytes referenced by current scraper state.
- **NAS SeaweedFS** — published media.
- **Host recovery root** — PostgreSQL dumps, snapshots, verified manifests, and recovery journal.

## Reader/image contract

- Manifest: `/api/reader/{seriesSlug}/{chapterSlug}`.
- One chapter-scoped grant authorizes primary and responsive page objects.
- Grant refresh: `/api/token/chapter/{seriesSlug}/{chapterSlug}`.
- Protected published pages are encoding **v4 only**.
- Web decodes protected bytes client-side.
- Android native Reader fetches still-encoded bytes only through `/api/mobile/v1/reader/.../page/{pageNumber}` and decodes locally.
- WebReader remains an explicit user-visible fallback, not a hidden transport fallback.

## API consolidation in RC4.84

Proven dead aliases were removed while end functionality is preserved:

- removed Catalog `/api/catalog/dashboard`; `/api/catalog/discover` is canonical;
- removed Progress `PUT /api/progress/{series}/{chapter}`; `/commit` is canonical;
- removed scraper `publish-status`; `workflow-status` is canonical;
- removed Realtime `/ws`; `/api/realtime/ws` is canonical.

The generic scraper/existing-series/batch/new-series workflows and synchronous/asynchronous thumbnail paths are **not** aggressively removed in RC4.84; they still represent product capabilities or require a separate behavior-level consolidation pass.

## Progress, History and Smart Library

Progress owns one PostgreSQL command transaction for accepted opens/checkpoints, exact chapter evidence, and outbox events. Server session generations and command sequences fence delayed requests. The live `reading_state_v1` view feeds History, Series state, and the single Smart Library query. Pending client state accelerates rendering while clearly remaining unsynced. See the [reading contract](contracts/reading/v1/README.md) and its runtime acceptance tests; the RC4.85 branch is still awaiting full qualification.

Migration `048_rc483_current_baseline.sql` remains immutable historical upgrade provenance: it backfills any surviving `reading_history` rows into `chapter_reads`, drops the transition table, and removes the old notification-kind default.

## Scraper, Media and Lifecycle

- Scraper requires the current schema at startup.
- PostgreSQL-referenced unpublished files must exist on the current staging PVC; runtime does not reconstruct missing staged files from old source URLs/spools.
- Media job status is PostgreSQL-only (`media_operations`).
- Lifecycle distinguishes local staging cleanup from NAS published-object cleanup.
- Reader grant revocation uses explicit cache Redis ownership.

## Android

The app remains **Mreader**, visible version **ver.1.1.0**, build code **484**.

```bash
./build-android-apk.sh
```

Output:

```text
dist/Mreader-ver.1.1.0-debug.apk
```

## Operator commands

```bash
./hybrid-up.sh
./scripts/hybrid/status.sh
./scripts/hybrid/logs.sh
./scripts/hybrid/public-up.sh both
./scripts/hybrid/public-status.sh
./scripts/scraper-browser.sh enable
./scripts/scraper-browser.sh disable
./scripts/migrate.sh
./db-backup.sh status
./db-backup.sh daily
./db-backup.sh snapshot
./test-mreader.sh --quick
./test-mreader.sh --full
./diagnose-mreader.sh
./test-mreader.sh --user-800 --admin-username <disposable-admin> --admin-password <disposable-password> --scraper-series-url <real-series-url>
./hybrid-down.sh
```

Recovery shortcuts:

```bash
make catalog-recovery-check SOURCE=/path/to/backup.dump
make catalog-recovery-import SOURCE=/path/to/backup.dump
```

### One-command fault finding

Run `./diagnose-mreader.sh` to launch the dedicated Dockerized diagnostics module against the current twin-plane deployment. Full diagnostics are permissions-first: **832 PostgreSQL grant/membership/isolation checks + 272 gateway/routing/CORS boundary cases** run before the normal API, actor, and browser suites, so 500/503 cascades can be localized to database authorization, edge/service routing, or application/state integration. It also captures Kubernetes/Docker/PostgreSQL/RabbitMQ/Valkey/NAS evidence before and after the run and writes `test-results/diagnostics/<run-id>/REPORT_BUNDLE.zip` for debugging. Use `--quick` for a shorter core functional pass; the architecture checks remain explicit.

For the user/admin acceptance pass, run `./test-mreader.sh --user-800`. It wraps the same diagnostics with a source inventory of every current React route and clickable access point, passes disposable admin credentials into both pytest and Playwright, exercises a supplied real scraper series URL through API and browser discovery, and writes `test-results/user-qualification/<run-id>/qualification-800.tsv`. The ledger contains exactly 800 prioritized runtime cases (functional API/external/browser first, then boundary and least-privilege evidence), while the command still fails if **any** additional executed test outside those 800 fails. Prefer credential environment variables (`MREADER_TEST_ADMIN_USERNAME`, `MREADER_TEST_ADMIN_PASSWORD`) over command-line password arguments when shell history matters.

## Validation

```bash
./scripts/validate-current-release.sh
for t in tests/regression/*.sh; do TERM=xterm bash "$t"; done
```

Runtime Docker/Kubernetes/API/browser/load verification additionally requires Docker Desktop, Docker Desktop Kubernetes, a configured `.env`, and reachable NAS SeaweedFS.

## Documentation

- `RELEASE_NOTES.md`
- `CONSOLIDATION_AUDIT_RC4.84.md`
- `docs/recovery/CATALOG_RECOVERY.md`
- `docs/architecture/TWIN_PLANE_ARCHITECTURE.md`
- `docs/deployment/DOCKER_DESKTOP_HYBRID.md`
- `docs/deployment/NAS_STORAGE_QUICKSTART.md`
- `docs/operations/POSTGRES_BACKUP_AND_RESTORE.md`
# analyse
