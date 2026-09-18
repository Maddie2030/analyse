# RC4.85 next-chat start — P08.3 private recovery download bridge

This is the compact continuation entry point after P07.5 canonical status/UI convergence was source-qualified. The canonical tracker, continuation manifest, and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P07.5 source checkpoint: `26d80a1fa040304be770a9ee14a4be53faafb047`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P09.1/scoped-secret prerequisite: `0f1fadb`
- Forensic `stash@{0}` remains superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

If the active workspace is missing, materialize the Library recovery-current package, verify its SHA-256 and embedded all-refs Git bundle, restore every ref including `refs/stash`, switch to `sequential/p06.4-caller-cutover`, and verify the recorded tracker HEAD before editing.

## P07.5 source-qualified contract to preserve

`26d80a1` establishes these source/UI boundaries:

1. New-series orchestration has one canonical parent `ingestion_operations` header; subordinate chapter publication operations link via `parent_operation_id`.
2. Discovery/staging/publish/cancel/retry/recovery coordinator transitions synchronize the parent operation projection while editable draft state remains workflow detail rather than a competing status authority.
3. Admin operation/new-series surfaces label canonical operation status/phase separately from workflow detail.
4. Catalog series/chapter DELETE returns `202 Accepted` with `catalog_removed=true`, `storage_cleanup=queued`, and the durable Lifecycle cleanup `job_id`; UI messaging must never equate metadata removal with completed physical deletion.
5. Existing workflow-status and operation-events routes remain because active clients still consume them; the obsolete publish-status alias remains retired.
6. Migration 059 backfills parent headers/child links for existing new-series drafts and is metadata-only.
7. All P06/P07 publication, generation, cancellation, Stage/Retry, cover, and Lifecycle deletion fences remain in force.

Fresh exact-tree source evidence before the source commit: 233 dependency-light regression tests with 10 intentional skips; explicit P07.5 10/10; 18/18 runnable Scraper; 6/6 ingestion-authority; API ownership; 136/136 route audit; WebP audit; changed Python compilation; Go formatting; `git diff --check`; Ripwire `gating=0`. The full static shell runner was attempted but exceeded the 120-second harness limit after its first four cases passed, so it is not a full-pass result.

Known environment blocks remain blocks: Scraper hardening lacks `selectolax`; Catalog Go runtime requires >=1.25 while this sandbox has 1.23.2; frontend `node_modules` is absent; API integration lacks `psycopg`; P06.3 PostgreSQL qualification remains deferred/unexecuted by explicit prior decision. Runtime restart/worker-loss/KEDA/browser proof belongs to P11 and was not claimed by P07.5.

## Exact next product lane

**P08.3 — narrowly authenticated private recovery download.** P08.1/P08.2 host-root/catalog/operator alignment already exist. The workload-scoped secret-selection prerequisite required by P08.3 is reconstructed at `0f1fadb`.

Required behavior from the canonical plan:

1. Keep the existing backup agent as the host-local recovery-file owner.
2. Add a narrowly authenticated **read-only** bridge for recovery download by opaque verified recovery ID.
3. Never expose host filesystem paths to API callers.
4. Do not add a public file route.
5. Do not mount the user's host-home/database-protection root into Kubernetes API pods.
6. Allocate only the minimum credential through the existing workload-specific secret renderer/allowlists; do not restore namespace-wide `.env` exposure.
7. Preserve one recovery catalog/queue/engine; P08.4 facade extraction follows only after the download bridge is source-qualified.

Start with Ripwire mapping for `admin_download_database_backup`, `database_operations`, backup-agent endpoints/transport, opaque recovery IDs, DB-protection root resolution, gateway exposure, deployment mounts, and scoped secret renderer consumers. Write RED source/behavior/security tests before implementation.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
git rev-parse refs/stash
ripwire . --handoff
ripwire . --for='P08.3 private recovery download backup agent opaque recovery id database protection host path secret scope gateway mount'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. this file

Mandatory persistence rule remains in force: after each meaningful source + tracker checkpoint, create `git bundle --all`, verify active HEAD and all required refs/stash, build immutable + recovery-current continuation ZIPs, verify SHA-256, persist both into `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
