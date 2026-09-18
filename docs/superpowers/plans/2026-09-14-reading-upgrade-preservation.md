# Reading Upgrade Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax. Existing reviewer quota interruptions require inline implementation; independent review remains a qualification gate.

**Goal:** Preserve last-open, matching checkpoints and independent furthest evidence before shipped migrations 047/048 remove legacy history, using one serialized migration runner for upgrades and restore candidates.

**Architecture:** A shared POSIX shell renderer emits a complete psql script, then a shared apply wrapper executes that script through one connection. A session advisory lock covers ledger checks and all migration transactions. The preservation SQL executes inside each pending 047/048 transaction, validates its canonical copies, then removes old input rows so the unchanged shipped migration cannot copy another chapter's checkpoint. A forward migration updates provenance-aware projections for existing installations.

**Tech Stack:** PostgreSQL 16, POSIX shell, Bash entry points, Python standard-library unittest, existing Go Progress store. No dependency or resource-limit changes.

**Spec:** `docs/superpowers/specs/2026-09-11-mreader-rc485-ownership-consolidation-design.md`, sections 4, 9, and MIG-01.

## Global Constraints

- Preserve already-shipped migration filenames and SQL bytes, especially 047 and 048. Do not expect an edited historical migration to replay.
- No live database or production restore is exercised. PostgreSQL tests create and own isolated databases and require an explicit test DSN.
- Old history is not a runtime fallback. Temporary preservation evidence is transaction-local; no permanent duplicate history table is introduced.
- Match user, series and chapter before borrowing page/scroll/completion. Independent furthest-only evidence uses `provenance='migrated_reach'` and cannot create exact read/completion markers or Recently Opened timing.
- Existing exact ledger rows win over inferred reach. Keep original timestamps and deterministic ties. Already-destroyed evidence requires a verified backup; never guess it back.
- Mandatory verified local pre-upgrade backup remains before normal production migration orchestration. This plan does not qualify writer quiescence or destructive restore cutover.
- Source/runner tests do not replace actual PostgreSQL, Go or deployment qualification. Record unavailable tools as blocked.

## Task 1: One serialized migration executor

**Files:** create `ops/migrate/render.sh`, `ops/migrate/apply.sh`, `tests/regression/test_migration_runner.py`; modify `ops/migrate/run.sh`, `ops/migrate/Dockerfile`, `ops/postgres-backup/Dockerfile`, `scripts/migrate.sh`, `scripts/backup/backup-agent.sh`, `deploy/compose/docker-compose.hybrid-stateful.yml`.

**Interfaces:** `render.sh MIGRATION_DIRECTORY PRESERVATION_SQL` prints a complete psql script. `apply.sh [psql arguments...]` reads `MREADER_MIGRATIONS_DIR` (default `/migrations`) and `MREADER_READING_PRESERVATION_SQL` (default `/migration-safety/preserve-reading-evidence.sql`), renders to a private temporary file and invokes psql exactly once. `run.sh` retains connection readiness/configuration and delegates to apply. Backup `apply_current_migrations(target_db, host, port)` calls the same wrapper.

- [x] Write executable-renderer tests before implementation: two original migration bodies survive verbatim, the hook precedes each destructive body, one psql connection is used, missing inputs stop before psql, and a failing psql exit is propagated.
- [x] Run `python3 -m unittest discover -s tests/regression -p test_migration_runner.py -v`; record initial failures and later output.
- [x] Implement the generated control flow below once, using safely quoted repository filenames and a fixed advisory lock key. `\gset`/`\if` must make ledger decisions inside the locked psql session, not from another shell connection.

```sql
SELECT pg_advisory_lock(77160485, 1);
CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
SELECT NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version='047_consolidate_reading_state_rc482.sql') AS apply_migration \gset
\if :apply_migration
BEGIN;
-- preservation SQL, followed by unchanged migration bytes
INSERT INTO schema_migrations(version) VALUES ('047_consolidate_reading_state_rc482.sql');
COMMIT;
\endif
SELECT pg_advisory_unlock(77160485, 1);
```

- [x] Wire all three callers and both images/mounts. The manual host entry point delegates to the existing mandatory-preupgrade orchestration instead of keeping a fourth loop. Preserve existing image pins, limits and deployment topology.
- [x] Run shell syntax and focused renderer tests; record remaining real PostgreSQL/concurrency gates and checkpoint assigned files.

## Task 2: Preserve exact evidence before history retirement

**Files:** create `db/upgrade/preserve-reading-evidence.sql`, `db/migrations/052_reading_evidence_provenance.sql`, `tests/regression/test_reading_upgrade_postgres.py`; modify `services/progress_go/internal/store/commands.go` and `services/progress_go/internal/store/store.go` for inferred-to-observed provenance and exact-marker filtering; modify `services/social_ts/src/routes.ts` to retain reach-only evidence in unread calculation; extend `tests/api/test_26_reading_commands.py` for the actual open transition.

