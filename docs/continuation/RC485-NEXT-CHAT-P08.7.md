# RC4.85 next-chat start — P08.7 actual PostgreSQL dump/snapshot drill rehearsal

This is the compact continuation entry point after P08.6 restore CLI/catalog-only safeguard alignment was source-qualified. The canonical tracker, continuation manifest, capability matrix and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P08.6 source checkpoint: `f051fc732035cd0ded878ad2edc720939552dbbe`
- P08.5 source checkpoint: `d26448681de021dadde61d01f9e2790db9341189`
- P08.4 source checkpoint: `c8a7c524f90c863b7a6fabb32802a4d457c72802`
- P08.3 source checkpoint: `c5e686678c1f636d4337d2fc5852e72c54271ebb`
- P07.5 source checkpoint: `26d80a1fa040304be770a9ee14a4be53faafb047`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P09.1/scoped-secret prerequisite: `0f1fadb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

## P08.6 source-qualified contract to preserve

`f051fc7` establishes these restore-source/scope boundaries:

1. Normal restore accepts only `latest`, `latest-snapshot` or an opaque `bkp_<24 hex>` public recovery ID; arbitrary category/filename/host-path selectors are not the canonical operator contract.
2. Opaque IDs resolve to exactly one verified bundle inside `local-recovery-store.sh` before confirmation/quiescence, then reuse the existing backup-agent restore engine.
3. Catalog-only recovery accepts only an opaque verified ID, stages its donor under the canonical recovery root, keeps NAS read-only and preserves the exact empty-target seven-table `catalog-import.sql` scope.
4. Catalog-only pre-import safety capture is created by `backup_agent pre-restore` and recorded by opaque safety ID; the old direct `pg_dump` path under `backups/recovery/` is retired.
5. P08.3–P08.5 private bridge/facade/import/pin/retention/paging boundaries remain unchanged; no second recovery queue/catalog/restore engine was added.

Fresh exact-tree evidence before source commit: 258 dependency-light regression tests with 10 intentional skips; focused P08.6 5/5; all 11 recovery/database shell contracts; 18/18 runnable Scraper tests; API ownership, WebP and 136/136 route audits; changed shell/Python syntax and `git diff --check`; Ripwire `gating=0`.

Known environment blocks remain blocks: Scraper hardening lacks `selectolax`; local Go is 1.23.2 while Catalog requires >=1.25; frontend `node_modules` is absent; `asyncpg` and `psycopg` are absent; Docker is absent; P06.3 PostgreSQL qualification remains deferred/unexecuted by explicit prior decision.

## Exact next product lane

**P08.7 — rehearse logical dump and physical snapshot recovery using actual PostgreSQL tools.**

Required direction from the canonical plan:

1. Map the existing dump/snapshot drill runners, restore staging, current migrations/grants, validation SQL and NAS/media reference checks before editing.
2. Exercise logical dump and physical snapshot recovery with actual PostgreSQL tooling/current schema and grants when a suitable runtime is available; preserve the same verified opaque-ID/root/engine boundary established by P08.6.
3. Validate restored row counts, foreign-key integrity, database encoding and required schema/migration state; do not reduce qualification to archive-format checks alone.
4. Validate SeaweedFS/NAS references read-only and report missing media; do not mutate NAS during the drill.
5. Report additional databases/cluster objects outside the configured logical MReader backup scope rather than silently implying they were restored.
6. Preserve P08.3–P08.6 contracts and stay within P08.7. Live writer/cutover generation fencing, interruption recovery and stale-work reconciliation are P08.8.

Start with Ripwire mapping for `verify-restore-latest`, snapshot drill paths, migration runner, grants, validation queries, row/FK/encoding checks, SeaweedFS read-only verification and extra-database discovery. Write RED drill/runtime contracts before production edits.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.7 PostgreSQL logical dump physical snapshot drill migrations grants row FK encoding NAS read only missing media extra databases'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
