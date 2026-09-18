# Catalog-only recovery

MReader recovery is intentionally separate from normal runtime compatibility. The current application uses only the current schema/API contracts; historical backups are normalized by this on-demand recovery path.

## Scope

Imported from a supported donor database:

- `series`
- `chapters`
- `pages` including exact `image_path`, responsive path/dimensions, v4 grid metadata, and `encoding_seed`
- `genres` and `series_genres`
- `tags` and `series_tags`

No account, social, reading-progress, notification, queue, worker, scraper-operation, or Media-job state is imported.

## Safety model

**NAS SeaweedFS is read-only during recovery.** The recovery command checks every primary published page object before import and never issues object DELETE, MOVE, rename, or re-encode operations. Missing primary objects block import. Missing responsive derivatives or covers are reported as warnings because the canonical primary protected page remains readable.

The target Catalog must be empty. The tool refuses to merge into an existing catalog. Before the transactional import it asks the existing backup agent to create a verified `pre-restore` safety recovery point in the same canonical host-local recovery store.

## Supported sources

The first recovery contract, `catalog-v4-v1`, accepts only a **verified recovery point already admitted to the canonical host-local recovery store**, selected by its opaque `bkp_…` public ID. The verified bundle may contain either:

1. a PostgreSQL custom-format logical dump with the current v4 catalog columns; or
2. an MReader PostgreSQL 16 physical snapshot containing `base.tar.gz` and `pg_wal.tar.gz`.

Legacy/NAS bundles must first pass the explicit verified import workflow; catalog recovery never scans NAS backup directories as a second runtime authority. Unknown schemas are rejected rather than guessed. Future schema changes should add a new explicit adapter/contract instead of adding old-schema branches to runtime services.

## Check only

```bash
./scripts/recovery/catalog-restore.sh --backup-id bkp_<24-hex> --check
```

The command re-resolves and checksum-verifies the opaque ID through the canonical recovery store, stages the artifact under that store, starts an isolated donor PostgreSQL container/volume, validates the donor schema and v4 page metadata, checks NAS media objects read-only, writes a report to `backups/recovery/`, and destroys the temporary donor/staged copy. It does not modify current PostgreSQL.

## Import

After `--check` succeeds:

```bash
./scripts/recovery/catalog-restore.sh --backup-id bkp_<24-hex> --import
```

The import path:

1. performs one-time stateful-volume adoption;
2. starts the current PostgreSQL service;
3. applies current migrations;
4. refuses to continue if current Catalog already contains series;
5. creates a local pre-import database backup;
6. loads only the catalog/taxonomy CSV staging data;
7. validates foreign-key identity and v4 protected-page metadata again;
8. inserts all seven catalog tables in one PostgreSQL transaction;
9. verifies final series/chapter/page counts.

Existing NAS object paths and encoding seeds are preserved byte-for-byte.
