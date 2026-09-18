# NAS SeaweedFS setup

This document describes the current topology. Historical Docker-Desktop-to-NAS export helpers are no longer shipped because the application now treats the NAS as permanent production storage and Docker named volumes as temporary scraper staging.

## Storage roles

| Data | Storage |
| --- | --- |
| Raw scraped pages awaiting review | Docker named volume `mreader_scraper_staging` on the application host |
| Published reader assets/covers | SeaweedFS Filer/volumes on the NAS |
| Workflow/catalog metadata | PostgreSQL |
| Queues/cache | RabbitMQ / Redis/Valkey |

## NAS deployment

On the Linux NAS:

```bash
cd ops/nas-seaweedfs
cp .env.example .env
# edit SSD/HDD paths and resource limits
docker compose up -d
```

Verify:

```bash
../../scripts/storage/nas-status.sh
```

## MReader application deployment

In the application `.env`:

```env
NAS_SEAWEEDFS_HOST=<nas-address>
NAS_SEAWEEDFS_PORT=8888
SCRAPER_STAGING_VOLUME_NAME=mreader_scraper_staging
```

Start using the maintained Bash launcher:

```bash
./hybrid-up.sh
```

The launcher validates NAS reachability, repairs scraper staging-volume ownership, applies database migrations, and starts the selected Compose topology. Host Python is not required.

## Verification

```bash
./scripts/storage/verify-nas-storage.sh
./scripts/storage/verify-existing-objects-on-nas.sh
./scripts/diagnose-scraper-staging.sh nas
```

`diagnose-scraper-staging.sh` confirms all scraper/lifecycle processes see the same Docker volume and spool marker.

## Data safety

Normal `docker compose down` preserves the named staging volume. `docker compose down -v` removes named volumes and must not be used when unpublished staging must survive.

Final NAS objects are deleted through lifecycle jobs only after canonical PostgreSQL state is checked. Raw scraper staging is removed only after successful publication/cancellation/acknowledgement cleanup according to the lifecycle state machine.
