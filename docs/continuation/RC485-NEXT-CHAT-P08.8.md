# RC4.85 next-chat start — P08.8 write/cutover fencing and interruption recovery

This is the compact continuation entry point after P08.7 PostgreSQL drill qualification was source-prepared. The canonical tracker, continuation manifest, capability matrix and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P08.7 source checkpoint: `8f011179026348e8971745e460a2cb2fac2903c3`
- P08.6 source checkpoint: `f051fc732035cd0ded878ad2edc720939552dbbe`
- P08.5 source checkpoint: `d26448681de021dadde61d01f9e2790db9341189`
- P08.4 source checkpoint: `c8a7c524f90c863b7a6fabb32802a4d457c72802`
- P08.3 source checkpoint: `c5e686678c1f636d4337d2fc5852e72c54271ebb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

## P08.7 source-prepared contract to preserve

`8f01117` keeps the single canonical recovery queue/store/restore engine and adds source-level drill qualification:

1. Opaque `bkp_...` IDs resolve through the verified local store, then logical and snapshot drills reuse `database_operations` and the existing backup-agent engine.
2. Drill candidates receive current migrations and structured validation for row counts, UTF8 database encoding, chapter/page orphan integrity, v4 protected-page encoding, validated foreign keys, latest migration presence, essential CONNECT/series SELECT privileges and extra databases outside the configured logical scope.
3. Physical snapshot drills use an isolated snapshot cluster; snapshot conversion and drill share the same staging/migration preparation rather than duplicating a second engine.
4. `scripts/backup/postgres-restore-drill.sh` composes the existing read-only catalog/NAS media check with the isolated opaque-ID restore drill. It does not import catalog rows or write to NAS.
5. Fresh source evidence: 262 dependency-light regression tests with 10 intentional skips; focused P08.7 4/4; all 11 recovery/database shell contracts; 18/18 runnable Scraper tests; API ownership, WebP and 136/136 route audits; syntax/compile/diff checks; Ripwire `gating=0`.
6. Actual Docker/PostgreSQL drill execution remains **blocked** in this sandbox because Docker is absent. Do not describe P08.7 as runtime-qualified. Other known `selectolax`, Go >=1.25, frontend dependency and `asyncpg`/`psycopg` blockers remain unchanged.

## Exact next product lane

**P08.8 — implement/qualify write fencing, installation-bound confirmation, durable cutover journaling and interruption/stale-work recovery.**

Required direction from the canonical plan:

1. Map every production writer/quiescence boundary and the existing database restore confirmation/cutover-generation model before editing.
2. Bind destructive confirmation to the installation and exact recovery source; reject stale confirmation after source/generation changes.
3. Maintain source and safety pins while restore/cutover is active so retention cannot remove required recovery material.
4. Persist an external cutover journal before destructive rename/cutover steps; interruption/restart must either safely finalize or rollback based on observed database state.
5. Invalidate stale generations and selectively reconcile stale queued/in-flight work after cutover; do not blindly requeue work from the pre-restore generation.
6. A drill must remain isolated: no production messages, Catalog publication effects or Media writes may escape it.
7. Preserve P08.3–P08.7 bridge/facade/import/pin/retention/opaque-ID/catalog-only/drill boundaries and stay within P08.8.

Start with Ripwire mapping for database writers, quiescence/readiness, confirmation tokens, cutover markers, source/safety pins, generation/revision fields, RabbitMQ/worker stale work and post-cutover reconciliation. Write RED interruption/fencing tests before production edits.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.8 write fencing installation confirmation source safety pins cutover journal interruption rollback generation invalidation stale work reconciliation drill isolation'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
