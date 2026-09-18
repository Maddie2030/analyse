# RC4.84 consolidation audit

## Objective

Preserve the RC4.81 behavioral contract while keeping RC4.83's cleaner current-only runtime ownership. Historical compatibility belongs in explicit upgrade/recovery tooling, not normal service request paths.

## Correct RC4.83 improvements retained

- Reader uses one chapter allow-list grant and a chapter-scoped refresh endpoint.
- Protected-page runtime is v4 only.
- Progress uses `reading_progress` for resume and `chapter_reads` for exact history/completion.
- Social Smart Library/History derive from canonical Progress-owned state.
- Media job truth is PostgreSQL `media_operations`; RabbitMQ is transport.
- Social viewer-state reuses the shared public-metrics aggregate.
- Session contract is current-only.
- Lifecycle and Reader share explicit cache-Redis grant ownership.
- Admin mobile Reader routing uses the user-namespace Reader service.
- Only the Docker Desktop hybrid deployment model remains executable.

## RC4.84 repairs

### Stateful continuity

RC4.83's fixed volume names were safe only for fresh installs. RC4.84 records one authoritative volume name per stateful component during upgrade. PostgreSQL adoption validates PGDATA and refuses ambiguous dual-live state.

### Catalog/NAS disaster recovery

The catalog-only recovery subsystem restores the metadata required to make existing NAS media meaningful again while deliberately excluding old personal/operational state. NAS is validation-only during recovery.

### Low-risk API alias removal

Removed Catalog `/dashboard`, Progress PUT, scraper `publish-status`, and Realtime `/ws` after confirming current Web/Android/tests/load tooling have canonical replacements.

## Remaining review areas

- Generic scraper endpoints coexist with draft/batch/series-draft workflows. They are not removed until a capability-level consolidation proves equivalence.
- Synchronous series-cover handling and asynchronous thumbnail jobs both remain; choose one only after product latency/operational requirements are explicit.
- Some frontend API-client methods have no direct Web caller but may still represent Android/admin/test/server capability. Caller analysis is required before removal.
