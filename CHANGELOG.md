## RC4.84 package hotfix r3

- Made PostgreSQL volume adoption catalog-aware when both candidate volumes contain valid PGDATA.
- Automatically selects the only volume that contains an MReader catalog; still fails closed when both contain catalogs.
- Added runtime regression coverage for the empty-new-volume / populated-legacy-volume upgrade case.

## RC4.84 package hotfix r1

- Fixed fresh `./scripts/bootstrap.sh` ordering so `.env` is created before stateful-volume adoption.
- Added an executable fresh-bootstrap regression and wired it into hybrid/current-release validation.

## 1.3.0-rc4.84 — continuity-safe consolidation

- Restored safe upgrade continuity with one-time Docker stateful-volume adoption and fail-closed dual-PGDATA handling.
- Added permanent catalog-only recovery from PostgreSQL custom dumps and MReader physical snapshots; NAS validation is read-only and v4 page paths/seeds are preserved.
- Future backup manifests declare PostgreSQL major, schema migration version, catalog recovery contract and protected encoding version.
- Removed proven-dead API aliases: Catalog `/dashboard`, Progress PUT mutation, scraper `publish-status`, Realtime `/ws`.
- Preserved the RC4.83 chapter-grant, v4 codec, two-table reading state, PostgreSQL-only Media status, shared Social metrics and hybrid/KEDA ownership model.
- Android build code advanced to 484; visible app version remains `ver.1.1.0`.

# v1.3.0-rc4.83 — repository consolidation and integration repair

- Made Docker Desktop Kubernetes + hybrid stateful Compose + external NAS SeaweedFS + KEDA/HPA the only executable deployment model.
- Consolidated reading state to `reading_progress` + `chapter_reads`; migration 048 removes transition `reading_history` state on upgrade.
- Consolidated Reader authorization to chapter grants and removed page/path/scope/batch token compatibility.
- Standardized protected pages on encoding v4 across database, encoders, Web and Android.
- Removed Android hidden direct `/images` fallback; native protected transport is the mobile Reader adapter.
- Made PostgreSQL `media_operations` the sole Media job-status ledger and cache Valkey the explicit chapter-grant cache/revocation owner.
- Made scraper staging strict to the Kubernetes PVC and aligned Catalog/Lifecycle local-vs-NAS deletion ownership.
- Reused one Social public-metrics aggregate implementation and removed legacy notification-kind defaults.
- Removed superseded Helm/platform/generic-gateway/full-stack Compose deployment files and old Docker-volume-name compatibility.
- Updated release/audit/test scripts so retired behavior is forbidden rather than required.

# Changelog

## v1.3.0-rc4.82 — repository consolidation

- Consolidated reading state to `reading_progress` + `chapter_reads`; migration 047 backfills and drops `reading_history`.
- Removed duplicate Smart Library Progress-History fallback/floor queries from web and Android.
- Removed legacy `/api/token/refresh`, per-page token fallback, and v2/v3 protected-page acceptance; chapter-scoped v4 is canonical.
- Removed the Media compatibility upload adapter; durable Media jobs are the only chapter upload ingestion path.
- Made Social ratings schema and session contract v1 mandatory across services; removed rolling-upgrade session-shape acceptance.
- Removed dormant legacy scraper `_scraper/*` SeaweedFS staging fallback; staging is local until publish.
- Kept Docker Desktop Kubernetes + Docker Compose + external NAS SeaweedFS + KEDA as the canonical working deployment model.
- Removed checked-in generated caches/build output and point-in-time audit clutter from the runnable package.

# RC4.82 — History footprint + public series metrics reliability

- Decoupled synchronous `reading_history` persistence from secondary `chapter_reads` writes so a secondary-table problem cannot roll back Library footprint membership.
- Added client-side retry for the idempotent chapter-open history call on both web and Android.
- Added a direct Progress History safety floor/recent footprint section to web Library and a History count floor to Android Smart Library.
- Added migration `046_reading_history_repair_rc482.sql` to replay recoverable history from `reading_progress`/`chapter_reads`.
- Made `/api/social/series/:seriesId/metrics` and `/api/social/series/metrics-batch` strictly public/session-independent aggregate endpoints.
- Restored aggregate average rating, bookmark count, and subscriber count across web/mobile cards and guest Series views while keeping all mutations authentication-gated.
- Preserved RC4.80 web-baseline/scraper repairs and mobile Latest Updates behavior.


- Restored canonical scraper chapter-number identity and durable title-suppression behavior from the supplied RC4.53 working baseline.
- Restored missing scraper identity tests/regression guards.
- Classified all 140 current API routes and added mobile Reader adapter API coverage.
- Aligned active Docker/Kubernetes/Helm/service release tags that were still pinned to RC4.52.
- Mobile Latest Updates now shows the latest two chapters with larger aligned touch rows and text.
- Retained RC4.79 Smart Library History repair and newer Android integrations.

# RC4.79 — Smart Library History visibility repair

- Fixed shared web/mobile Smart Library History staying empty or reporting zero unique series after reading.
- Added synchronous authenticated chapter-open history recording.
- Exit progress commit now synchronously updates lightweight history/chapter-read state before the asynchronous stream flush.
- Added migration 045 to recover missing reading_history rows from reading_progress/chapter_reads.
- Added end-to-end API regression coverage for immediate History count and History membership.

# RC4.78 — Smart Library session continuity and navigation finalization

- Preserve the last server-verified Android account identity in an Android-Keystore encrypted snapshot so account-scoped Smart Library/cache can render during temporary network/TLS/gateway outages.
- Keep the encrypted session cookie authoritative; an actual profile 401 clears the snapshot, protected cache, and personal Smart Library cache.
- Reconcile the cached account identity on foreground resume without converting transient transport failures into a guest session.
- Retain RC4.76/77 explicit Browse-to-Catalog-root navigation and accurate bottom-bar selection.
- Retain migration 044 that removes every legacy `users.avatar_key` CHECK before installing the canonical replacement-avatar constraint, fixing avatar-change HTTP 500 on upgraded databases.
- Keep the new RC4.77 mobile launcher icon, aligned web/mobile avatar grids, local content cache, 24-hour signed-in chapter cache, and 3-ahead/2-behind reader prefetch.

