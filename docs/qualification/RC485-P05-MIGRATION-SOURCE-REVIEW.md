# RC4.85 P05 migration/preservation sequential review

Date: 2026-09-15

Status: **source-qualified / runtime-blocked**. This is not PostgreSQL or deployment acceptance.

## Scope reviewed

P05 was reopened from the sequential RC4.85 line after P01-P04. The review covered the shared migration runner, pre-047/048 reading-evidence preservation, migration 052 provenance semantics, upgrade orchestration, legacy Progress stream handling, and legacy backup/scraper operation retirement rules.

## Findings and changes

1. The existing shared renderer/apply boundary is retained. It still renders every migration into one psql connection, owns one advisory lock, injects the preservation hook before pending 047/048, and records each ledger entry inside that migration transaction.
2. Historical migrations `047_consolidate_reading_state_rc482.sql` and `048_rc483_current_baseline.sql` were not edited. Their SHA-256 values remain:
   - `a18ebb775978f0e3fd177e878f0a1ac072c5cae01e6ee145cd1506c47fdbb0f7`
   - `16bfb1f1117512359c6a1487ebdab191bca9fbaad90f712e33e0d95b3ab23026`
3. Upgrade orchestration had a real P05.4 gap: `stateful-up.sh` could capture and migrate while old Kubernetes application deployments and autoscalers were still active. `scripts/hybrid/quiesce-before-migration.sh` now:
   - removes HPA and KEDA ScaledObject authority before changing replicas;
   - scales all non-Progress deployments to zero;
   - runs the existing Progress image in explicit `PROGRESS_GO_DRAIN_LEGACY_STREAM=1` maintenance mode;
   - requires the configured legacy stream consumer group to report both `pending=0` and `lag=0` twice consecutively;
   - scales Progress to zero and verifies every remaining MReader Deployment is stopped;
   - treats a populated legacy stream with a missing/unknown consumer group as an ambiguous blocking condition rather than discarding it;
   - is a no-op on a fresh install with no MReader Kubernetes namespaces.
4. `stateful-up.sh core` invokes that quiescence after the stateful database/cache/broker are healthy and the old backup agent is stopped, but before replication repair, mandatory pre-upgrade capture, or migration. The manual `scripts/migrate.sh` path therefore cannot bypass the same boundary. Current-version deploy is intentionally responsible for resuming workloads, preventing old mixed-version writers from coming back after schema changes.
5. Migration `050_retire_backup_requests.sql` historically allowed one migrated legacy queued request to become a canonical queued operation. That is unproven work and conflicts with the approved recovery-required rule. Historical migration 050 was not rewritten. New forward migration `053_legacy_operation_reconciliation.sql` marks only such `migrated-queued` legacy rows failed with phase `migration-recovery-required`, terminal timestamp, and explicit `replay_allowed=false` metadata before current workloads resume. Verified/failed/cancelled terminal history is not requeued.
6. `scraper_history` is deliberately **not** retired in P05. Its useful history/status reconciliation depends on the P07 canonical `ingestion_operations` header and fencing rules. P05 records that dependency instead of dropping or copying it into another temporary authority.

## Fresh verification

- P05 quiescence/reconciliation source regressions: **10 passed**.
- Migration-runner shell contracts: **6 passed**.
- Existing local pre-upgrade capture/order fixtures: **5 passed** after extending the miniature stateful fixture with the new quiescence dependency.
- Bash syntax: passed for the quiescence, stateful-up, manual migrate, and shared migration runner scripts.
- Python compilation: passed for the P05 regressions and PostgreSQL qualification source.
- Current renderer emits **46 migration transactions**, **2 preservation hooks**, and includes migration 053.
- `git diff --check`: passed before commit.

## Blocked acceptance

The following gates were not run in this environment and remain open:

- actual PostgreSQL execution of `test_reading_upgrade_postgres.py` against RC4.81, supplied RC4.84 variants, fresh/partial/interrupted/concurrent states;
- actual SQL semantics of migration 053 against a disposable PostgreSQL database;
- live Kubernetes quiescence with HPA/KEDA installed, legacy Progress stream drain, failed migration hold state, and current-version resume;
- Docker/Compose backup plus migration execution.

Tool probe at this checkpoint: `psql`, Docker, and `kubectl` are unavailable and `MREADER_TEST_POSTGRES_DSN` is unset. These are **blocked**, not passing.

## Sequential disposition

P05.1-P05.4 are source-qualified. P05.5 remains runtime-blocked. P05.6 is source-qualified for the legacy backup queue and explicitly deferred for scraper-history retirement until P07 establishes the replacement ingestion authority. MIG-01/MIG-02 remain open combined gates.
