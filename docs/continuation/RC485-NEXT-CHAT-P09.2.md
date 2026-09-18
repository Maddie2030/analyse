# RC4.85 Next Chat — P09.2 Ownership / Route Manifest

## Resume authority

- Branch: `sequential/p06.4-caller-cutover`
- P08.8 source-qualified checkpoint: `cbaf5a89accf1b92e92c5b6cd1765c3f23e6fad3`
- Tracker/handoff HEAD: trust the live HEAD embedded in the continuation bundle created after this document is committed.
- Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — **do not apply or pop**.
- Persistent recovery authority: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip` plus `.sha256`.

## P08.8 state to preserve

P08.8 is **source-qualified/runtime-blocked**. Restore confirmation and queued operations are bound to the selected opaque recovery ID/hash, browser-safe installation fingerprint and expected host restore generation. The host backup agent rechecks that tuple at claim and immediately before cutover, keeps exact source+safety IDs pinned, records each destructive phase in the host-owned v2 journal, deterministically reconciles interruption states, invalidates only replay-unsafe restored ingestion/media/outbox work, mirrors the committed generation into PostgreSQL and advances the host generation only after validation/reconciliation. Drill paths must never enter production cutover/generation/reconciliation state.

Fresh source evidence at `cbaf5a8`: 282 dependency-light regressions with 10 intentional skips; P08.8 20/20; all 10 current recovery/database shell contracts; 18/18 runnable Scraper; API ownership; 136/136 route classification; WebP audit; shell/Python syntax and diff checks; Ripwire `gating=0`. Docker/PostgreSQL interruption rehearsal remains blocked because Docker is unavailable.

## P09 prerequisite status

P09.1 workload-scoped secret selection is **already reconstructed/qualified** at `0f1fadb`. Do not redo P09.1 and do not merge `reference/p09.1-scoped-secrets` wholesale.

## Next lane — P09.2 only

Build the machine-readable ownership/route manifest from the current sequential source. Each in-scope route/operation row must carry: operation, method/path, access plane, owner, handler, version, authentication, permitted writes, dependencies, consumers, events and acceptance-test IDs. Use `reference/p09.2-manifest-wip` only as selective evidence/fixture material; never merge it wholesale. Preserve P06/P07/P08 ownership and P09.1 scoped-secret boundaries. Do not begin P09.3 restrictive grants or P09.4 readiness/generation enforcement until P09.2 is source-qualified.

## Resume commands

```bash
cd /mnt/data/mreader-rc485-working
Drushti doctor
git status --short
git rev-parse HEAD
git rev-parse refs/stash
sed -n '1,220p' docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md
sed -n '1,220p' docs/continuation/RC485-CONTINUATION-MANIFEST.md
ripwire . --for='P09.2 ownership route manifest handlers gateways adapters permissions consumers events acceptance tests'
```

## Mandatory checkpoint rule

After meaningful P09.2 source work: make a source-only commit, then a separate tracker/handoff commit. Rebuild a fresh `git bundle --all` continuation package, verify active HEAD + all refs + exact forensic stash, create/verify immutable and rolling ZIPs plus SHA-256 sidecars, persist them to `/MReader/RC4.85`, re-materialize both Library copies and independently verify their checksums and embedded HEAD/source/stash before calling the milestone durable or moving to P09.3.