# RC4.77 — mobile integration reliability, Smart Library and avatar constraint repair

- Added migration `044_profile_avatar_constraint_repair_rc476.sql` to discover and remove every legacy `users.avatar_key` CHECK constraint before installing one canonical replacement-avatar constraint.
- Fresh schema now names the avatar constraint explicitly as `ck_users_avatar_key`; historical migration 025 remains unchanged for migration-ledger integrity.
- Expanded the Auth API regression test so every replacement avatar is persisted through the real profile-update/database path.
- Unified the web profile avatar cards through one shared grid/card path and fixed mobile avatar image/label/description/selection slots for deterministic alignment.
- Added account-scoped Smart Library process/disk cache with stale-while-revalidate behavior so Library does not disconnect visually during tab/Reader transitions.
- Smart Library overlays a just-read local chapter onto matching resume/furthest metadata while Progress/Social reconciliation completes.
- Recently Opened is available in both Smart Library All and History scopes, including local history during temporary network outages.
- Browse bottom-navigation taps now explicitly pop to the existing Catalog root; only the actually visible top-level destination is highlighted.
- All mobile HTTP 5xx, DNS, TLS, handshake and transport failures collapse to the user-facing `Server under maintenance.` message.
- Retains RC4.75 Latest Updates alignment, RC4.73 cache/prefetch hardening, and `Mreader` / `ver.1.1.0` identity.

# RC4.75 — avatar integration completion and mobile UI polish

- Audited Browse, Catalog/Search/Series SWR caches, chapter persistence, Settings clear-data, reader prefetch, history, pagination, Latest Updates, and top-level navigation as complete UI → repository → API/storage flows.
- Enforced the protected-page 24-hour TTL in both RAM and disk; disk LRU eviction now demotes RAM persistence bookkeeping.
- Deduplicated visible reader, viewport prefetch, and full-chapter cache fetches with shared per-object locks.
- Made signed-in chapter-wide caching sequential and delayed behind interactive reader work.
- Added process-hot parsed metadata snapshots plus saved/restored top-level tab state for immediate Reader ↔ Browse/tab transitions.
- Bounded process-hot result maps and added zero-frame hot-cover reuse so long sessions stay resource-safe while returning screens remain visually instant.
- Added displayed-request keys so Catalog/Search/Series cannot show stale rows under a newly selected page/filter/query.
- Made Settings cache usage react when background caching finishes.
- Preserved the working Browse anchor, 3-ahead/2-behind reader window, Latest Updates sizing, history parity, pagination, `Mreader` launcher label/icon, and `ver.1.1.0`.

# MReader v1.3.0-rc4.71

- Removed the Android native reader cream surround/inset.
- Restored edge-to-edge chapter page rendering.
- Simplified reader progress/resume geometry to the actual page aspect ratio.
- Responsive image selection and decode width now use the full reader width.
- Replaced the cream-layout regression test with edge-to-edge geometry assertions.
- Retained Android app identity `Mreader`, `ver.1.1.0`, and versionCode 471.

# v1.3.0-rc4.68 — Android mobile UI/UX, pagination and sync stabilization

- Added a cream reader surround targeting 76dp (the CSS/96-ppi visual equivalent of about 2 cm) on all four sides, with a narrow-phone safety cap that preserves at least 200dp of readable page width.
- Updated reader progress geometry, resume offset calculation, decode width and responsive-derivative selection to use the visible page width after the cream inset.
- Normalized horizontal shelves and poster/card text slots so carousels no longer step, clip or change height from one/two-line titles.
- Added narrow-screen-safe section headings/actions and consistent carousel widths/edge peek spacing.
- Replaced Android Catalog and Advanced Search append-style paging with explicit Previous / Page N / Next controls using 20-row web-compatible offsets.
- Replaced series chapter Load more behavior with debounced server-side chapter-number search and Newer / Page N / Older controls using the web `chapter_search` contract.
- Kept empty/end pages recoverable so Previous/Newer remains available instead of trapping the user on a blank page.
- Parallelized independent taxonomy, library history, series social/reading-state and Browse discovery fetches; optional search social metrics no longer block primary result rendering.
- Search now retries the exact failed page and refreshes active results/taxonomy on foreground content reconciliation.
- Preserved RC4.67 account-scoped recent-read overlay, foreground history reconciliation, Smart Library parity and mobile page-count cleanup.
- Added RC4.68 static regression guards and pure-Kotlin reader-layout policy validation.

# v1.3.0-rc4.67 — Android reading-state and mobile/web parity

- Fixed Android Browse/Continue Reading initialization so personal history follows the authenticated session.
- Refreshes personal reading state when the app returns to the foreground, allowing web reads to reconcile into mobile without an app restart.
- Added a small account-scoped local recent-read overlay and deterministic server/local history merge so a just-read Android chapter appears immediately while the asynchronous progress flusher catches up.
- Expanded the Android Smart Library model/parser to retain the full web reading-state contract: resume, furthest/reached, next, first, latest, counts, timestamps and activity fields.
- Added a Recently Opened rail to the History scope and aligned Smart Library actions with web semantics: Read next, Start, Continue and Read.
- Removed chapter page-count text from Android chapter rows and reader chrome while retaining the visual progress indicator.
- Personal bookmark/follow/rating mutations now invalidate shared content state for consistent Library/Browse refresh.
- Added static and unit regression coverage for history merging, session/foreground refresh, Smart Library parity and page-count removal.

# v1.3.0-rc4.66 — native fast-reader compile fix

