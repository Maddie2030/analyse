# Reading evidence during upgrade and restore

This is the RC4.85 source design and operator contract, not a qualified release procedure. Actual PostgreSQL migration, service and restore rehearsals remain required before deploying this checkout.

## One migration executor

`ops/migrate/apply.sh` renders the complete migration set before opening a PostgreSQL connection. Missing or empty inputs stop before SQL runs. One psql session takes advisory lock `(77160485, 1)`, checks each filename in `schema_migrations`, and runs each pending migration and its ledger insert in one transaction. The lock is released when the connection ends, including on errors.

The migration container and backup agent both include this runner and the preservation SQL. `ops/migrate/run.sh` handles readiness and connection configuration; the backup agent supplies its isolated restore candidate's connection. `scripts/migrate.sh` delegates to the hybrid stateful startup path, which requires a verified host-local pre-upgrade bundle even when scheduled backups are disabled. A custom Compose override is rejected rather than silently selecting a different database.

This lock serializes migration executors. It does **not** stop old Kubernetes writers or drain legacy Redis messages. The combined upgrade still needs an orchestrated maintenance window: stop old writers/consumers, capture and verify the safety bundle, preserve and migrate, validate data and grants, then start current services. The preservation transaction locks the relevant source tables during its own copy/validation interval only.

## Evidence rules

Before either pending historical migration 047 or 048, the runner injects `db/upgrade/preserve-reading-evidence.sql` in that migration's transaction. The shipped SQL files remain unchanged.

| Surviving source | Canonical result |
|---|---|
| Exact user/series/chapter checkpoint | Same chapter's page and scroll; legacy completion only from that chapter's page count |
| Last-open chapter | Exact legacy chapter evidence and original event timestamp |
| Independent furthest chapter without exact evidence | `chapter_reads.provenance='migrated_reach'`; no checkpoint or completion |
| Existing exact ledger row at the furthest chapter | Existing exact evidence wins; it is not replaced by inference |
| Null chapter link from a deleted target | No replacement chapter or intervening read markers are invented |

The hook snapshots legacy inputs into temporary tables, validates identities, copies and verifies the canonical evidence, then empties the old rows. This prevents 047/048 from assigning chapter A's checkpoint to chapter B. Their original table drop, all copied evidence and the `rc485_reading_evidence_preserved_v1` marker commit or roll back together. No permanent duplicate history table remains.

Migration 051 owns the one-time surviving-checkpoint repair. Migration 052 owns the provenance-aware view and inferred-evidence constraint. Resume selection uses exact evidence only, with deterministic timestamp/chapter ties. Reach-only series retain their furthest position in Library All, Updates and Caught up, but do not gain an exact History entry, Recently Opened timestamp or read/completed marker. On a real open, Progress converts the inferred row into observed evidence using the actual event time. The explicit legacy maintenance drain also promotes only an exact delivered chapter event; it is not a normal runtime writer.

Already-retired legacy evidence cannot be recovered from a migration ledger alone. If 047 previously removed the only furthest value or original checkpoint association, inspect a selected verified pre-upgrade backup in isolation. Forward repair uses surviving evidence and emits a notice when no preservation marker exists; it cannot certify old legacy rows or reconstruct information that is gone. RC4.81 and the supplied RC4.84 variants are the supported continuity sources; older schemas need separate qualification.

## Qualification

The shell runner has executable standard-library tests. The actual SQL tests require `psql` and an explicitly supplied `MREADER_TEST_POSTGRES_DSN` with permission to create disposable test databases. Each case creates its own randomly named database and drops only that database. They exercise the real runner, shipped migration bodies and production Smart Library SQL, including rollback and two concurrent executors.

```bash
python3 -m unittest discover -s tests/regression -p test_migration_runner.py -v
python3 -m unittest discover -s tests/regression -p test_reading_upgrade_postgres.py -v
```

Without the test DSN or PostgreSQL client, the second command reports skipped cases. That is a blocked acceptance gate, not evidence that migration or restore works. `tests/api/test_26_reading_commands.py` additionally covers an inferred chapter's first real open through the actual Progress API.

Outstanding combined-release gates include all uploaded-version/fresh-install rehearsals, old-writer quiescence and stream drain ordering, runtime database grants/readiness, Catalog publication and deletion effects, complete logical/physical restore, and the legacy operator/catalog recovery entry points' backup and storage alignment.
