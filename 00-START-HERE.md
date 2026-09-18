# MReader RC4.85 — milestone 1 source test package

This is a full application source checkpoint provided after resolving the startup blocker caused by obsolete recovery assumptions. It includes Web, Android, backend services, database migrations, Docker/Kubernetes configuration and tests. It is not a compiled APK or a qualified final RC4.85 release.

## Major blocker resolved

Startup validation required the retired Docker backup-spool volume and the former 7/14-day retention defaults even though the application had moved PostgreSQL protection to the host user's home. Automatic volume adoption also continued selecting that obsolete spool.

The operator paths now share the home-directory root, validate the requested 4-day dump / 2-day snapshot defaults, and leave old backup-spool volumes untouched during adoption. The storage doctor invokes the current backup agent instead of checking a NAS backup inventory. Missing/known old retention defaults migrate once with an original configuration copy; custom settings and later administrator changes survive.

All 13 source/fixture regressions invoked by the hybrid validator, plus its actual backup-policy assertions, pass after this correction. These checks do not execute Docker Desktop or PostgreSQL.

## Other included source work

- Progress commits resume, chapter evidence and outbox effects together, with revision/session/sequence ordering and account fencing.
- Web and Android use account/origin-scoped local reading journals for immediate pending state and background synchronization. Canonical Library counts and Recently Opened come from one server projection.
- Upgrade and restore candidates use one serialized migration executor. Transactional preservation runs before pending 047/048 so an unrelated chapter's checkpoint is not copied into history; 052 separates inferred reach from exact read/recency evidence.
- PostgreSQL recovery bundles use one host-local catalog and operation queue. Logical bundles include the application database, globals, manifests and checksums.

## Verification available in this package

| Check | Latest result |
|---|---|
| Web reading repository behavioral tests | 31 passed |
| Migration shell runner behavioral tests | 6 passed |
| Pre-upgrade capture/order behavioral tests | 5 passed |
| Recovery operator behavioral tests | 8 passed |
| Startup source/fixture guards and backup-policy assertions | 14 passed |
| Updated Bash storage doctor/environment and source contracts | Passed |
| Actual PostgreSQL migration cases | 10 written; blocked/skipped here |
| Actual API, Go/TypeScript builds, browser and Android execution | Blocked by unavailable dependencies/tooling here |

The archive includes `SOURCE-CHECKPOINT.json`, detailed startup check output and per-file SHA-256 checksums. See [the qualification record](docs/qualification/RC485-WORK-IN-PROGRESS.md) for the precise limits.

## Testing this checkpoint

The retained topology is Windows/Git Bash + Docker Desktop Kubernetes for application services, Docker Compose for stateful services and Image Edge, and external NAS SeaweedFS for media. KEDA/HPA and the existing resource limits remain.

Use disposable test infrastructure/data for this checkpoint. Startup can adopt existing volumes, and the complete writer-quiescence/restore fences and actual SQL rehearsals are not yet qualified. Do not run its migration/restore path against the only copy of an installation's data.

Build all changed services and clients from this same checkpoint. The Progress open/commit contract is incompatible with older direct command clients. Existing runtime image/version labels remain RC4.84 until the coordinated release version update; the distinct archive/checkpoint ID identifies this test source. Deployment commands and configuration are in [README.md](README.md). Android source/build instructions are in [android/README.md](android/README.md).

### P12.8 user-perspective qualification

For a disposable full-stack qualification run on the current machine, use `./test-mreader.sh --user-800`. It inventories the current React route/control surface and executes the Dockerized functional/integration API suite, route ownership checks, PostgreSQL permission matrix, user/admin gateway-boundary matrix, real external scraper journeys and Playwright browser journeys. The report contains a balanced canonical 800-case ledger and still fails if any additional executed case outside that ledger fails. Supply disposable credentials and the real scraper series URL through environment variables; see `docs/qualification/2026-09-18-rc485-p12.8-user-perspective-800-suite.md`.

## Work still required

Catalog publication/ingestion receipts, lifecycle and permission isolation; secure private recovery download transport and narrow namespace secrets; restore pin/generation/quiescence/reconciliation; actual PostgreSQL/Go/Web/Android builds and runtime tests; complete capability/load qualification and final release packaging.

The browser recovery Download action remains disabled. A full production restore and Android build have not been verified by this checkpoint. Original uploaded archives are unchanged.