- Fixed `CatalogScreen.DiscoveryPrimaryAction` to use the real `Series` model instead of nonexistent `SeriesSummary`.
- Eliminates the Kotlin compiler/type-inference cascade reported at CatalogScreen lines 469–483.
- Retains all RC4.65 native-reader latency improvements, mobile adapter integration, WebView fail-safe, and exact Android Docker OS package pins.
- Added a static contract check so the nonexistent `SeriesSummary` type cannot reappear in Catalog UI.

# v1.3.0-rc4.65 — native fast reader, web-aligned fetch policy, simple connection status

- Restored the optimized native protected reader as the default chapter engine; retained the proven web reader as an explicit fallback.
- Removed Auth-profile initialization from the reader-manifest critical path.
- Matched the web reader's 820px/15% physical-pixel responsive-asset decision.
- Changed encoded-page warming to a two-ahead/one-behind network window with at most two concurrent requests and no background bitmap decode.
- Kept Reader-Go `/api/mobile/v1` as the authoritative native page adapter with direct `/images` compatibility fallback.
- Simplified Settings connection UX to Connected / Not connected / Checking; gateway and CDN URLs are no longer user-visible.
- Pinned Android Docker builder OS packages to exact Jammy revisions so `tests/regression/dependency-pins.sh` passes during `hybrid-up.sh`.
- Added `ReaderVariantPolicyTest` and strengthened Android/web integration audits for the new fetch policy and hidden URL requirement.

# v1.3.0-rc4.64 — Android reader bridge and mobile adapter

- Added `ANDROID_WEB_READER_ALIGNMENT_RC4.64.md` plus a build-time web/Android reader contract audit so manifest/token/image-path drift is caught before Gradle compilation.
- Made WebView session handoff deterministic: native cookies are acknowledged before the first `/read/...` navigation, and `AndroidView.update` no longer races the initial authenticated load.
- Fixed generic Docker Caddy mobile-adapter routing to use the Compose service name `reader_go`; Kubernetes/Helm continue to use `reader-go`.
- Makes the proven web reader the default Android chapter engine to eliminate the physical-device native reader crash/failure path while preserving the native app shell.
- Bridges the encrypted native session into WebView so authenticated reader progress/comments continue to use the same account.
- Adds a versioned Reader-Go `/api/mobile/v1` adapter that validates the existing chapter token and streams still-scrambled page bytes directly from canonical storage paths.
- Routes `/api/mobile/*` to Reader Go in Docker Desktop hybrid, generic gateway and Helm profiles.
- Aligns the native fallback with web behavior by requesting canonical `image_path` first and reduces its output bitmap budget for phone stability.

# Android RC4.63 — integration/compile hotfix for web-parity UI

- Fixed the real Kotlin compiler failure in `NotificationsScreen.kt` caused by an extra closing brace before `catch`.
- Added the missing exact web `brand-800` palette shade used by Reader surfaces.
- Moved per-notification read mutations into `AppViewModel` scope so navigation cannot cancel the server update.
- Added foreground-only notification badge refresh (`ON_RESUME`) without background polling.
- Fixed the Unread-only notification filter so read items disappear immediately after single/all-read actions.
- Expanded the static audit to verify the `/api/notifications` public gateway route, notification navigation payload fields, palette completeness and the RC4.62 brace regression.
- Added explicit `:app:compileDebugKotlin` before unit tests/APK assembly for faster source-failure feedback.
- Retains all RC4.62 web-parity UI and RC4.60 reader/token compatibility work.

# Android RC4.62 — web-parity UI/UX and discussions

- Reworked the native Compose UI around the web frontend's exact ink-night, ink-panel, paper, coral and gold design language.
- Expanded Browse into poster-first discovery with hero treatment, web-style shelves and Surprise Me.
- Added native advanced Search with tags/rating filters and social metrics.
- Added native registration, notification feed/badge and profile/avatar flows.
- Added reusable series/chapter discussion UI backed by the existing Social comments API, including replies, posting and owner deletion.
- Updated Series, Library, Login, Settings and Reader surfaces to match the web information hierarchy while retaining mobile-native navigation and safe-area behavior.
- Preserved RC4.60 chapter-open compatibility, responsive protected-page decoding, token compatibility and image-origin fallback.
- Extended the Android static audit to cover the new web-parity routes, palette, search/notification/comment integrations and reader discussion surfaces.

# Android RC4.60 — chapter-open compatibility

- Decoupled reader manifest rendering from Progress restoration.
- Added 4-second best-effort remote progress restore timeout.
- Added web-compatible fallback from `chapter_token` to legacy page `token`.
- Added legacy `/api/token/refresh` fallback when the modern page-grant endpoint is unavailable.
- Added ReaderTokenPolicy unit coverage and static contract checks.
- Updated Android build output to RC4.60.

## 1.3.0-rc4.58 — Android Kotlin compile fix

- Fixed `ReaderScreen` nullable `LocalProgressCheckpoint` compile failure discovered by the real Docker Gradle build.
- Moved local/server checkpoint selection into `ProgressSelectionPolicy` with explicit null handling.
- Added regression tests for no/local/server/newest progress combinations.
- Removed remaining unnecessary `user!!` assertions in Settings.
- Bumped Android versionCode to 458 and the Docker image/APK output to RC4.58.

# MReader Change Log

## 1.3.0-rc4.57 — Android Retrofit connection layer

- Replaced the Android hand-written API request layer with Retrofit 3 over OkHttp 5.
- Centralized Android endpoints in `MReaderApiService` and transport/session behavior in `MReaderApiAdapter`.
- Added gateway/Catalog/Auth connection diagnostics with DNS, TLS and timeout error classification.
- Added bounded Android request concurrency and explicit OkHttp Happy Eyeballs fast fallback.
- Added Android network-state permission and stale emulator-origin migration for physical phones.
- Default Android gateway remains `https://overlord.seahorse-banded.ts.net`.

## RC4.56 Android Hotfix 3 — API 36 AndroidX compatibility

