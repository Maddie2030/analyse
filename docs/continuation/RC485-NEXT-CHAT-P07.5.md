# RC4.85 next-chat start — P07.5 status/UI convergence

This document is the compact continuation entry point after P07.4 lifecycle cleanup ownership was source-qualified. The canonical tracker, continuation manifest, and sandbox-loss recovery ledger remain the detailed authorities.

## Restore authority

- Persistent Library package: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`
- Checksum sidecar: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`
- Active branch: `sequential/p06.4-caller-cutover`
- P07.4 source checkpoint: `394e440272226237c138b2b4b668f2a65369cfb3`
- P07.3 reconstructed source: `6e42f6b` (behavior-equivalent replacement for historical lost `b5ddd8a`)
- Tracker/handoff: use the live HEAD restored from the current Library package; verify it before editing.
- Forensic `stash@{0}` is superseded evidence only. Restore the ref, but never apply/pop it during normal continuation.

If `/mnt/data` is missing, materialize the Library package, verify its SHA-256, and restore all refs from the embedded Git bundle. Verify the active branch HEAD and `refs/stash` before editing. Restore `/Drushti/drushti-global-agent-bundle-2026-09-15.zip` and run `Drushti doctor` if the shell binaries are absent.

## P07.4 source-qualified contract to preserve

`394e440` establishes these boundaries and P07.5 must not weaken them:

1. Catalog stores the relevant Media generation on published pages and current cover state.
2. Catalog snapshots exact primary/responsive/cover `{path, generation, kind}` cleanup intent inside the same delete/replacement transaction that retires canonical state.
3. Media hands production-output cleanup to durable Lifecycle cleanup jobs; UUID-scoped `_jobs/media` input/staging cleanup remains private Media cleanup.
4. Lifecycle is the sole production physical object deleter.
5. Before deletion, Lifecycle protects any path that is currently referenced by Catalog and checks Media generation for Media-originated cleanup so delayed work cannot remove replacement output.
6. Legacy `storage_prefixes` / broad-prefix jobs are terminally quarantined and never execute recursive production deletion.

Fresh source evidence at the P07.4 checkpoint: dependency-light regression suite OK with 223 tests reported and 10 intentional skips; 18/18 runnable Scraper tests; API ownership audit; 136/136 source routes classified; WebP ownership audit; changed Python compile, Go formatting and `git diff --check`; 6/6 ingestion-authority tests; Ripwire `gating=0`.

Known blocks remain blocks, not passes: Scraper hardening lacks `selectolax`; Go runtime partner tests require >=1.25 while the sandbox has 1.23.2; frontend dependencies are absent; API integration lacks `psycopg`; P06.3 real PostgreSQL qualification remains deferred/unexecuted by explicit prior decision.

## Exact next product lane

**P07.5 — status/UI convergence and runtime-behavior qualification.** Do not reopen P07.4 ownership unless a failing P07.5 test demonstrates a real contract defect.

Required next behavior:

1. Present overall ingestion status from the canonical `ingestion_operations` header rather than reconstructing truth independently from subordinate draft/media state.
2. Present catalog removal separately from storage cleanup so the UI never claims physical deletion merely because canonical metadata is gone.
3. Exercise retry, refresh, process restart, worker loss, and KEDA redelivery against the canonical receipt/generation/cancellation/cleanup fences.
4. Preserve known-commit versus unknown-outcome semantics: known commit preserves published data; unknown outcomes reconcile rather than delete/requeue blindly; cancellation cannot permit a stale worker to publish.
5. Retire obsolete scraper history/status routes only after their capability and retained-data disposition is explicitly mapped and tested.
6. Stay within P07.5; do not broaden into P08/P09/P10 work until this lane is source-qualified.

Start with Ripwire mapping of operation-status consumers, admin scraper status screens/routes, cleanup-job status surfaces, retry/restart paths, KEDA/redelivery boundaries, and any legacy scraper history/status endpoints. Use TDD: write RED behavioral/contract tests before production changes.

## Fresh-chat commands

```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
cd /mnt/data/mreader-rc485-working
git status --short --branch
git log -12 --oneline --decorate
ripwire . --handoff
ripwire . --for='P07.5 ingestion operation status catalog removal storage cleanup retry refresh restart worker loss KEDA redelivery scraper history status'
```

Then read:

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. this file

Mandatory persistence rule remains in force: after every meaningful source + tracker checkpoint, create a fresh `git bundle --all`, verify active HEAD and required refs/stash, build immutable + rolling continuation ZIPs, verify SHA-256, persist them to `/MReader/RC4.85`, re-materialize both Library copies, and independently verify checksum plus embedded HEAD/stash before calling the checkpoint durable.
