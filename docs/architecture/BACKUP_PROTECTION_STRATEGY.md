# MReader PostgreSQL backup protection strategy

## Goal

A Docker Desktop PostgreSQL volume must never be the only copy of MReader metadata. Recovery points are written to the external NAS SeaweedFS filer and verified independently.

## Layers

### Daily logical protection

The scheduler is calendar-day based, not clock based. On startup and continuously while online, it checks whether a successful logical backup already exists for the current `POSTGRES_BACKUP_TZ` date. If none exists, it creates a custom-format `pg_dump` immediately. Logical recovery points are retained for 7 days by default.

A successful admin/manual logical backup also satisfies that day's protection requirement. If the manual backup ran first, no additional automatic daily dump is created. Manual backups requested later remain allowed as intentional extra recovery points.

### Physical snapshot

A transaction-consistent `pg_basebackup -X stream` physical snapshot is due after `POSTGRES_BACKUP_SNAPSHOT_EVERY_DAYS` (default 2) has elapsed since the last successful snapshot. If the system was offline when it became due, the snapshot runs when the backup agent next starts. Retention defaults to 14 days and transfer is rate-limited to 32 MiB/s.

### Pre-upgrade protection

Every `hybrid-up.sh` creates a separately retained verified logical dump before migrations. Deployment stops before migrations if this recovery point cannot be verified on NAS.

### Restore verification

A weekly non-destructive drill downloads the latest verified logical recovery point, validates checksum/archive structure, restores into a temporary database, checks the restored DB, and drops the temporary DB.

## Admin control

The Admin Dashboard can request a backup without exposing Docker APIs to Kubernetes. The request crosses the boundary through PostgreSQL:

```text
Admin UI
   -> scraper-service API
   -> backup_requests (queued)
   -> host backup_agent claims row
   -> pg_dump
   -> NAS SeaweedFS + checksum verification
   -> backup_requests (verified/failed)
   -> UI status/history
```

Only one manual database backup may be queued/running. Concurrent admin clicks are coalesced.

## Identification

Filenames contain backup type, database, local date/time, timezone, release and short unique ID. Manifests additionally contain UTC/local timestamps and trigger source (`automatic`, `admin`, `upgrade`, `restore`).

Examples:

```text
mreader-daily-manhwa-2026-09-04_20-37-04_IST-v1.3.0-rc4.36-a1b2c3d4-auto-window.dump
mreader-manual-manhwa-2026-09-04_14-42-19_IST-v1.3.0-rc4.36-b2c3d4e5-admin-1234abcd.dump
mreader-snapshot-manhwa-2026-09-06_09-05-11_IST-v1.3.0-rc4.36-c3d4e5f6.tar
```

## Retention

| Type | Default |
|---|---:|
| Daily + manual logical backups | 7 days |
| Physical snapshots | 14 days |
| Pre-upgrade backups | latest 5 |
| Pre-restore backups | safety copies |

## Health and failure visibility

The backup agent becomes unhealthy when daily protection is stale or the latest physical snapshot attempt failed after the last successful snapshot. Backup success requires NAS upload and checksum verification, not merely a successful local command.

Scheduler state is reconstructed from NAS indexes when local state markers are missing, preventing unnecessary duplicate logical dumps after a local spool reset.

See `docs/operations/POSTGRES_BACKUP_AND_RESTORE.md` for commands and restore procedures.