- Fixed the real Gradle `checkDebugAarMetadata` failure caused by API-37-only AndroidX dependencies.
- Pinned Compose BOM to `2026.06.01`, which resolves the core Compose 1.11.4 stable line instead of Compose 1.12.0.
- Pinned Lifecycle Compose artifacts to `2.10.0` instead of `2.11.0`.
- Pinned Navigation Compose to `2.9.8` instead of `2.10.0`.
- Added an explicit `:app:checkDebugAarMetadata` preflight task before unit tests and APK assembly.
- Added static guards that reject the known API-37-only dependency pins while `compileSdk = 36`.
- Changed Docker builder tag to `mreader-android-builder:rc4.56-hf3` so the previous hotfix image cannot be reused accidentally.

## RC4.56 Android Hotfix 2 — stable SDK / Android CLI builder

- Fixed Docker APK build failure `Failed to find package platforms;android-37`.
- Changed Android compile SDK and Docker SDK platform from API 37 to the current stable API 36; target SDK remains 36.
- Replaced deprecated `sdkmanager --install` with the current `android sdk install` CLI.
- Added Docker build-time verification for `android.jar`, `aapt2`, `adb`, and Gradle.
- Changed the builder image tag to `mreader-android-builder:rc4.56-hf2` to prevent reuse of the failed toolchain image.
- Added static audit checks that reject API-37/deprecated-sdkmanager toolchain drift.

# v1.3.0-rc4.56 — Android integration/resource audit

- Set the Android default gateway to `https://overlord.seahorse-banded.ts.net` and revalidated all Android API paths against the user gateway/service routes.
- Fixed whole-chapter progress semantics, exit-only server commits, durable account-scoped local checkpoints, fraction-based restore and 100% end-of-chapter capture.
- Fixed legacy/non-scrambled reader compatibility, grant-gated protected-cache reuse, corrupt cache eviction/refetch, stale-token refresh handling and cancellation-safe serialized decoding.
- Added paginated catalog/library/chapter loading, retry/empty UI states and small-screen Settings scrolling.
- Reduced cover cache to 64/48 MiB high/target and protected encoded-page cache to 128/96 MiB high/target; decoded clean pages remain memory-only.
- Updated OkHttp BOM to 5.4.0 and retained current AGP 9.4 / Gradle 9.6 / JDK 17 / API 37 / Compose 2026.08.00 pins.
- Added Docker build CPU/RAM bounds and versioned builder-image reuse while preserving the persistent Gradle dependency cache.
- Expanded `scripts/android-static-audit.sh` with legacy-page, cache-authorization/corruption, cache-bound and OkHttp-pin assertions.
- Removed the accidental host-Python requirement from the Android static audit; XML is checked with an available host parser or by the mandatory Docker/Gradle build stage.

# v1.3.0-rc4.53 — native Android client

- Adds an independent Kotlin/Jetpack Compose Android application under `android/` without replacing the web client or creating a mobile-only backend.
- Reuses existing MReader auth/catalog/reader/token/progress/social/image contracts and encrypted cookie sessions.
- Ports protected image decoding v2/v3/v4, including `MRTILE4`, to native Android bitmap reconstruction.
- Adds bounded encoded-page disk cache, lazy decoded-bitmap retention, responsive asset selection, grant refresh, progress resume/sync, bookmarks/library and configurable gateway/CDN settings.
- Adds Android codec compatibility unit vector and Android developer/build instructions.
- Server runtime/deployment behavior remains RC4.52-equivalent.

# v1.3.0-rc4.52 — Database Protection capability/readiness integration

- Decouples Database Protection capabilities from a single physical-storage health bit: restore drills remain available when the backup inventory and operation engine are healthy even while physical proof is pending.
- Adds durable `database_protection_runtime` heartbeat/capability state so Admin can distinguish an offline worker from a deliberately degraded storage-proof state.
- Keeps the backup operation engine running after migrations when only NAS proof is missing; protected backup/snapshot/production-restore writes remain locked until proof is valid.
- Adds capability-aware server-side gates for logical backup, physical snapshot, restore drill and production restore, including the legacy Admin manual-backup action.
- Adds browser-safe Recovery Engine status and automatic readiness polling; no internal filesystem paths, Filer routes, devices, mount points or proof payloads are exposed.
- Adds a standalone, non-disruptive NAS verifier that derives the active SeaweedFS `/data` bind from Docker, verifies it with `findmnt`, and publishes proof without restarting SeaweedFS or moving existing data.
- Adds optional SSH-assisted proof bootstrap (`POSTGRES_BACKUP_AUTO_VERIFY_NAS`) that streams the verifier to an established NAS; it is opt-in and stores no SSH password.
- Preserves the inspected NAS layout (`/srv/seaweed/hdd/volumes`) and keeps strict drift protection for package-managed NAS restarts.

# v1.3.0-rc4.51 — established NAS adoption without data migration

- Makes the running SeaweedFS volume container `/data` bind source authoritative for non-disruptive verification of established NAS deployments.
- Adds `check-running`/`publish-running` storage-contract modes so existing NAS data is never moved, recreated or restarted merely to publish physical-storage proof.
- Keeps package-managed NAS startup strict: configuration/runtime drift blocks restart to prevent switching SeaweedFS to an empty/wrong directory.
- Uses the running Filer's published port during established-NAS verification when no NAS `.env` port is available.
- Treats NAS config/runtime drift as advisory when the actual running bind, physical disk and application expectation agree; physical verification remains valid while restart drift is reported separately.
- Adds storage-contract exit code 42 to distinguish NAS proof/storage availability from PostgreSQL replication/database failures.
- Allows hybrid application deployment to continue when only NAS physical proof is missing/unavailable, while leaving the backup scheduler stopped and refusing new verified recovery points.
- Extends sibling `.env` reuse to short `mreader-rc*` release directories.
- Adds bounded migration of the known obsolete `/srv/mreader-seaweed/hdd/volume` expected-root default to `/srv/seaweed/hdd/volumes`, preserving all unrelated secrets/settings and creating a pre-migration copy.
- Adds established-NAS runtime-adoption and environment-migration regressions.

