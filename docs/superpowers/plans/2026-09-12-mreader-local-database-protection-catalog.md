# MReader Host-Local Database Protection Catalog Plan

> Status: approved architecture, implementation checkpoint in progress. This plan changes storage and inventory only; it deliberately preserves the existing guarded restore/drill/cutover engine.

## Goal

Make the resolved host directory `MREADER_DB_PROTECTION_ROOT` the canonical durable location for PostgreSQL dumps and snapshots, expose those verified artifacts to the admin UI through an opaque catalog, and remove the database-protection runtime's dependency on SeaweedFS/NAS paths.

## Ownership

- The host recovery directory owns backup bytes, manifests, checksums, and recovery markers.
- The backup agent is the only writer/scanner of that directory.
- `database_recovery_points` is a rebuildable inventory projection used by the Admin API; it never owns backup bytes.
- `database_operations` remains the only queue for backup, drill, and production-restore commands.
- The browser receives opaque recovery IDs and safe metadata only. It never receives a host path or internal filename.
- The existing restore validation, pre-restore safety backup, cutover, rollback, and restart-recovery logic remains the single restore engine.

## Canonical layout

```text
<host-root>/
  dumps/
    automatic/<recovery-id>/
    manual/<recovery-id>/
    pre-upgrade/<recovery-id>/
    pre-restore/<recovery-id>/
  snapshots/<recovery-id>/
  state/
  staging/
```

Each published recovery-point directory is immutable and contains its data artifact, globals where applicable, `manifest.json`, and `checksums.sha256`. Publication is a same-filesystem rename after validation.

## Retention

- Logical dump bundles: 4 days.
- Physical snapshot bundles: 2 days.
- A bundle involved in an active operation is not pruned.
- Invalid or incomplete bundles are excluded from the catalog and reported in backend diagnostics; they are not silently treated as recovery points.

## Work sequence

### 1. Storage contract and deployment

- Add a read/write bind of the resolved host root to the backup agent only.
- Replace the named backup spool with subdirectories under that bind.
- Change retention defaults to 4/2 days in Compose, application configuration, and `.env.example`.
- Keep protected-media SeaweedFS configuration untouched; only PostgreSQL protection leaves NAS storage.

### 2. Recovery-point projection

- Add `database_recovery_points` with opaque ID, internal relative target, kind, timestamps, size, checksum, version, verification state, and last-seen timestamp.
- Do not persist absolute host paths.
- Add indexes for newest-first catalog reads and verification state.
- Make the backup agent rescan manifests on startup and each scheduler pass, upserting valid bundles and retiring entries no longer present.

### 3. Local storage adapter

- Implement category-to-directory mapping and strict target validation.
- Implement atomic publish, checksum verification, inventory scan, safe copy-to-staging, and retention pruning.
- Reject symlinks, traversal, unexpected filenames, incomplete checksums, and manifests whose declared artifact does not match the bundle.
- Generate both full database dump and PostgreSQL globals for logical bundles.

### 4. Preserve the restore engine

- Replace only `download_verified_backup` with a local verified-copy adapter.
- Preserve snapshot isolation/conversion, logical drill, pre-restore safety backup, migration validation, cutover, rollback, and recovery markers.
- Resolve operation targets from the inventory projection, but revalidate the manifest and bytes at execution time.

### 5. Admin API and UI catalog

- Read the catalog from `database_recovery_points`, not a remote `index.json`.
- Keep the existing opaque identifier contract for list, download, drill, and restore.
- Stream downloads through the backend from a revalidated local target.
- Present the compact recovery-point table and keep operational diagnostics collapsed.

### 6. Retire duplicate and legacy paths

- Route the Dashboard shortcut through `database_operations`.
- Remove `backup_requests` only after its callers and pending rows are migrated or explicitly drained.
- Remove PostgreSQL-backup NAS proof/index configuration and tests without changing media-storage NAS behavior.

## Verification gates

- Unit tests for category mapping, traversal/symlink rejection, manifest/checksum validation, atomic publication, and 4/2-day pruning.
- API contract tests proving paths/filenames remain private and opaque IDs resolve correctly.
- Static deployment tests proving one explicit host bind and no named backup spool.
- Runtime capture of a logical bundle against PostgreSQL, followed by `pg_restore --list` and an isolated restore drill.
- Runtime physical snapshot capture and isolated snapshot-to-logical restore drill.
- Failure injection: corrupt checksum, missing manifest, interrupted publish, removed bundle, failed pre-restore backup, and restart during cutover.

No production restore is executed as part of an ordinary development test. It remains an explicit operator acceptance test with disposable data first.
