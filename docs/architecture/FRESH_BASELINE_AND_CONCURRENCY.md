# Fresh baseline, concurrency and queue scaling — RC4.28

This release assumes there is no published production content that requires legacy codec/backfill recovery.

## Cleanup decisions

- Removed the one-off page encoding backfill command/module.
- Removed the legacy transient publish recovery shim.
- Removed old RC4.18/RC4.20 upgrade-only documents from the package.
- Disabled legacy remote staging fallback by default.
- Kept all current database tables because each still has runtime consumers; the scraper ledgers are durability/idempotency state, not historical clutter.
- Kept the migration ledger because it is the supported reproducible schema builder.

## Multi-admin concurrency

RabbitMQ distributes compact durable job references. PostgreSQL remains canonical. Different series can run in parallel, while operations for the same series are protected by the existing `scraper-publish:<draft_id>` advisory lock and row-level state transitions.

The Docker Desktop hybrid profile permits two `scraper-series-worker` replicas through KEDA. Each pod has two publish/chapter-publish consumers and a shared concurrency semaphore of two. This permits at least two separate series to stage/publish concurrently while bounding RAM/CPU on the 16 GB workstation.

KEDA publish queue targets are one queued job per desired replica, so two separate queued series can promptly request two replicas.

## End-to-end dataflow

The old admin UI requested exactly 120 events and displayed that array length as if it were the total. RC4.28 returns the exact DB count and cursor-paginates the timeline. The UI polls the newest 250 events and can load older events in stable pages without offset drift.

## PostgreSQL physical backups

`pg_basebackup` now uses a dedicated `mreader_backup` replication role. `hybrid-up.sh` repairs/creates the role and a SCRAM `pg_hba.conf` replication rule in the existing PostgreSQL volume before backup work begins. Snapshot failure is reflected in the backup-agent health state until a later physical snapshot succeeds.
