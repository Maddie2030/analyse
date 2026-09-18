# RC4.85 next chat — P09.5 route / consumer denial

## Resume authority

- Branch: `sequential/p06.4-caller-cutover`
- P09.4 final source checkpoint: `56337e03d9a6bd87163ace8250276ed1e766a9cb` (`56337e0`)
- P09.3 restrictive-grant source: `67303f6e71f9c232f3e4385c5912e19bace5ead4`
- P09.2 ownership/route source: `289337e10af684704437430c3b9f85dd70f17cd7`
- P09.1 scoped-secret prerequisite: `0f1fadb`
- Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — **do not apply/pop**
- Persistent recovery authority: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip` plus `.sha256`
- Tracker/handoff HEAD: trust the live HEAD embedded in the continuation package created after this document is committed.

## P09.4 boundary to preserve

P09.4 is **source-qualified / runtime-gate blocked**. Fresh exact-tree P09.4 evidence on `56337e0`: focused P09.4 18/18 PASS; inherited P09.3 20/20 PASS; PostgreSQL role audit PASS (15 capabilities / 18 workload identities); inherited P08.8 + secret-scope regressions 28/28 PASS; pre-upgrade ordering PASS; all 10 current recovery/database shell contracts PASS; full dependency-light discovery 335 tests with 10 intentional skips and 0 failures; runnable Scraper 18/18; ownership/route 136/136 plus API ownership, route coverage and WebP PASS; shell syntax, Python compile and `git diff --check` PASS; Ripwire `e03ef17..56337e0` `gating=0`. The P09.3 real PostgreSQL permission gate remains BLOCKED rc=2 because Docker is unavailable and no authorized disposable DSN is present. The P09.4 real runtime gate remains BLOCKED rc=2 because no explicitly authorized current-hybrid target was supplied; neither blocker is a PASS.

Preserve one host-side readiness authority, P08.8 host generation as recovery truth with `database_restore_state` as its mirror, P09.3 exact grant verification, workload-scoped DSNs, deterministic generation stamping for all database-dependent Deployment templates including replica-zero workers, rollout-before-autoscaling, and restore re-entry through canonical deploy.

## Next legal source lane — P09.5 only

Do **not** start P09.5 source work unless the P09.4 Task 8 immutable and rolling Library continuation packages have both been independently re-materialized and verified.

P09.5 must consume the same-tree P09.2 ownership/route manifest to enforce route/consumer denial without inventing a second ownership registry. Preserve P09.1/P09.3/P09.4 security boundaries and do not broaden credentials or bypass readiness/generation enforcement.

Start with Superpowers design/brainstorming and Ripwire same-tree mapping before any implementation.

## Read first

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. `contracts/ownership/routes.v1.json` and its schema/auditor
6. this handoff

The mandatory source + tracker + all-refs Library durability rule remains in force for every future meaningful checkpoint.
