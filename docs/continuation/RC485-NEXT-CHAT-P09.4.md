# RC4.85 next chat — P09.4 readiness / generation enforcement

## Resume authority

- Branch: `sequential/p06.4-caller-cutover`
- P09.3 final source checkpoint: `67303f6e71f9c232f3e4385c5912e19bace5ead4` (`67303f6`)
- P09.2 ownership/route source checkpoint: `289337e10af684704437430c3b9f85dd70f17cd7`
- P09.1 scoped-secret prerequisite: `0f1fadb` — preserve; do not redo
- Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — do not apply/pop
- Persistent recovery authority: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip` plus `.sha256`
- P09.3 durable tracker checkpoint: `32c43838cb354ce52f005ff762862b5cac5853ca` (`32c4383`), independently verified from immutable + rolling Library copies at SHA-256 `257c894549eef3917989454f379c76c416505cdc61b1c0ee41cdc85feebc682c`

## P09.3 boundary to preserve

P09.3 is **source-qualified / runtime-permission-gate blocked**. The exact-tree qualification passed 315 dependency-light regressions with 10 intentional skips, 18/18 focused P09.3 tests, 18/18 runnable Scraper tests, 5/5 pre-upgrade tests, all 10 current recovery/database shell contracts, ownership/route 136/136, API ownership, WebP, syntax/compile/diff and Ripwire `gating=0`. The actual PostgreSQL permission gate exits 2 (BLOCKED) because Docker is unavailable and no explicitly authorized disposable DSN exists; never reinterpret that as PASS.

Preserve: 15 capability roles / 18 workload logins; subtractive grant reconciliation; PostgreSQL-catalog effective-privilege verification; explicit PUBLIC and future-function fail-closed rules; role-unique P09.1 DSNs; fail-closed runtime loaders; per-login positive/negative permission probes; KEDA read-only identity.

## Next legal source lane — P09.4 only

Start with Superpowers design/planning and current-tree Ripwire mapping before source edits. P09.4 must:

1. fail readiness when the expected owner schema/grants are missing or inconsistent;
2. complete quiescence/restart and restore-generation fencing across the supported deployment/recovery path;
3. preserve P09.1/P09.3 narrow credentials and never fall back to broad bootstrap credentials;
4. keep P09.5 route/consumer denial out of scope until P09.4 is independently source-qualified.

The P09.3 Task 8 package at tracker `32c4383` has been independently verified in Library. Before P09.4 source edits, also verify the newest closure-tracker continuation package that contains this handoff, preserving the standing durability rule.

## Read first

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. `docs/superpowers/specs/2026-09-16-rc485-p09.3-restrictive-domain-grants-design.md`
6. this handoff

The mandatory durability rule remains in force after every future meaningful source + tracker checkpoint.
