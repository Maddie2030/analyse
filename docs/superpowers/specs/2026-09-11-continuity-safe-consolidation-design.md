# MReader continuity-safe consolidation design

## Goal

Keep the RC4.83 current-only runtime ownership model while restoring safe upgrade/data continuity for existing Docker volumes and historical PostgreSQL backups without reviving stale runtime compatibility paths.

## Runtime principles

- One current API/state owner per capability.
- Historical compatibility is isolated to bootstrap/recovery tooling.
- NAS SeaweedFS published objects are immutable/read-only during recovery.
- PostgreSQL catalog metadata is the authoritative mapping from series/chapter/page identity to NAS object paths and v4 decoding metadata.
- Recovery imports only catalog/taxonomy/page metadata; personal/social/operational data is not imported.

## Stateful upgrade continuity

Docker Compose volume names are parameterized through `HYBRID_*_VOLUME_NAME`. A one-time adoption helper runs before deployment. It selects a single authoritative volume and persists that selection in `.env`. PostgreSQL candidates are validated as PGDATA. Ambiguous dual-live volumes fail closed.

## Catalog recovery

Supported donor formats for `catalog-v4-v1`:

- PostgreSQL custom-format `.dump`.
- MReader physical snapshot `.tar` containing `base.tar.gz` and `pg_wal.tar.gz`.

The recovery process boots an isolated PostgreSQL donor, verifies the required seven tables/columns, rejects non-v4 pages or broken FK identity, exports canonical CSV staging, validates every primary NAS page object read-only, and only then imports into an empty current catalog in one transaction.

Imported tables: `series`, `chapters`, `pages`, `genres`, `series_genres`, `tags`, `series_tags`.

Excluded donor state: accounts, social state, reading state, notifications, scraper jobs, Media jobs, caches, queues, and old runtime coordination.

## API cleanup boundary

Remove only aliases proven unused by current consumers:

- Catalog `/dashboard`.
- Progress PUT mutation.
- Scraper `publish-status`.
- Realtime `/ws`.

Do not remove generic scraper/draft/batch/new-series workflows or thumbnail execution models until behavior-level tests prove equivalence.

## Validation

Release qualification must cover canonical route ownership, Web/Android reader parity, two-table reading state, PostgreSQL-only Media job status, Social aggregate ownership, cache-Redis grant ownership, twin-plane deployment wiring, volume adoption behavior, and catalog recovery safety rules.
