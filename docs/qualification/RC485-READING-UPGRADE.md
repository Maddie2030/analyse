# Reading upgrade source checkpoint — 2026-09-14

The shared migration runner and preservation implementation are present in source. No live database, service, deployment or production restore was modified. No release archive was produced.

## Changes and self-review

- Replaced three migration loops with one renderer/apply pair used by normal migration and restore candidates. The host migration entry point now uses the existing mandatory pre-upgrade capture orchestration.
- Kept 047/048 unchanged and inserted transactional evidence preservation before either pending destructive migration. Added 052 for provenance-aware projection and an inferred-row constraint; reused 051's existing surviving-checkpoint repair rather than duplicating it.
- Fixed the newly identified Social integration gap: reach-only evidence was excluded before unread calculation. Library now consumes the canonical furthest value without claiming exact history or recency.
- Updated both actual-open and explicit legacy-drain ledger transitions so an inferred observation timestamp cannot become the real first/last-read timestamp.
- Added executable shell contracts, actual-runner PostgreSQL fixtures and an actual-API inferred-to-observed regression. Independent source review and runtime qualification remain pending.

## Actual results

| Check | Result |
|---|---|
| Initial runner regression | Failed: 3 of 6 cases failed because render/apply did not exist |
| Implemented runner regression | 6 passed, 0 skipped; real shell execution with a recording psql boundary |
| Existing pre-upgrade capture/order behavioral tests | 5 passed, 0 skipped |
| Existing Web reading repository behavioral tests | 31 passed, 0 skipped |
| Render full current migration set | 45 migration transactions, 2 preservation hooks emitted |
| Shell syntax, Python compilation, `git diff --check` | Passed |
| Backup-agent static contract | Passed; source check only |
| Restore-recovery static contract | Passed; source check only |
| Mandatory pre-upgrade order check | Passed; backup source line precedes migration source line |
| Actual isolated PostgreSQL cases | Blocked: psql and explicit disposable test DSN unavailable; no SQL acceptance pass |
| Actual inferred-to-observed API test | Blocked: pytest unavailable; no service/runtime pass |
| Go/TypeScript compilation, Docker image build, deployment | Blocked by unavailable tooling/dependencies |

Historical migration hashes match baseline commit `7d6b74c`:

| File | SHA-256 |
|---|---|
| 047_consolidate_reading_state_rc482.sql | `a18ebb775978f0e3fd177e878f0a1ac072c5cae01e6ee145cd1506c47fdbb0f7` |
| 048_rc483_current_baseline.sql | `16bfb1f1117512359c6a1487ebdab191bca9fbaad90f712e33e0d95b3ab23026` |

The PostgreSQL suite now contains ten cases, including the production Smart Library query. None has executed here. A skipped suite or rendered SQL does not qualify a data migration. See `docs/recovery/READING_UPGRADE.md` for the operator contract and outstanding gates; the full RC4.85 status remains in `RC485-WORK-IN-PROGRESS.md`.
