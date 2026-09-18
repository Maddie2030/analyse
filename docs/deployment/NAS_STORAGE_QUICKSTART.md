# NAS storage quick start

Full setup guide: `docs/deployment/NAS_SEAWEEDFS_SETUP_AND_MIGRATION.md`.

The current layout is deliberately simple:

```text
MReader host Docker volume  -> unpublished scraper staging
NAS SeaweedFS               -> final published media
PostgreSQL                  -> canonical metadata/state
```

Configure `NAS_SEAWEEDFS_HOST` and `NAS_SEAWEEDFS_PORT` in `.env`, then:

```bash
./hybrid-up.sh
./scripts/storage/verify-nas-storage.sh
./scripts/storage/verify-existing-objects-on-nas.sh
./scripts/diagnose-scraper-staging.sh nas
```

The old one-off Windows Docker-Desktop Seaweed export/import scripts are no longer part of the normal application package. For an existing SeaweedFS migration, follow the preservation procedure in the full NAS guide or migrate the storage server independently before switching the application URL.

Never use `docker compose down -v` during preservation-sensitive work.