# v1.3.0-rc4.50 — opaque Database Protection UI + existing-NAS adoption + snapshot recovery

- Adopts the existing NAS SeaweedFS layout rather than forcing a storage migration; the running SeaweedFS volume container `/data` bind source is the authoritative physical chunk location and is verified/published by backend tooling.
- Adds explicit `NAS_VOLUME_DATA_DIR` support and keeps logical backup namespace/physical path configuration in backend `.env`/NAS configuration.
- Removes internal storage topology from browser-facing Database Protection responses and UI: no Filer URLs, filesystem paths, mount points, device names, filesystem names, storage proof payloads, backend commands, or `.env` variable names are rendered.
- Replaces raw backup category/filename addressing in browser actions with stable opaque `bkp_…` identifiers; drill/restore/download resolve those identifiers server-side.
- Sanitizes database-operation history so raw backup filenames, metadata, result payloads and backend error details stay in backend logs only.
- Supports both logical `pg_dump` archives and physical `pg_basebackup` snapshots as first-class restore-drill/restore sources. Physical snapshots boot in an isolated PostgreSQL instance, are checksum/version/tablespace validated, migrated, and converted to a logical staging archive before the normal guarded atomic cutover.
- Adds manual snapshot creation from Admin, snapshot restore drills, snapshot download, and snapshot restore while keeping pre-restore safety backup, audit preservation, cutover rollback and recovery markers.
- Updates the legacy Admin backup summary to return only browser-safe recovery-point metadata.
- Packaging-time validation: 38/38 static regressions PASS; API route inventory 137/137 classified.

# v1.3.0-rc4.49 — NAS storage contract and environment diagnostics

- Replaces the ambiguous Database Protection “Not verified / mismatch” state with explicit `application_env_mismatch`, `application_env_incomplete`, `filer_unreachable`, `proof_missing`, `proof_unavailable`, `physical_root_mismatch`, `logical_root_mismatch`, and `verified` verdicts.
- Shows Filer reachability, indexed backup count, runtime Filer URL, configured NAS host/port, logical namespace, expected physical root and NAS-published device/filesystem independently in the Admin UI.
- Adds `scripts/storage/backup-storage-doctor.sh` to compare non-secret Windows `.env`, running backup-agent values, Kubernetes scraper runtime values, backup index and NAS proof.
- Fixes `scripts/storage/nas-up.sh` so normal NAS startup can no longer bypass guarded `findmnt` verification and `storage-location.json` publication.
- Makes the NAS Compose Filer host port honor `NAS_SEAWEEDFS_PORT`.
- Hardens NAS env validation: absolute SSD/HDD roots, no traversal, `NAS_HDD_ROOT` must be the parent root (not end in `/volume`), safe backup namespace and valid port.
- Makes new backups require a matching NAS physical-storage proof by default (`POSTGRES_BACKUP_REQUIRE_STORAGE_PROOF=true`); Filer-only verification is an explicit warning-producing override.
- Expands cross-machine `.env` documentation and adds `nas-status.sh` mount-source diagnostics.
- Adds storage-contract classifier, doctor, stale-Kubernetes-env and proof-missing regressions. Packaging-time static suite: 36/36 PASS; API route inventory remains 136/136.

# v1.3.0-rc4.48 — database-operation ledger JSON hotfix

- Fixes RC4.47 restore-drill/restore status persistence where Bash `result="${5:-{}}"` appended a stray `}` to supplied JSON and caused PostgreSQL `invalid input syntax for type json` after otherwise-successful restore work.
- Canonicalizes database-operation `result` payloads through `jq`, requires a JSON object, retries ledger updates three times, and no longer swallows failed status writes with `|| true`.
- Makes restore-drill and destructive-restore phase/terminal ledger updates explicit failure gates instead of relying on Bash `errexit` inside scheduler error-handling contexts.
- Adds startup reconciliation for orphaned `running` database operations from a prior backup-agent process, while preserving cutover-marker authority for interrupted destructive restores.
- Keeps rollback databases/recovery markers during restart recovery until a terminal database-operation status has been durably persisted.
- Adds `database-operation-ledger-runtime.sh`, reproducing the long RC4.30 backup filename/result payload from the reported failure and validating default `{}`, non-object rejection, and three-attempt SQL failure propagation.
- Packaging validation: 34/34 static regressions PASS; API route audit remains 136/136 classified.

# v1.3.0-rc4.47 — enterprise PostgreSQL Database Protection

- Adds dedicated Admin `/admin/database` Database Protection console with exact logical Filer path, expected physical NAS HDD root, verified mount/device proof, backup policy, inventory, downloads, operation history, restore drills and controlled restores.
- Adds durable `database_operations` queue for `backup`, `restore_drill`, and `restore`, with one-active-operation enforcement, phases, status, errors, result metadata and queued cancellation.
- Keeps Docker/Kubernetes control credentials out of the web application; the isolated host-side `backup_agent` remains the only component performing `pg_dump`, `pg_restore`, migrations and database-name cutover.
- Adds NAS `ops/nas-seaweedfs/start.sh` mount guard using `findmnt`; SeaweedFS refuses startup when the configured HDD path resolves to the NAS root filesystem and publishes `/backups/mreader/postgres/storage-location.json` after verification.
- Adds staged point-in-time restore: checksum/archive verification, temporary restore DB, current migration ledger application, data validation, pre-restore safety backup, persistent cutover recovery marker, atomic rename cutover, audit-history preservation, post-cutover validation and compensating rollback.
- Routes the CLI restore path through the same staged restore engine instead of the older drop/recreate flow; `db-restore.sh` still quiesces Kubernetes clients and leaves them stopped after a failed restore.
- Adds Admin backup downloads as native streaming responses so large dump files are not buffered into frontend memory.
- Expands API route inventory to 136/136 classified routes and pytest API/integration coverage to 122 tests; adds non-destructive Database Protection RBAC/path/typed-confirmation tests and a dedicated static contract regression.
- Packaging validation: 33/33 static regressions PASS, API route audit 136/136 PASS, Python/Bash/TSX syntax validation PASS.

