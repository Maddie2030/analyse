# RC4.85 P03 — Web reading repository source review

Date: 2026-09-15

Scope: sequential re-review of P03 only. This report qualifies the Web reading repository source contract and locally runnable behavior tests. It does **not** claim the real frontend build/browser or independent-review gates in P03.2.

## Result

P03.1 is source-qualified after re-review. The shared Web reading repository, IndexedDB journal, account/origin scoping, pending overlays, immutable retry handling and late-acknowledgement fences are present and the 31 focused production-state-machine cases pass.

The regression entrypoint had a portability defect: on Node 22 it imported TypeScript without `--experimental-strip-types`, while the test file swallowed the import failure and converted it into dozens of misleading missing-export failures. This pass makes the wrapper explicitly select TypeScript stripping when required and removes the defensive import catches so loader/parse failures remain visible.

P03.2 remains open. Source checkpoint `d7fd294` now adds dedicated Playwright coverage for two-tab durability, quota failure, offline refresh, late acknowledgement, and media failure, plus a validator-enforced source contract. Real Playwright execution and independent review are still required.

## Source findings

### One Web reading owner

- `frontend/src/reading/repository.ts` owns pending reading state and transport ordering for the selected account/origin scope.
- `IndexedReadingStore` persists one `mreader-reading-v1` IndexedDB account store; no old writable `mreader:progress:*` local-storage path remains.
- `reading/transport.ts` is the only Web source that constructs Progress open/commit routes.
- Library does not call `api.getHistory()` or reconstruct Smart Library truth by merging Progress history. The retained `api.getHistory()` client method remains unused by Library and can support purposeful direct Progress consumers.
- Catalog Continue Reading and Library Recently Opened consume the Smart Library response; pending local intent only overlays affected actions/previews and does not manufacture server counts/read markers.

### Pending/confirmed separation

- Pending preview contains chapter/position/status only; it does not invent canonical read-state, completion or global totals.
- Acknowledgement generation/version checks prevent an older ACK from clearing a newer checkpoint.
- Sent commands retain their original body across timeout/retry; stale sessions pause instead of auto-rebasing.
- Explicit opens remain distinct ordered intents and dependent offline opens advance from the accepted prior revision.
- Account/origin keys are collision-safe. Suspended previous-account repositories do not upload into the new account, and explicit clear uses an IndexedDB epoch tombstone to fence delayed writes/ACKs across tabs.

### Local durability and bounds

- Active checkpoint persistence is debounced to one second.
- Background network flush runs every 30 seconds while dirty, plus online/visibility/pagehide and reader navigation/end events.
- Retry backoff is exponential with jitter and capped at 60 seconds.
- One in-flight sender/lease is used per series, with cross-tab transactional IndexedDB updates.
- Dirty/pending state is bounded at 500 records and 5 MiB per account. Clean records/confirmed cache can expire after seven days while dirty intent is retained.
- Storage-limit/failure handling keeps unsaved intent visible in memory and prevents an unpersisted command from being sent as though it were crash-safe.

### Reader lifecycle

- Each Reader visit establishes an explicit local open before asynchronous canonical restoration completes.
- Delayed restoration cannot override user interaction or a later chapter load.
- Reader snapshots on scroll, chapter navigation, pagehide and effect cleanup.
- Completion requires chapter-end observation plus the complete published page-number set being loaded; merely viewing the last visible image is insufficient.
- Manifest/token responses are request-generation fenced so stale chapter responses cannot replace a newer route.

### UI consumers

- Library validates Smart Library contract/request identity, discards late requests, resets page/filter state, de-duplicates appended IDs and leaves summary/recent data owned by a non-append refresh.
- Catalog history uses `response.recently_opened` from `scope=history`; it does not call Progress history as a safety floor.
- Series Detail uses canonical series reading state plus the local pending action overlay; exact read markers remain server-owned.
- Confirmed-reading events invalidate/refetch personal projections rather than updating durable totals locally.

## Test-harness correction

Changed:

- `tests/regression/progress-consistency-static.sh`
  - probes/uses Node TypeScript stripping support before running the production repository suite;
  - fails with an explicit environment error instead of allowing loader failure to masquerade as behavioral failures.
- `tests/regression/test_web_reading_repository.mjs`
  - production TypeScript modules are imported directly; loader/parse errors are no longer caught and converted to empty objects.

Before the correction, `node --test tests/regression/test_web_reading_repository.mjs` on Node v22.16.0 failed with repeated `production reading reducer must exist` assertions because the `.ts` import error was hidden. After removing the catch, the same unsupported invocation reports the real `ERR_UNKNOWN_FILE_EXTENSION`. The corrected wrapper runs the suite with `--experimental-strip-types` on this runtime.

## Locally reproduced evidence

- `bash tests/regression/progress-consistency-static.sh` — 31/31 pass.
- `node --experimental-strip-types --test tests/regression/test_web_reading_repository.mjs` — 31/31 pass.
- `bash tests/regression/api-flow-ownership-static.sh` — pass.
- `node --check tests/browser/*.mjs` — all current browser specs parse as JavaScript.
- Source searches confirm no `mreader:progress` Web storage keys and no Library `api.getHistory()` call.
- `git diff --check` — clean for this unit.

## Blocked/open P03.2 gates

The following are **not passed**:

- `npm run typecheck` under `frontend` — dependency tree is absent; TypeScript therefore reports missing React/React Router/Lucide modules and type declarations. This is an environment/dependency block, not a qualified application typecheck result.
- `npm run build` under `frontend` — cannot start because local `vite` is absent.
- Real Playwright execution — browser dependencies/runtime and deployed app topology are unavailable here.
- Required P03 browser scenarios — source coverage now exists in `tests/browser/reading-consistency.spec.mjs`, but the scenarios have not been executed against a real deployed browser/runtime topology in this sandbox.
- Independent scoped review — not performed by this same sequential-review pass.

These limitations leave P03.2 and the browser/runtime portions of LOCAL-01, LOCAL-02, LOCAL-03, READ-03, READ-04, UI-01 and PERF-01 open.

## Sequential disposition

- P03.1: source-qualified in this pass.
- P03.2: open/blocked verification; do not mark complete.
- Next sequential task: P04 Android reading/origin review. Re-run its source audit, inspect the 11 Kotlin tests and origin migration/current adapter paths, and attempt compile/tests only if a compatible Gradle/Kotlin environment is available.

## 2026-09-17 P03.2 browser acceptance source coverage

At source `d7fd294`, the missing browser scenarios were added without production behavior changes. The supported current-release validator now requires `tests/regression/browser-reading-acceptance-static.sh`, which in turn requires all five scenario sources and parses the Playwright spec. Fresh local evidence is 31/31 Web reading state-machine tests, browser acceptance source contract PASS, all browser `.mjs` syntax PASS, and current-release source/static validation PASS. Real Playwright execution and independent review remain open.
