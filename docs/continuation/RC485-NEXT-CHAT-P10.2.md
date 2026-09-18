# RC4.85 next chat — P10.2 resilience/race/outage verification

## Resume authority

- Branch: `sequential/p06.4-caller-cutover`
- P10.1 source checkpoint: `c09227da005e21be2ef133f7373fd72103214165` (`c09227d`)
- P09.5 source checkpoint: `7c292fe6571d7da7a0f5206a80bdcc5185b1887d`
- P09.5 tracker checkpoint before P10.1: `dd410f7e2672622a713ad733ff236c68a9b872ae` (`dd410f7`)
- Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — do not apply/pop
- Tracker/handoff HEAD: trust the live HEAD embedded in the continuation package created after this document is committed.

## P10.1 boundary to preserve

P10.1 is source-qualified at `c09227d` across all nine retained UI groups. Preserve the repairs for recoverable pagination, truthful unavailable/unknown state, identity-scoped Android notifications, supported PDF upload, existing-series page replacement, Android announcement link/dismiss behavior, and fail-closed Database Protection. Do not reopen P09 ownership, route/event, least-privilege or readiness boundaries.

Fresh evidence on `c09227d`: P10.1 focused 43/43; full dependency-light 388 tests / 10 skips / 0 failures; Web Reader 31/31; Android Reader 8/8; API ownership PASS; route coverage 139/139; WebP PASS; Python compile and diff check PASS; committed-tree Ripwire `dd410f7..c09227d` `gating=0`. Nine recovery/database shell contracts ran successfully. `backup-daily-policy.sh` timed out with its backend paths unchanged by P10.1. Frontend `node_modules`, Android Gradle wrapper JAR and Scraper `selectolax` are unavailable, so those gates remain BLOCKED rather than passed.

The P09.5 immutable/current package was manually downloaded by the user and explicitly accepted as a temporary user-held fallback when Library read-back was unavailable. That provenance does not waive the P10.1 checkpoint rule.

## Next legal source lane — P10.2 only

Exercise delayed and out-of-order responses, double-click/repeated-submit behavior, pagination/filter resets, offline/reconnect, account/origin changes, and Social/Progress/Realtime/NAS outages. Assert that unavailable is never rendered as zero/false, local pending is never represented as server-confirmed, stale identity data cannot cross account/origin boundaries, and destructive/admin operations stay fail-closed under ambiguity.

Start with Superpowers brainstorming/mapping and Ripwire impact/test selection. Use RED→GREEN for each concrete defect. Prefer existing repositories/adapters and existing operation receipts; do not introduce a second state owner or fallback API.

## Read first

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`
4. `docs/qualification/RC485-CAPABILITY-MATRIX.md`
5. `docs/continuation/RC485-NEXT-CHAT-P10.2.md`

Do not begin P10.2 implementation until the P10.1 source+tracker all-refs continuation package is created and independently verified.
