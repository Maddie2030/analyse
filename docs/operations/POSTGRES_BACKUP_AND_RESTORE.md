# PostgreSQL Database Protection

RC4.85 source checkpoint: the host-local storage, migration and operator changes are implemented, but the full release is not qualified. See `../qualification/RC485-WORK-IN-PROGRESS.md` for remaining restore, permission, client and deployment gates. The commands below describe the current source interfaces; no live restore has been exercised for this checkpoint.

## Storage ownership

The backup agent owns PostgreSQL recovery bundles under the configured host user's home. SeaweedFS continues to own media storage. Database Protection uses one host-local inventory and `database_operations` queue; it no longer scans a second NAS backup inventory during ordinary runtime.

| Host directory under the recovery root | Contents |
|---|---|
| `dumps/automatic`, `dumps/manual` | Complete application database dumps |
| `dumps/pre-upgrade`, `dumps/pre-restore` | Safety recovery bundles |
| `snapshots` | Physical PostgreSQL snapshots |
| `state` | Scheduler/catalog handoff state and legacy recovery markers |
| `control` | Host-owned restore identity/generation plus v2 cutover journals; private to the backup agent |
| `staging` | Operation-owned temporary work |

`MREADER_DB_PROTECTION_ROOT` defaults to the host user's `.mreader/database-protection` directory. On Linux this is under the actual host home; on Windows/Git Bash the resolver uses the host profile and writes an absolute drive path. Compose mounts the selected root at `/mreader-db-protection`. The backup container's home is never used as the durable root.

The resolver preserves a configured custom root and rejects disagreement between process and saved configuration before starting Docker. Do not change a running installation's root to discover older artifacts: import selected verified legacy bundles through the recovery workflow once that import path is qualified.

Logical bundles contain the full MReader database (`database.dump`), PostgreSQL globals (`globals.sql`), a manifest and checksums. Snapshots contain the physical `pg_basebackup` archive with streamed WAL and verification metadata. Normal application restore uses the selected MReader database; globals support separate disaster recovery. PostgreSQL recovery does not include NAS media bytes, Redis/Valkey sessions or RabbitMQ queues.

## Policy and configuration continuity

Default dump retention is **4 days** and snapshot retention is **2 days**. The initial daily backup schedule, timezone and snapshot cadence remain configurable.

On the first RC4.85 configuration pass, `migrate-known-settings.sh` preserves the original environment in a private `.before-rc485-local-recovery` copy. Missing retention values and known old defaults (7-day dumps / 14-day snapshots) become 4/2. Other configured values remain unchanged. `MREADER_DB_PROTECTION_CONFIG_VERSION=1` records that this migration ran; later administrator choices, including a former default, are not repeatedly reset.

Old NAS backup settings remain dormant configuration evidence for an explicit legacy import. The migration does not rewrite NAS paths or add an obsolete storage-proof requirement. NAS media diagnostics remain in `../deployment/NAS_STORAGE_QUICKSTART.md` and `../deployment/NAS_SEAWEEDFS_SETUP_AND_MIGRATION.md`.

## Operator entry points

```bash
./db-backup.sh status
./db-backup.sh list
./db-backup.sh check-storage
./db-backup.sh manual
./db-backup.sh snapshot
```

`check-storage` invokes the existing backup agent self-test with the selected root. It uses a disposable local write probe and reads database/replication readiness; it does not configure roles, start database dependencies, stop the scheduler or create a backup. The older `scripts/storage/backup-storage-doctor.sh [ENV_FILE]` entry point delegates to this same check and propagates failures.

`self-test` and `repair-replication` are explicit setup/repair commands and can configure the PostgreSQL replication role. Manual backup and snapshot commands pause an existing scheduler while the same agent performs the work. Their root and environment selection are shared with the normal startup path. A selected `MREADER_ENV_FILE` also reaches replication setup.

## Recovery catalog and restore

The Admin Database Protection page displays opaque recovery IDs and browser-safe metadata from the agent's verified local catalog projection. The agent re-resolves the selected artifact before recovery. Internal host directories, filenames and credentials stay out of public responses.

Both logical and snapshot restores use the existing staged restore engine. A physical snapshot is booted in isolation, validated and converted into a logical source before the common cutover path. The engine creates a fresh safety backup and journals cutover/recovery state. Database renames and reconnection steps are not represented as a single atomic transaction.

Upgrade and restore candidates use the same serialized migration executor. The pre-047/048 preservation hook and migration 052 keep checkpoint, exact history and inferred furthest evidence distinct. See `../recovery/READING_UPGRADE.md`.