- Adds Git-Bash/MSYS container-path protection for Dockerized seed/pytest/k6/audit commands and regression coverage for `/load`, `/tests`, `/repo`, and `/results` container paths.
- Expands restore failure handling so audit-history import/cleanup failures and post-cutover validation failures trigger compensating database-name rollback, backed by persistent recovery-marker regressions and post-run stale/failed database-operation integrity checks.

# v1.3.0-rc4.46 — comprehensive API/integration/E2E/load/spike/soak release qualification

- Wired deterministic release qualification: integrity baseline → static → API/integration → browser E2E → runtime event integration → breakpoint → spike/recovery → soak → final integrity.
- Expanded pytest to 109 API/integration tests and tightened the route manifest to 130/130 source routes with concrete evidence.
- Added deterministic deep scraper route coverage for existing-draft page lifecycle, publish, SSRF validation, retries, operation acknowledgement, series-draft status/events/cancel, and viewer state.
- Added/fixed 6 Playwright journeys including user social/library flow, admin UI authorization/routes, and admin scraper stage/publish → user Reader.
- Added shared 16-workload k6 executor, true sudden spike/recovery tests, 7-workload soak profile, HPA/KEDA/resource sampling and dropped-iteration/429/5xx accounting.
- Added current outbox→RabbitMQ integration, explicitly gated broker-outage chaos, and post-run restart/OOM/stale-work/leak/backlog integrity checks.
- Corrected browser admin/user-plane routing, node-postgres URL normalization, API preflight HTTP status handling, spike shedding thresholds, and qualification log-pipeline failure handling.
- Packaging validation: 30/30 static regressions PASS and API inventory 130/130 classified; Docker runtime suites remain target-host validation.

# v1.3.0-rc4.45 — Windows/Git-Bash regression portability and truthful capability skips

- Fixed the uploaded RC4.44 static-run failures caused by host-only test assumptions, without weakening Linux/container validation.
- Removed the duplicate nested execution of `backup-daily-policy.sh` from `backup-agent-static.sh`; each regression now runs exactly once under the regression runner.
- Added a self-contained test-only jq fixture for the backup scheduling simulation so Windows Git Bash does not require host `jq`; the production backup-agent image still uses its pinned jq package.
- Reworked staging-volume permission validation: Linux root hosts exercise the entrypoint directly; Windows/non-root hosts exercise the real scraper image inside a Linux Docker named volume when available, otherwise report an explicit capability SKIP (exit 77) instead of a false failure.
- Regression runner now records PASS/SKIP/FAIL separately, preserves individual exit codes, and treats log-capture (`tee`) failure as a harness failure.
- Added a behavioral regression for PASS/SKIP/FAIL reporting and preserved-failure exit codes.
- Added a Windows/no-Docker capability-classification regression for staging ownership checks.
- Static regression validation in the packaging environment: 28/28 PASS.

# v1.3.0-rc4.44 — test harness hardening and edge-case expansion

- Fixed Docker test helper `errexit` preservation and pipeline exit-code handling.
- Treat failed live-log capture and failed/missing pytest result artifacts as harness failures.
- Wired static regressions into normal quick/full correctness gates.
- Removed stale Catalog `503` success branches and corrected locked Auth profile identifier expectations.
- Added Reader navigation-boundary, curation cache invalidation, lifecycle delete retry/deduplication, and diagnostic secret-redaction tests.
- Made scheduled curation tests use real Admin APIs instead of cache-bypassing direct DB writes.
- Isolated k6 setup dependencies per workload and separated auth-login stress credentials from authenticated read/write workloads.
- Made the auth-login load identity unique per capacity run and removed it on cleanup.
- Static test-harness/regression validation: 26/26 PASS; Python/Bash/JS syntax checks PASS.

# v1.3.0-rc4.43 — media event-loop relief, Reader fan-out and scoped Catalog cache invalidation

- Moves CPU-heavy chapter page-generator advancement and optional first/last image conversion off the asyncio event loop; adds a one-page bounded prefetch queue so conversion can overlap SeaweedFS upload without chapter-sized buffering.
- Moves thumbnail-transformer libvips resize/WebP encoding into Starlette's threadpool so concurrent requests and health checks are not serialized behind image CPU work.
- Confirms the existing fresh-schema `idx_chapters_series_number` partial B-tree already covers published prev/next chapter seeks and adds an idempotent upgrade-path guard using the same index name, so legacy databases are repaired without a duplicate index.
- Fans Reader page/previous/next post-manifest reads out concurrently through the existing bounded pgx pool.
- Makes Catalog local caching scope-aware with per-scope invalidation generations and Pub/Sub scope propagation instead of global local-cache clears.
- Adds explicit curation invalidation after editor-pick/announcement writes and explicit taxonomy invalidation when series genre/tag membership can change.
- Adds focused Go cache tests and `hot-path-concurrency-cache-static.sh` regression coverage.

# v1.3.0-rc4.42 — workload-aware KEDA recovery and zero-idle background workers

- Switches long-running RabbitMQ KEDA consumers from AMQP ready-only metrics to management HTTP QueueLength including unacknowledged/in-flight deliveries.
- Adds PostgreSQL wake-up triggers for stale/undispatched scraper and media durable work, allowing recovery from zero without an always-running recovery helper.
- Scales outbox relay and lifecycle cleanup to zero when idle and wakes them from PostgreSQL due work; metric failures fall back to one replica for safety.
- Adds KEDA-namespace metric-backend connectivity preflight, required KEDA DB URL validation, restore-script integration updates and workload-aware autoscaling regressions.
- Keeps all existing CPU/RAM ceilings unchanged.
- Replaces the Kubernetes-Job diagnostic harness with ordinary Docker pytest/k6 containers that use host.docker.internal for the twin-plane gateways, the existing stateful Docker network for PostgreSQL, and the configured NAS filer directly; adds container-side connectivity preflight and live unbuffered pytest output.

