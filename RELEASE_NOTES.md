# MReader v1.3.0-rc4.84 — continuity-safe consolidation

RC4.84 keeps the major RC4.83 ownership improvements but fixes the upgrade/recovery gap that could make an intact NAS library appear empty when PostgreSQL started from a new volume.

## Upgrade/data continuity

- Added one-time stateful-volume adoption through `scripts/hybrid/adopt-existing-stateful-volumes.sh`.
- Hybrid Compose volume names are selected through explicit `HYBRID_*_VOLUME_NAME` settings after adoption; runtime still has one owner per volume.
- If only an older `mreader-hybrid-stateful_pgdata` contains valid PGDATA, it is adopted.
- Upgrade bootstrap now prefers populated legacy `mreader-hybrid-stateful_*` volumes so historical PostgreSQL/Redis/RabbitMQ/cache/backup data is not shadowed by newly initialized canonical volumes. PostgreSQL still uses clone-based catalog inspection to avoid selecting a proven-empty legacy catalog over a populated canonical one.
- Bootstrap and `hybrid-up.sh` run adoption before stateful deployment.

## Permanent catalog recovery

Added `scripts/recovery/catalog-restore.sh` and `docs/recovery/CATALOG_RECOVERY.md`.

The `catalog-v4-v1` recovery contract accepts PostgreSQL custom `.dump` files and MReader physical snapshot `.tar` files. The tool starts an isolated donor PostgreSQL, extracts only Catalog/Page/Taxonomy data, validates v4 encoding metadata and existing NAS paths read-only, and imports into an empty current Catalog in one transaction.

Imported donor tables:

`series`, `chapters`, `pages`, `genres`, `series_genres`, `tags`, `series_tags`.

No user/social/progress/notification/scraper-job/media-job/cache/queue state is imported.

Before import the tool creates a local full PostgreSQL safety dump. Missing primary NAS page objects block import; missing optional cover/responsive objects are reported.

Future backup manifests now record PostgreSQL major version, latest schema migration, `recovery_contract: catalog-v4-v1`, and protected encoding version.

## API cleanup

Removed four aliases whose current consumers already use the canonical contract:

- Catalog `/api/catalog/dashboard` → use `/api/catalog/discover`.
- Progress `PUT /api/progress/{series}/{chapter}` → use `POST .../commit`.
- Scraper `/publish-status` → use `/workflow-status`.
- Realtime `/ws` → use `/api/realtime/ws`.

Gateway-covered source routes reduce from RC4.83's 138 to **135** without removing end capabilities.

## Preserved RC4.83 ownership improvements

- chapter-grant-only Reader authorization;
- v4-only protected-page runtime;
- `reading_progress` + `chapter_reads` canonical reading state;
- PostgreSQL-only Media job status;
- shared Social public-metrics aggregate owner;
- explicit cache-Redis grant ownership;
- corrected admin-to-user Reader namespace routing;
- Docker Desktop Kubernetes + stateful Compose + NAS + KEDA/HPA as the sole runtime topology.

## Deliberately not over-pruned

RC4.84 does not delete the generic scraper/existing-series/batch/new-series workflow families or choose between synchronous and asynchronous thumbnail ingestion solely from static caller counts. Those areas need separate behavior-level consolidation to avoid another functionality regression.

## Android

Application name/version remain `Mreader` / `ver.1.1.0`; build code is **484**.