The source operator restore entry point remains `scripts/backup/postgres-restore.sh`. It resolves the same host-local root and accepts `latest`, `latest-snapshot`, or an opaque `bkp_<24 hex>` recovery ID. Every selector is resolved to one exact verified opaque ID and SHA-256 **before** confirmation/quiescence; bare internal filenames and category/path selectors are not operator restore selectors. Deployment quiescence/restart, NAS reference validation and full dump/snapshot restore still require combined runtime qualification. Do not infer production readiness from a visible Restore button or a source check.

### P08.8 restore fencing and cutover recovery

The backup agent owns a private `control/restore-control.json` record outside PostgreSQL. It contains a stable installation ID, a browser-safe fingerprint (`inst_<16 hex>`) and a monotonic restore generation. The raw installation ID never leaves the host. PostgreSQL's `database_restore_state` row is only a runtime mirror; the host control remains authoritative while PostgreSQL is offline or being replaced.

The exact human confirmation text is:

```text
RESTORE <backup_id> ON <installation_fingerprint> GEN <restore_generation>
```

Admin and CLI restores bind that confirmation to the selected recovery public ID, its verified SHA-256, the installation fingerprint and the expected restore generation. The backup agent re-resolves and rechecks the same tuple when it claims the operation and again immediately before destructive cutover. A source change, installation change or generation change invalidates an earlier confirmation.

Before the first database rename, the agent creates and verifies a `pre-restore` safety bundle. The active v2 cutover journal pins both the exact source recovery ID and the exact safety recovery ID so retention cannot remove either one while the restore remains unresolved. New journals are private files under `control/restore-cutover-<operation_uuid>.json`; legacy spool markers are still recognized only for backward recovery.

The v2 journal phases are:

```text
prepared
rename-live-pending
live-renamed
promote-staged-pending
cutover-live
reconciling
generation-commit-pending
generation-committed
```

The two database renames are journaled separately. On backup-agent restart, recovery combines the journal phase, observed live/old/staged database names, installation fingerprint and host generation. If the host is still on the expected generation, an unstarted cutover is abandoned safely, a first-rename-only interruption is rolled back, and a proven promoted database may be validated/finalized. Once the host generation has advanced to the journal's next generation, restart recovery **never automatically rolls back to the older generation**; it validates/finalizes the committed generation and terminal ledger instead. Any mismatched fingerprint, unexpected generation or ambiguous database-name combination leaves the journal and rollback evidence intact for operator inspection. The agent does not guess.

Before generation commit, restored replay-unsafe work is reconciled transactionally: active ingestion operations are cancelled with revision/lease-generation bumps; queued/retry/processing Media operations are failed with `media_generation` bumps and dispatch/heartbeat ownership cleared; unpublished outbox rows are marked published with `restore_suppressed=true` and the new restore generation. Generation/path-fenced Lifecycle cleanup is intentionally **not** globally cancelled, and the restore path does not flush Redis or purge RabbitMQ. After reconciliation and validation, the database mirror is written, the journal enters `generation-commit-pending`, the host generation advances exactly once, the journal enters `generation-committed`, then terminal ledger/old-database cleanup may complete.

Restore drills are deliberately isolated from this production cutover contract. `postgres-restore-drill.sh` runs the read-only catalog/NAS media check and the existing isolated `restore-drill-public-id` engine only. Drills never create a production pre-restore safety capture, write/update production cutover journals, reconcile production application work, suppress production outbox rows, update the PostgreSQL restore-state mirror or advance the host restore generation.

Private browser download delivery is implemented through the scoped P08.3 recovery bridge and canonical admin facade. The browser receives only the opaque recovery ID/stream; the host recovery root remains owned by the backup agent and is not mounted into Kubernetes or exposed through the media service.

## P09.3 runtime-role reconciliation

The host/bootstrap PostgreSQL identity remains reserved for migrations, role reconciliation, protected recovery, and diagnostics. Runtime workloads receive only their workload-specific DSNs from the P09.1 scoped-secret rollout.

The supported ordering is: **after migrations**, run `scripts/hybrid/reconcile-postgres-roles.sh`; only after that succeeds may workload-specific secret rollout and application restart proceed. The reconciler consumes the same-tree audited `contracts/ownership/postgres-roles.v1.json`, revokes the current runtime surface, reapplies exact grants, and persists role-specific DSNs without printing passwords.

`scripts/hybrid/validate.sh` runs `scripts/run-postgres-role-audit.sh` before Docker/Kubernetes preflight, so static role-policy drift is caught without requiring a live database. The destructive/permission runtime proof is separate: `scripts/test/p09-3-postgres-grants-gate.sh` runs only against an explicitly disposable DSN or an ephemeral PostgreSQL 16 Docker target. `P09.3 POSTGRES GRANTS GATE BLOCKED` is recorded as blocked evidence, never as a pass.