# v1.3.0-rc4.41 — scraper shared-package and Kubernetes staging hotfix

- Fixes `scraper-service` startup failure caused by the scraper image not carrying the repository `shared` package used by Session Contract v1 validation.
- Makes shared Python exports lazy so scraper/browser can consume the session validator without importing unrelated DB/model dependencies.
- Preserves the Docker staging/privilege-drop ENTRYPOINT in Kubernetes by using worker `args` instead of `command`, including Helm.
- Lets lifecycle safely adopt a newly provisioned staging PVC only when no unrecoverable staged manual/batch files would be orphaned.
- Adds a no-host-Python static regression for Python image packaging, ENTRYPOINT preservation and staging-spool safety.

# v1.3.0-rc4.41 — Go compile hotfix and build-gate hardening

- Removes the stale `time` import from Reader Go store code after the RC4.39 read-only Reader refactor, fixing the Docker `go build` failure.
- Adds a Go import-usage regression guard and wires it into release validation so refactor residue is caught before a long image build.
- Audits the other RC4.39-changed Go services for the same unused-import class and preserves all RC4.39 API ownership/integration behavior unchanged.

# v1.3.0-rc4.39 — API ownership and end-to-end flow consolidation

- Makes `chapter.published` the canonical publication consequence and the Notification Worker the sole notification writer; Media/Catalog/Scraper no longer create follower notifications directly.
- Makes Reader manifests read-only. Progress now owns resume/history/exact chapter-read state and migration `039_progress_owns_reading_state.sql` adds `chapter_reads`.
- Preserves exact chapter reads under Progress batching by coalescing per `(user, series, chapter)` while keeping stale/newest resume semantics transactionally safe.
- Routes every Media chapter variant, including optional first/last images, through the durable queued ingestion workflow; the legacy synchronous route is a compatibility adapter only.
- Consolidates existing-series drafts, new-series drafts and batch overwrite/create publication through one scraper publication primitive.
- Replaces Series Detail social fan-out with one viewer-state call plus a targeted Progress state call.
- Keeps Smart Library on canonical transactional tables but executes summary + page selection in one reusable SQL statement; no denormalized projection table is introduced.
- Applies realtime comment create/delete deltas directly in the browser and removes the duplicate Social SSE/Redis subscriber path; low-rate HTTP reconciliation remains only as recovery.
- Adds Session Contract v1 with cross-language validation and rolling-upgrade support for legacy versionless sessions; inactive admins are rejected consistently.
- Normalizes Catalog cache keys, adds singleflight and generation-safe invalidation, broadcasts invalidations across replicas, and uses the expendable cache Valkey in the hybrid profile.
- Moves chapter search to Catalog across all published chapters and uses exact `chapter_reads` IDs for read badges.
- Adds `tests/regression/api-flow-ownership-static.sh` to guard the new ownership/integration invariants.

# v1.3.0-rc4.38 — Pressure efficiency and repository-layout hardening

- Eliminates the Social metrics-batch N+1 fanout with set-based PostgreSQL queries.
- Adds bounded Reader image-grant/session caches and O(1) chapter-path authorization checks.
- Adds bounded local Catalog hot-read caching and replaces Redis `KEYS` invalidation with `SCAN`.
- Coalesces Progress stream updates and persists/acknowledges them in batches.
- Makes user-plane HPA/KEDA scaling fit the existing 3584 MiB namespace quota; no CPU/RAM ceilings were raised.
- Splits the existing hybrid Valkey aggregate budget into critical no-eviction and expendable LRU instances; Progress durable stream state stays critical while its 7-day read cache uses the expendable cache instance.
- Moves Argon2 work off the Auth event loop through a bounded executor.
- Adds realtime session/reconnect jitter, bounded Redis pools, grouped unread-count queries, and disables low-value WebSocket compression.
- Adds pressure-path PostgreSQL indexes and bounded NAS/SeaweedFS write pacing.
- Reorganizes Compose, Helm, platform/IaC, and documentation assets under `deploy/` and categorized `docs/` trees while preserving the root operator entrypoints.
- Fixes all discovered moved-path consumers, including CI change detection, dependency scanning, validation paths, and multicloud/platform scripts whose relative repo-root calculations changed after the move.
- Adds `tests/regression/pressure-efficiency-static.sh` and `tests/regression/repository-paths-static.sh`.
- Corrects the twin-plane architecture document to the actual 6656 MiB admin quota.
- Retains the RC4.37 libvips/WebP and publish-verification hardening.

# v1.3.0-rc4.37 — WebP publish/verification hotfix

- Removed every active WebP `keep=` saver argument, fixing `VipsForeignSaveWebpTarget does not support optional argument keep` on libvips 8.14.1. `keep="none"` paths now use `strip=True`; `keep="icc"` paths preserve only `icc-profile-data` by removing other metadata on a private image copy.
- Covered image-service conversion, thumbnail transformer, scraper cover generation, scraper tile-pack codec, and shared tile-pack codec.
- Post-publish verification now retries transient/stale 404 responses after commit/cache invalidation.
- Reader verification now rejects empty manifests and validates both first and last page objects for multi-page chapters without downloading all pages.
- Added `tests/regression/webp-publish-verification-static.sh` and wired it into release validation.

# v1.3.0-rc4.36 — Alpine exact-pin repair

- Updated every active Alpine v3.22 `jq` pin (PostgreSQL backup image and Jenkins tooling) from `1.8.1-r0` to the current stable revision `1.8.2-r0`.
- Digest-pinned the PostgreSQL base image used by backup and migration helper images.
- Kept the strict no-ranges dependency policy; no `>=`, `^`, `~`, wildcard or `latest` dependency declarations were introduced.
- Added a regression guard for the exact backup-image package set so a stale jq pin cannot silently return.



