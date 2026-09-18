# RC4.85 next-chat start — P08.6 restore CLI/catalog-only safeguard alignment

This is the compact continuation entry point after P08.5 verified recovery import/inventory/pins/retention was source-qualified. The canonical tracker, continuation manifest, capability matrix and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P08.5 source checkpoint: `d26448681de021dadde61d01f9e2790db9341189`
- P08.4 source checkpoint: `c8a7c524f90c863b7a6fabb32802a4d457c72802`
- P08.3 source checkpoint: `c5e686678c1f636d4337d2fc5852e72c54271ebb`
- P07.5 source checkpoint: `26d80a1fa040304be770a9ee14a4be53faafb047`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P09.1/scoped-secret prerequisite: `0f1fadb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

## P08.5 source-qualified contract to preserve

`d264486` establishes these recovery inventory/retention boundaries:

1. Legacy/NAS recovery enters only through an explicit operator-selected import of an already checksum-verifiable bundle; import re-verifies and copies into the canonical local store with local provenance and never treats NAS as a second runtime authority.
2. Tampered bundles, unsafe/symlinked roots and unsupported PostgreSQL majors are rejected before canonical admission.
3. Retention uses capture-completion UTC and protects active restore/drill sources, unresolved cutover markers, current pre-upgrade/pre-restore safety points and the last verified recovery point; active-pin query failure is fail-closed.
4. `database_recovery_points` remains a rebuildable projection; the canonical facade/admin UI use bounded opaque keyset paging rather than loading unbounded history.
5. P08.3 private download and P08.4 `/api/admin/database` facade boundaries remain unchanged; one queue/catalog/restore engine remains authoritative.

Fresh exact-tree evidence before source commit: 253 dependency-light regression tests with 10 intentional skips; focused P08.5 11/11; all 10 recovery/database shell contracts; 18/18 runnable Scraper tests; API ownership, WebP and 136/136 route audits; changed Python/shell syntax and `git diff --check`; Ripwire `gating=0`.

Known environment blocks remain blocks: Scraper hardening lacks `selectolax`; local Go is 1.23.2 while Catalog requires >=1.25; frontend `node_modules` is absent; `asyncpg` and `psycopg` are absent; Docker is absent; P06.3 PostgreSQL qualification remains deferred/unexecuted by explicit prior decision.

## Exact next product lane

**P08.6 — align normal restore CLI and catalog-only recovery safeguards with the same root/engine contract.**

Required direction from the canonical plan:

1. Map `postgres-restore.sh`, backup-agent restore entry points, `scripts/recovery/catalog-restore.sh`, root resolution, opaque-ID resolution and every caller before editing.
2. Preserve catalog-only recovery's empty-target rule and exact seven-table scope; it is a narrow catalog recovery mechanism, not a full MReader/PostgreSQL restore.
3. Align normal restore CLI and catalog-only recovery on the same canonical root/verified-source contract without creating another queue/catalog/restore engine.
4. Reject unsafe/path-escaping identifiers and ambiguous roots before any destructive action.
5. Preserve P08.3–P08.5 private bridge/facade/import/pin/retention boundaries.
6. Stay within P08.6; actual PostgreSQL dump/snapshot rehearsal is P08.7 and live writer/cutover fencing is P08.8.

Start with Ripwire mapping for `postgres-restore.sh`, `restore_backup_cli`, `catalog-restore.sh`, seven-table imports, empty-target checks, root resolution, recovery IDs and destructive restore callers. Write RED scope/root/empty-target tests before production edits.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.6 restore CLI catalog-only recovery empty target seven tables root engine opaque id postgres restore safeguards'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