**Interfaces:** the preservation hook consumes legacy `reading_history`, existing `reading_progress` and `chapter_reads`. It adds nullable per-chapter resume fields/provenance and a nullable aggregate last-open field only when missing. It creates temporary evidence tables `ON COMMIT DROP`, writes canonical rows, validates them, and records `rc485_reading_evidence_preserved_v1` in `schema_migrations` in the same transaction. If public history is absent while 047 is pending, an empty temporary compatibility table allows the original no-op migration to complete. 052 owns the final `reading_state_v1` definition and inferred-evidence constraint; 051 already owns the one-time surviving-checkpoint repair and is reused.

- [x] Write actual-runner PostgreSQL cases for exact A checkpoint versus B history, distinct C furthest reach, an existing exact C ledger row, 047-applied/048-pending legacy data, already-upgraded data with no history, a migration error that rolls back all preservation/deletion/ledger changes, and two concurrent executor processes.
- [x] Preserve a source snapshot before changes using `CREATE TEMP TABLE ... ON COMMIT DROP AS SELECT ... FROM reading_history`. Reject invalid user/series/chapter links and null event timestamps before deleting input.
- [x] Backfill matching surviving checkpoints as exact legacy evidence. Upsert legacy last-open rows with a three-key checkpoint join. Insert furthest-only rows with `completed=false`, `resume_page=NULL`, `resume_scroll_position=NULL`, `provenance='migrated_reach'`, and `ON CONFLICT DO NOTHING`.
- [x] Select resume only from exact rows, using timestamp then chapter number/ID tie-breakers. Preserve an aggregate row for reach-only series without claiming a last-open chapter. Verify that every valid source last-open and furthest target has its canonical ledger evidence and matching checkpoint provenance before clearing history rows.
- [x] Apply 052 after 051: infer no missing historical furthest value; mask reach-only last-open timing in the view, keep inferred reach in the furthest lateral query, and exclude it from exact/completed marker lists. On a real open of an inferred row, replace its observation timestamp with the actual first-read event and mark it observed.
- [ ] Run the PostgreSQL cases only with the isolated test DSN and available psql. Without those dependencies, report tests blocked and do not claim data migration correctness or concurrency success.

## Task 3: Source review, qualification record and persistence

- [x] Verify historical migration SHA-256 values against `7d6b74c` and ensure all active migration callers use the shared executor.
- [x] Run focused available regressions and syntax checks. Preserve real command exits separately from blocked PostgreSQL/Go/image/deployment checks.
- [x] Update `docs/qualification/RC485-WORK-IN-PROGRESS.md` and upgrade/restore instructions with the shared lock, evidence rules, backup prerequisite and unrecoverable-evidence limitation.
- [x] Record unresolved writer-quiescence, legacy Redis maintenance drain, role-grant and publication/lifecycle requirements as combined-release gates; do not represent this plan as completion of the whole RC4.85 spec.
- [x] Commit the source checkpoint, refresh the existing WIP source patch and save it as the next version. No release ZIP.

## Plan self-review

The runner and preservation SQL are coupled by the fixed hook path and 047/048 filenames. Restore and upgrade both consume the same wrapper, and both images/mounts must include its dependencies. Forward migration 052 requires columns installed by 051; the pre-047 hook adds only its necessary additive columns so it can run against RC4.81. Full spec scope outside this plan remains in the combined qualification backlog. No original migration is edited, no permanent history mirror is added, and no inferred reach is exposed as exact reading activity.

## Execution record — 2026-09-14

The six executable runner tests were written first: three initially failed because the implementation files did not exist; all six pass after implementation. Five pre-upgrade capture/order behavioral tests and 31 Web reading tests pass. Full-set rendering emits 45 migration transactions and two preservation hooks. Shell syntax, Python compilation, diff hygiene and the existing backup/restore source checks pass.

Ten actual-runner PostgreSQL cases are written but all skipped here because psql and an explicit disposable test DSN are unavailable. The actual API inferred-to-observed test could not start because pytest is missing. No SQL/runtime, compiler, independent source-review or release acceptance is claimed.

Plan adjustment from source inspection: Social previously filtered out canonical reach-only rows before calculating unread state. Its existing SQL now consumes those rows while keeping exact History/Recently Opened membership separate; the PostgreSQL suite executes the production SQL to verify this contract. The legacy maintenance drain also needs the provenance transition so its exact event cannot retain an inferred observation timestamp. No normal runtime write-behind owner was added.

Source checkpoint `842a2c2` and WIP patch version 2 were saved successfully. The PostgreSQL acceptance checkbox remains open.
