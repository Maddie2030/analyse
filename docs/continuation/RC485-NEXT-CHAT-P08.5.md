# RC4.85 next-chat start — P08.5 verified recovery import/inventory/pins/retention

This is the compact continuation entry point after P08.4 canonical database protection facade extraction was source-qualified. The canonical tracker, continuation manifest, capability matrix and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P08.4 source checkpoint: `c8a7c524f90c863b7a6fabb32802a4d457c72802`
- P08.3 source checkpoint: `c5e686678c1f636d4337d2fc5852e72c54271ebb`
- P07.5 source checkpoint: `26d80a1fa040304be770a9ee14a4be53faafb047`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P09.1/scoped-secret prerequisite: `0f1fadb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

If the active workspace is missing, materialize the Library recovery-current package, verify its SHA-256 and embedded all-refs Git bundle, restore every ref including `refs/stash`, switch to `sequential/p06.4-caller-cutover`, and verify the recorded tracker HEAD before editing.

## P08.4 source-qualified contract to preserve

`c8a7c52` establishes these facade boundaries:

1. `/api/admin/database` is the canonical admin database-protection namespace; admin Caddy routes it explicitly and the user gateway denies it.
2. Frontend callers and API coverage use the canonical namespace; legacy `/api/scraper/admin/database*` aliases are retired.
3. `database_facade.py` is only an HTTP/admin facade: the existing `database_operations` queue, recovery catalog and backup-agent restore engine remain authoritative.
4. Scraper staging initialization may degrade without preventing the facade process from starting; scraper readiness remains false when staging is unavailable.
5. P08.3 opaque-ID download bridge, scoped credential, host-root ownership, no-public-bridge-route and no-Kubernetes-root-mount guarantees remain unchanged.
6. No second recovery backend, queue, catalog or restore engine was introduced.

Fresh exact-tree source evidence before the source commit: 242 dependency-light regression tests with 10 intentional skips; focused P08.3/P08.4 10/10; 18/18 runnable Scraper tests; database-protection static contract; API ownership, WebP and 136/136 route audits; changed Python compilation; `git diff --check`; Ripwire `gating=0`.

Known environment blocks remain blocks: Scraper hardening lacks `selectolax`; local Go is 1.23.2 while Catalog requires >=1.25; frontend `node_modules` is absent; `asyncpg` and `psycopg` are absent; Docker is absent; P06.3 PostgreSQL qualification remains deferred/unexecuted by explicit prior decision.

## Exact next product lane

**P08.5 — explicit verified old-bundle import, rebuildable/paged recovery inventory, validation, active pins and retention safety.**

Required direction from the canonical plan:

1. Map current backup-agent catalog formats, historical/NAS bundle forms, inventory rebuild behavior, retention logic and all source/safety-pin consumers before editing.
2. Add explicit import of verified old NAS bundles; do not silently discover or trust arbitrary host paths.
3. Reject invalid checksum, incompatible major version and unsafe/path-escaping bundle metadata before catalog admission.
4. Keep inventory rebuildable from verified artifacts and add bounded paging rather than loading unbounded history into the admin facade.
5. Model active source/safety pins explicitly so retention cannot delete an in-use source, pre-restore safety point or the last verified recovery point.
6. Use UTC-safe retention semantics and preserve the existing single catalog/queue/restore engine.
7. Preserve P08.3 private bridge and P08.4 canonical facade contracts; do not broaden into P08.6+ live restore fencing/cutover qualification before P08.5 is source-qualified.

Start with Ripwire mapping for `database_recovery_points`, catalog rebuild/import, manifest/checksum/version validation, retention pruning, active restore/drill source selection, safety backup pins, old NAS bundle handling and admin inventory paging. Write RED validation/retention/pin tests before production edits.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.5 recovery import old NAS bundle inventory paging checksum version path validation source safety pins UTC retention last verified point'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
