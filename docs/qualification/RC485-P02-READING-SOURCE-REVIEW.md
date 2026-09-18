# RC4.85 P02 — Progress reading source review

Date: 2026-09-15

Scope: sequential re-review of P02 only. This report qualifies source structure and locally runnable checks; it does **not** claim the PostgreSQL/API runtime gates in P02.2.

## Result

P02.1 is source-qualified after re-review. The existing implementation already uses the intended synchronous Progress command boundary, so this pass does not replace the command algorithm. The only application-source edit in this unit is Go formatting cleanup in four Progress files.

P02.2 remains blocked in this workspace because the required disposable service/database runtime is unavailable.

## Source findings

### Normal acknowledgement path

- `POST .../open` calls `Service.RecordOpen` -> `Store.OpenReadingState`.
- `POST .../commit` calls `Service.Save` -> `Store.CommitReadingState`.
- Both command writers acquire a per-user/per-series PostgreSQL advisory transaction lock and validate the target chapter inside the transaction.
- The command transaction updates the exact chapter ledger and canonical `reading_progress`, appends `progress.updated` through the transaction-scoped outbox helper, and commits only after those operations succeed.
- Storage failure is returned as HTTP 503 with `code=progress_unsaved`; it is not acknowledged through Redis.

### Account and ordering fences

- Mutations require `X-MReader-Account-ID` and compare it with the authenticated user before target lookup.
- Reads accept a missing account fence for direct compatibility but reject a supplied mismatch.
- Open commands use `expected_revision`; accepted opens advance the series revision/session generation.
- Commit commands use the accepted session generation and a positive sequence; stale session/sequence and retained-ID conflicts return explicit synchronization results without taking newer resume ownership.
- Exact completion remains monotonic in `chapter_reads`; a checkpoint can move back while retained completion evidence remains true.

### Canonical read projection

- Migration 052 defines `reading_state_v1` as the Progress-owned projection.
- Exact history/recency excludes `provenance='migrated_reach'`.
- Migrated reach can still contribute the furthest chapter without manufacturing an exact open, resume, or completion event.
- Social Smart Library reads `reading_state_v1` and builds items, summary, filtered total, and the recent rail inside one SQL statement. It does not call `/api/progress/history` as a Library reconstruction fallback.

### Legacy write-behind boundary

- `PROGRESS_GO_DRAIN_LEGACY_STREAM` defaults to `0` and is not enabled in the normal hybrid Progress deployment.
- When explicitly enabled, `cmd/api/main.go` starts `RunFlusher` and returns before constructing/starting the HTTP API.
- `UpsertBatch` is reachable from that maintenance flusher only.
- Legacy resume updates are suppressed after a canonical command session exists by `reading_progress.session_generation = 0` in the legacy upsert condition.
- Exact legacy chapter evidence may still be reconciled by the drain; that is migration/maintenance behavior, not normal request acknowledgement.

### Event/read contracts

- `progress.updated` v2 carries the canonical revision and permits a null chapter target after deletion.
- Open/commit JSON schemas and the v2 event schema parse successfully and reject undeclared fields at the schema level.
- HTTP command decoding also rejects unknown fields and caps command bodies at 4096 bytes.

## Locally reproduced evidence

- `python3 -m unittest tests.regression.test_rc485_p02_reading_source -v` — 7/7 pass.
- `gofmt -l services/progress_go` — no output after formatting cleanup.
- `node --experimental-strip-types --test tests/regression/test_web_reading_repository.mjs` — 31/31 pass. This is P03 evidence, reproduced while investigating the historical `progress-consistency-static.sh` wrapper.
- The default `tests/regression/progress-consistency-static.sh` invocation fails on this Node 22 runtime because it imports `.ts` without `--experimental-strip-types`; its catch handler hides the import error and reports missing exports. This is a test-harness portability issue to address during P03, not evidence of a Progress server failure.

## Blocked runtime gates

The following were attempted and are **not passed**:

- `GOTOOLCHAIN=local go test ./...` under `services/progress_go` — blocked because the project requires Go >= 1.25.0 while this environment has Go 1.23.2. Automatic toolchain download is also unavailable because outbound access to `proxy.golang.org` is blocked.
- Actual Progress/Library API + SQL cases — blocked because `psql` and Docker are unavailable.
- `python3 -m pytest --collect-only ...` for the Progress/Library API suites — blocked before collection because Python package `psycopg` is unavailable.

These blocks leave P02.2 and the runtime portions of READ-01, READ-02, READ-03, READ-04 and LIB-01 open.

## Sequential disposition

- P02.1: source-qualified in this pass.
- P02.2: blocked verification; do not mark complete.
- Next sequential task: P03 Web reading repository. Re-run its production tests with a portable TypeScript-loading entry point, then inspect actual Web consumers and build/browser gates.
