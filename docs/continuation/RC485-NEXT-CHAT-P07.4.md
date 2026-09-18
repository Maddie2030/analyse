# RC4.85 next-chat start — P07.4 lifecycle cleanup ownership

This document is the compact continuation entry point after the sandbox-loss reconstruction. The detailed authorities remain the canonical tracker, continuation manifest, and sandbox-loss recovery ledger.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P07.3 reconstructed source: `6e42f6b` (behavior-equivalent replacement for historical lost `b5ddd8a`)
- Tracker/handoff: use the live HEAD restored from the current Library package; verify it before editing.
- Forensic `stash@{0}` is superseded evidence only. Do not apply/pop it.

If `/mnt/data` is missing, materialize the Library package and restore all refs from the embedded Git bundle. Verify the ZIP SHA-256 and active branch HEAD before editing. Restore `/Drushti/drushti-global-agent-bundle-2026-09-15.zip` and run `Drushti doctor` if shell binaries are absent.

## Reconstruction chain now recovered

Behavior-equivalent replacement commits for the lost sandbox history:

- `b709d03` ← historical `ec273f9` — P06.4 batch publication convergence
- `8cdfdf4` ← historical `5466101` — new-series chapter publication convergence
- `8ecc4c4` ← historical `631ddbf` — series/taxonomy/cover ownership cutover
- `0f1fadb` ← historical `4325575` — scoped-secret prerequisite
- `581c310` ← historical `c82650a` — P06.5 private transport auth
- `d79e340` ← historical `2954469` — P06.6 publication event/dedupe boundary
- `24adb72` ← historical `ae6f4c7` — P07.1 ingestion-operation convergence
- `f5c34a7` ← historical `cd921e6` — P07.2 lease/cancel/generation fencing
- `6e42f6b` ← historical `b5ddd8a` — P07.3 Stage/Retry repair + cover consolidation

The original historical hashes above are provenance references only; their Git objects were lost. Use the reconstructed commits as active source history.

## Exact next product lane

**P07.4 — lifecycle cleanup ownership.** Do not resume recovery reconstruction; that is complete.

Required behavior from the original plan/conversation record:

1. Capture exact primary/responsive/cover object references **and generations** inside the same Catalog delete/replacement transactions that remove or replace canonical rows.
2. Use Media generation as the production-object generation where appropriate; chapter/page and cover cleanup intent must identify the exact generation being retired.
3. Lifecycle is the sole production physical object deleter.
4. Before deleting an exact object, Lifecycle re-checks live Catalog ownership/path+generation so delayed cleanup cannot delete replacement output.
5. Legacy `storage_prefixes` / broad-prefix jobs are unsafe historical work: classify/contain them; do not execute broad production-prefix deletion.
6. Stay within P07.4. P07.5 UI/status work follows only after cleanup semantics are source-qualified.

Likely files/seams to inspect first:

- Catalog delete/replacement commands and migrations
- Catalog chapter/page and series/cover persistence fields
- Media `app/lifecycle_worker.py`
- Media `app/routers/lifecycle.py`
- cleanup job schema/model
- chapter/series deletion and replacement tests
- cover replacement cleanup tests

Start with Ripwire mapping for `storage_prefixes`, cleanup jobs, direct storage deletion, series/chapter delete, cover replacement, responsive refs, and generation fields. Write RED replacement-safety tests before production edits.

## P07.3 exact-tree qualification carried forward

On reconstructed P07.3 source `6e42f6b`:

- 104/104 focused publication/security/authority/P07 regressions passed.
- 18/18 runnable Scraper tests passed.
- API ownership audit passed.
- API route audit classified 136/136 source routes.
- WebP ownership audit passed.
- relevant Python compilation and `git diff --check` passed.
- Ripwire cold quality reported `gating=0`; only the reviewed thumbnail-route short-horizon churn is acknowledged.

Known blocks remain blocks, not passes:

- Scraper hardening: missing `selectolax`.
- Catalog Go runtime: local Go 1.23.2 vs module requirement >=1.25.
- frontend typecheck/build: `frontend/node_modules` absent.
- API integration collection: missing `psycopg`.
- P06.3 real PostgreSQL qualification: deferred/unexecuted by explicit prior decision.

## Drushti continuation command

Use the complete Drushti stack:

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
ripwire . --handoff
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. this file

Mandatory persistence rule remains in force: after every meaningful source + tracker checkpoint, rebuild an all-refs bundle, persist immutable + rolling continuation ZIPs to Library, re-materialize them, and verify checksum + embedded HEAD/stash before calling the checkpoint durable.