- Removes the hidden host-Python dependency from Docker Desktop hybrid validation. Resource-budget, twin-plane object-reference, dependency-pin and Dockerfile static regressions now run with Bash/AWK/grep only; Python remains inside pinned service/test containers where appropriate.
- Adds `tests/regression/hybrid-no-host-python.sh` so the `hybrid-up.sh` validation closure cannot silently reintroduce a Windows/Git-Bash Python requirement.
## Twin-plane corrections

- Splits Docker Desktop Kubernetes into `mreader-user` and `mreader-admin` while keeping PostgreSQL, Valkey, RabbitMQ, backup agent, Image Edge and NAS SeaweedFS shared.
- Public Cloudflare Quick Tunnel and Tailscale Funnel target only `user-gateway` on `127.0.0.1:8080`; `admin-gateway` stays local/private on `127.0.0.1:8081`.
- Fixes the RC4.33 validator false-positive that searched raw Compose comments for `8081`; validation now inspects the rendered connector command.
- Fixes secret reconciliation so RabbitMQ/NAS credentials are passed through temporary env files rather than fragile JSON interpolation.
- Adds static checks for namespace/service/KEDA/HPA/gateway/cross-plane routing invariants.
- Fixes stale RC4.33 release metadata still reported by the scraper API and aligns active frontend/social/browser package metadata to RC4.36.
- Replaces remaining host-side `source .env` use in migration/NAS verification helpers with the bounded dotenv parser, preventing shell interpretation of secret values.
- Corrects admin-plane resource admission: `scraper-series-worker` is capped at 768 MiB, `media-worker` at 1536 MiB, and the admin namespace limit quota is 6656 MiB. The advertised two-series + media and mixed-worker scenarios now fit the quota while aggregate scale-out remains bounded.

## Reproducible dependency declarations

- Pins active Python requirements with exact `==` versions and rejects range operators.
- Pins direct npm dependencies/devDependencies to exact semver values; frontend continues to use its lockfile + `npm ci`.
- Pins Go module/toolchain declarations, OpenTofu/providers, Helm release versions, Kubernetes add-ons and CI security tools to exact versions.
- Fixes the CI OpenTofu installer pin from 1.12.6 to 1.12.0 so it matches the infrastructure `required_version = "= 1.12.0"` contract.
- Pins active Docker/base image tags; Playwright browser images are additionally digest-pinned.
- Pins all explicitly installed Alpine/Debian OS packages in active Dockerfiles/Jenkins to exact package revisions.
- Fixes the Image Service Dockerfile build syntax (`RUN python -m pip install ...`) and removes unnecessary compiler packages from Python builders.
- Browser scraper now uses the exact Playwright Python image instead of dynamically installing Chromium/system dependencies at build time.
- Jenkins validation image now installs exact Docker CLI/Compose plugin revisions because release validation renders Compose configuration.
- Adds dependency/Dockerfile regressions to reject future floating declarations and malformed Dockerfile directives.

## PostgreSQL protection

- Automatic logical backup: at most one attempt per local calendar day, only within the default 20:00–22:00 maintenance window.
- A verified manual/admin logical backup earlier that day satisfies the daily requirement and suppresses the automatic dump.
- Manual backups remain available at any time and are one-shot; bookkeeping recovery cannot create duplicate dumps.
- Physical snapshots are due every two days and get at most one automatic attempt on an eligible date inside the same maintenance window.
- Logical daily/manual retention remains 7 days; physical snapshot retention remains 14 days; pre-upgrade recovery points retain the latest 5.
- Dedicated `mreader_backup` replication role/HBA repair and replication-protocol verification remain mandatory.

## Scraper/concurrency baseline retained

- Different series can stage/publish in parallel; same-series updates are serialized by canonical series locks and final DB uniqueness.
- Existing-series update scraping subtracts chapters already published or already claimed/staged and only stages genuinely missing serial/chapter numbers.
- KEDA allows two scraper-series replicas and two batch replicas, with queue work durable under resource admission pressure.
- Admin dataflow history reports an exact total and cursor-pagination instead of the old 120-event UI ceiling.
- Fresh v4-only content baseline remains; obsolete legacy codec/backfill compatibility stays removed.

- Test tooling: added live Job/pod/log visibility, host-side runner phase status, `test-mreader.sh --status/--follow`, conditional test image builds, and TTL-retained diagnostic Jobs.

- Test harness follow-up: replay Secure auth cookies only inside local Docker diagnostics instead of weakening `COOKIE_SECURE`; seed taxonomy through Catalog Admin writes so cache invalidation is exercised; align Media compatibility tests with durable `202` jobs; align duplicate-guard assertions with durable state/slug contracts; preserve the complete gradual k6 breakpoint ladder.
- Distribution packaging: provide a short archive/root name to avoid Windows Explorer `0x80010135: Path too long` when users extract into already-long Downloads paths.

## v1.3.0-rc4.54 — Android Docker APK build

- Added `build-android-apk.sh`: one-command Dockerized Android build from the package root.
- Added a pinned Android builder image with JDK 17, Android API 37, Build Tools 36.0.0 and Gradle 9.6.0.
- The build runs Android unit tests before `assembleDebug` and copies the installable APK to `dist/`.
- Fixed nullable series cover URL compilation issue.
- Fixed missing `LazyColumn.items` import in the native reader.
- Pinned Lifecycle dependencies to the current stable 2.11.0 rather than a nonexistent stable 2.12.0 coordinate.
- Added debug-only cleartext network policy for emulator/LAN development while keeping release HTTPS restrictions.

### RC4.84 package revision r5
- Simplified hybrid stateful adoption to deterministic legacy-first behavior during recovery/upgrade.
- Removed automatic PostgreSQL catalog-inspector dependency from volume selection.
- Retained the PostgreSQL volume inspector as an optional manual diagnostic only.
- Added regression coverage that legacy volumes remain authoritative even when bootstrap-created canonical volumes also contain data.
- Added regression coverage proving the pre-upgrade PostgreSQL backup is created before migrations.
