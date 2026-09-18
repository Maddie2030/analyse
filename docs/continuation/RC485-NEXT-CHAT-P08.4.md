# RC4.85 next-chat start — P08.4 recovery facade extraction

This is the compact continuation entry point after P08.3 private recovery download was source-qualified. The canonical tracker, continuation manifest, and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P08.3 source checkpoint: `c5e686678c1f636d4337d2fc5852e72c54271ebb`
- P07.5 source checkpoint: `26d80a1fa040304be770a9ee14a4be53faafb047`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P09.1/scoped-secret prerequisite: `0f1fadb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

If the active workspace is missing, materialize the Library recovery-current package, verify its SHA-256 and embedded all-refs Git bundle, restore every ref including `refs/stash`, switch to `sequential/p06.4-caller-cutover`, and verify the recorded tracker HEAD before editing.

## P08.3 source-qualified contract to preserve

`c5e6866` establishes these recovery-download boundaries:

1. Recovery bytes and the database-protection root remain owned only by the host-local backup agent.
2. The private bridge is read-only, requires the scoped recovery bridge credential, and accepts only opaque `bkp_<24 hex>` recovery IDs.
3. Scraper proxies the verified stream for the authenticated admin surface without learning or exposing host filesystem paths.
4. Neither public gateway exposes the bridge directly, and Kubernetes workloads do not mount the host protection root.
5. Bridge staging reuses the existing verified copy-artifact flow and rejects symlinked recovery/staging roots before creating temporary output.
6. The bridge credential is allocated only to the backup-agent/Scraper transport boundary through the existing workload-scoped secret mechanism; frontend/browser workloads do not receive it.
7. The backup agent remains the single recovery-file owner and the existing recovery catalog/queue/engine remains authoritative.

Fresh exact-tree source evidence before the source commit: 237 dependency-light regression tests with 10 intentional skips; 18/18 runnable Scraper tests; recovery-bridge Go tests + vet; 11 targeted backup/deployment/ownership/route/WebP gates; syntax/format/`git diff --check`; Ripwire `gating=0`. One narrow Ripwire acknowledgement records only the intentional evolution of the historical future-secret test.

Known environment blocks remain blocks: Scraper hardening lacks `selectolax`; Catalog Go runtime requires >=1.25 while this sandbox has 1.23.2; frontend `node_modules` is absent; API integration lacks `psycopg`; P06.3 PostgreSQL qualification remains deferred/unexecuted by explicit prior decision.

## Exact next product lane

**P08.4 — extract the recovery/admin database facade from Scraper readiness and move UI/gateway/API together to `/api/admin/database`.**

Required behavior from the canonical plan:

1. Map every existing admin database/recovery consumer before editing: UI, gateway, Scraper readiness, backup-agent catalog/queue, CLI and compatibility aliases.
2. Preserve one `database_operations` queue, one recovery catalog and one restore engine; do not create a second recovery backend.
3. Move the API/gateway/UI contract together to `/api/admin/database` so no layer temporarily invents a competing authority.
4. Preserve the P08.3 opaque-ID private download bridge, scoped credential, host-root ownership, and no-public-route/no-Kubernetes-mount guarantees.
5. Retire old aliases only after all real consumers have moved and replacement behavior is source-qualified.
6. Stay within P08.4; import/pins/fencing/restore qualification remains P08.5+ work.

Start with Ripwire mapping for current `/api/admin/database*` routes, Scraper readiness/database endpoints, frontend callers, gateway mappings, backup-agent queue/catalog calls, CLI operations, and compatibility aliases. Write RED route/consumer/authority tests before implementation.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.4 admin database facade scraper readiness gateway frontend database_operations recovery catalog aliases'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
