# RC4.85 next chat — P10.1 UI capability verification

## Resume authority

- Branch: `sequential/p06.4-caller-cutover`
- P09.5 final source checkpoint: `7c292fe6571d7da7a0f5206a80bdcc5185b1887d` (`7c292fe`)
- P09.4 source checkpoint: `56337e03d9a6bd87163ace8250276ed1e766a9cb`
- P09.3 restrictive-grant source: `67303f6e71f9c232f3e4385c5912e19bace5ead4`
- P09.2 ownership/route source: `289337e10af684704437430c3b9f85dd70f17cd7`
- P09.1 scoped-secret prerequisite: `0f1fadb`
- Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — do not apply/pop
- Tracker/handoff HEAD: trust the live HEAD embedded in the continuation package created after this document is committed.

## P09.5 boundary to preserve

P09.5 is source-qualified at `7c292fe`. The same-tree ownership authority covers 139 routes and 10 proven direct HTTP→event effects. Retired/private/admin/Catalog-write denial is explicit at the gateway boundary, Web/Android preserve safe owner/error/request/operation/revision metadata, and event producers/outbox-relay preserve only allowlisted safe metadata. P09.1–P09.4 least-privilege/readiness boundaries remain intact.

Fresh qualification: focused P09.5+P09.2 24/24; full dependency-light 345 with 10 skips and 0 failures; runnable Scraper 18/18; ownership/route 139/139; PostgreSQL role audit PASS; API ownership/route/WebP PASS; Python compile, TypeScript typecheck, `gofmt`, diff check PASS. Android Gradle is blocked by unavailable network download; changed Go modules require Go >=1.25 while the sandbox has 1.23.2. Raw Ripwire ref-pair reports three unchanged pre-existing dead-code false positives; changed-surface comparison excluding exactly those unchanged files is `gating=0`.

The user granted a one-time waiver only for P09.4 Library re-materialization. Do not carry that waiver forward. P10.1 must not start until the P09.5 tracker/all-refs continuation package is durably checkpointed.

## Next legal source lane — P10.1 only

Verify the nine retained UI surface groups from the canonical plan: Browse/Search, Series, Reader, Library, Account/Alerts, admin content, ingestion, curation, and Database Protection. Test guest/authenticated/admin access separately. Preserve functionality first; do not redesign unrelated UI or reopen P09 ownership boundaries unless a P10 verification proves a concrete integration defect.

Start with Superpowers brainstorming/mapping and Ripwire impact analysis. For every surface, identify intended actions and backend/data dependencies, test unavailable/stale/pending states, and use RED→GREEN for any discovered defect.

## Read first

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. `contracts/ownership/routes.v1.json`
6. this handoff

Normal source + tracker + all-refs Library durability is mandatory again.
