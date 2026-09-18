# MReader RC4.85 Sequential Action Plan and Progress Tracker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers\:executing-plans to continue this plan task by task. Use systematic-debugging, test-driven-development and verification-before-completion for implementation changes. Steps use checkboxes for tracking.

**Goal:** Preserve MReader's user/admin capabilities while making each persisted fact have one owner, keeping Web/Android state consistent, and delivering application source packages at verified major-blocker checkpoints.

**Architecture:** Retain the existing microservices and shared PostgreSQL deployment. Domain commands own writes; versioned projections own read contracts; local client journals represent unconfirmed reading intent. Recovery uses one host-local catalog and operation engine.

**Tech Stack:** Docker Desktop Kubernetes, Docker Compose, PostgreSQL 16, Go, Python/FastAPI, React/TypeScript, Kotlin/Android, Valkey, RabbitMQ, external SeaweedFS, KEDA/HPA.

**Spec:** Ownership and UI-state consolidation.

**Updated:** 2026-09-16. **Source checkpoint reviewed:** `cad8826` (P10.2 qualified tree: behavior/source `b15b417` plus targeted Ripwire analyzer-evidence commit).

**Workspace / continuation authority:**

This block is deliberately self-contained so a fresh chat/session can recover the exact working topology before touching code.

| Role | Canonical location / ref | Authority and usage |
| --- | --- | --- |
| Workspace root | `/mnt/data/mreader-rc485-working` | Current canonical restored source workspace after sandbox-loss recovery. |
| Workspace locator sentinel | `/mnt/data/.mreader_current_sequential_repo` | Contains the current workspace root path. If the expected absolute path is forgotten, read this file first. |
| **Canonical implementation repo** | `/mnt/data/mreader-rc485-working` | **Only repo allowed for sequential P01–P12 implementation, commits, verification evidence, tracker updates, and packages in the current recovered sandbox.** |
| **Canonical tracker** | `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md` | First file to read on every continuation. This is the single overall status authority. |
| Approved design/spec copy | historical pre-sandbox path `/mnt/data/mreader-rc485-sequential-review-repo/reference/RC485-OWNERSHIP-UI-STATE-SPEC.md` | Not mounted in the recovered sandbox. Treat as provenance only unless separately restored; current continuation uses checked-in tracker/manifest/qualification docs plus preserved Git refs. |
| Original action-plan copy | historical pre-sandbox path `/mnt/data/mreader-rc485-sequential-review-repo/reference/RC485-ACTION-PLAN.md` | Not mounted in the recovered sandbox; historical provenance only. The checked-in tracker is authoritative. |
| Reference-branch map | `docs/qualification/RC485-REFERENCE-BRANCHES.md` | Explains every `reference/*` and `reverse-reference/*` ref and whether selective porting is allowed. |
| Imported reverse-order repo | historical pre-sandbox path `/mnt/data/mreader_rc485_reverse_work/mreader-rc485-milestone-1` | Not mounted in the recovered sandbox. Preserve the imported `reference/*` / `reverse-reference/*` Git refs already carried by the canonical repository; never require this old checkout for continuation. |
| Ripwire source checkout | historical pre-sandbox workspace copy (not mounted) | Provenance only; current execution uses the installed global runtime and checked-in wrapper. |
| Ripwire binary | `$HOME/.local/bin/ripwire` | Current verified v0.6.1 runtime; use through `scripts/diagnostics/ripwire-context.sh` where possible. |
| Ripwire staged skills | historical pre-sandbox workspace copy (not mounted) | Use the installed Drushti/Ripwire skill/runtime layer instead of this old path. |
| Ripwire activated agent skills | current Drushti/Ripwire runtime layer | Verified through `Drushti doctor`; checked-in repo workflow rules remain authoritative. |
| **Drushti persistent recovery bundle** | `/Drushti/drushti-global-agent-bundle-2026-09-15.zip` (Library) | Cross-chat recovery source for Drushti + Caveman + RTK + Headroom + Ripwire custom skills. Current runtime materialized copy: `/mnt/data/drushti-global/drushti-global-agent-bundle-2026-09-15`. |
| Drushti global custom skills | `$HOME/.agents/skills` | Installed from the verified Drushti bundle; includes `drushti`, Caveman specialist workflows, `rtk`, `headroom`, and Ripwire skills. |
| Headroom source/wrapper | `$HOME/.local/share/dev-agents/headroom-0.37.0` / `$HOME/.local/bin/headroom` | Restored from saved `headroom-main.zip`; source declares 0.37.0 and wrapper `--help` exits 0. Persistent proxy/routing is **not** enabled. |
| RTK runtime state | `$HOME/.local/bin/rtk` compatibility launcher, source contract 0.48.0 | `Drushti doctor` verifies the launcher; upstream native Rust binary is unavailable, so report the compatibility launcher honestly. |
| Checked-in agent rules | `AGENTS.md` and `docs/development/RIPWIRE-WORKFLOW.md` | Defines how Superpowers and Ripwire are combined for MReader work. |
| Ripwire wrapper | `scripts/diagnostics/ripwire-context.sh` | Auto-discovers `MREADER_RIPWIRE_BIN`, `PATH`, then the workspace-local binary; must fail explicitly rather than fabricate Ripwire output. |
| **Detailed continuation manifest** | `docs/continuation/RC485-CONTINUATION-MANIFEST.md` | Detailed inventory of repos, branches, commit chronology, stashes, tools, skills, key files, tests, recovery rules, and new-chat resume instructions. Read immediately after this tracker. |
| **One-command continuation status** | `scripts/diagnostics/continuation-status.sh` | Prints repo identity, branch/HEAD, dirty count, stash, remotes, branches, Ripwire doctor, and current task. Run at every fresh continuation. |
| Portable continuation ZIP | `/mnt/data/mreader-rc485-continuation-2026-09-15.zip` | Handoff/recovery artifact containing a Git bundle of all refs (including `refs/stash`), key docs/reference files, verified Ripwire binary/skills, live status, restore README, and checksums. Not a release package. |
| Portable ZIP checksum | `/mnt/data/mreader-rc485-continuation-2026-09-15.zip.sha256` | Verify before restoring/transferring the continuation bundle. |
| **Persistent Library copy** | `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip` | **Cross-chat recovery authority during sandbox-loss reconstruction.** Companion `.sha256`, tracker, manifest, and recovery ledger are stored in `/MReader/RC4.85`. If `/mnt/data` is unavailable, restore this package first and verify the embedded `sequential/p06.4-caller-cutover` HEAD. |

**Canonical Git state at this checkpoint:**

- Active branch: `sequential/p06.4-caller-cutover`.
- Recorded source stack when this tracker was refreshed: P10.2 behavior/source `b15b417`, qualified through analyzer-evidence commit `cad8826`; P10.1 durable tracker is `ecb8c18`. Earlier post-recovery checkpoints remain preserved in Git history and the continuation manifest. Always compare this to live `git rev-parse HEAD`; tracker/documentation commits may move HEAD.
- Working tree was clean when this manifest was refreshed.
- Historical rollback stash: `stash@{0}` = `On sequential/p06.4-caller-cutover: P06.4 WIP paused for P06.3 completion gate audit`. Its useful manual-publication work has been reconstructed and superseded by committed checkpoints `54ec3fd` and `b7af7fe`. **Do not reapply it during normal continuation**; retain it only for forensic comparison until P06 caller cutover is complete.
- Sequential branches preserved in this repo: `sequential-baseline`, `sequential/p01-baseline-audit`, `sequential/p02-reading-review`, `sequential/p03-web-reading-review`, `sequential/p04-android-reading-review`, `sequential/p05-migration-review`, `sequential/p06-catalog-publication-review`, `sequential/p06.3-prereq-ingestion-fence`, `sequential/p06.4-caller-cutover`.
- Reference branches preserved in the same Git object database: `reference/p06.2-17c28ac-import`, `reference/p09-baseline`, `reference/p09.1-scoped-secrets`, `reference/p09.2-manifest-wip` plus remote-tracking `reverse-reference/milestone1-baseline` and `reverse-reference/reverse-p09`.
- Reference branches/remotes are evidence/import sources only. Never merge them wholesale into the sequential line. Selective ports require revalidation against the current sequential source and a dedicated commit.

**Agent workflow contract — Superpowers + Ripwire:**

1. **Superpowers controls process and correctness.** At a fresh continuation, invoke/read `using-superpowers` and `executing-plans`; for implementation use `test-driven-development`; for failures/unexpected behavior use `systematic-debugging`; before any completion/move-to-next-task claim use `verification-before-completion`; use the worktree skill for parallel/isolated work where appropriate.
2. **Ripwire controls repository context and change-risk evidence.** Before multi-symbol work run `scripts/diagnostics/ripwire-context.sh pack "<task>"`; before changing a known boundary use its impact/caller/affected-test modes; while debugging use the Ripwire bug/trace workflow; before a commit/checkpoint run quality/change-check/PR-context/test-gate as appropriate; at session handoff run `scripts/diagnostics/ripwire-context.sh handoff`.
3. Ripwire evidence never replaces executable tests, PostgreSQL/runtime gates, the approved design, or this tracker. If Ripwire is unavailable, record it as blocked and continue with direct source/test inspection; never invent Ripwire findings.
4. Ripwire quality/test-gate findings are obligations to inspect. A Ripwire test-gate naming tests does not mean those tests passed; execute them and record the real result.
5. Superpowers and Ripwire must always operate from the canonical implementation repo above unless the task is explicitly to inspect a named reference repo/branch.
6. **Drushti** is the user's umbrella invocation for the combined development workflow. Its recovery bundle is verified in Library at `/Drushti/drushti-global-agent-bundle-2026-09-15.zip`. In this runtime `Drushti doctor` verifies Ripwire 0.6.1, Caveman, Headroom source runtime 0.37.0 and the RTK compatibility launcher (source contract 0.48.0). The upstream native RTK Rust binary is unavailable; do not misreport the compatibility launcher as the native binary. Superpowers remains process authority and executable test evidence remains authoritative.

**Fresh-chat resume procedure (run before editing anything):**

```bash
cd /mnt/data/mreader-rc485-working
cat docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md
git status --short
git branch --show-current
git rev-parse HEAD
git stash list
git remote -v
scripts/diagnostics/ripwire-context.sh doctor
scripts/diagnostics/ripwire-context.sh handoff
```

Then:

- read `docs/continuation/RC485-CONTINUATION-MANIFEST.md` before opening implementation files;
- run `scripts/diagnostics/continuation-status.sh` and preserve its output when handing off to another chat;
- read the `Current task` and `Continuation handoff` sections below;
- compare live branch/HEAD/stash to the values recorded here and explain any difference before editing;
- inspect `docs/qualification/RC485-REFERENCE-BRANCHES.md` only when prior/reference work is relevant;
- do **not** restart from P01, do **not** reapply the superseded P06.4 stash, and do **not** switch to a scratch/reference repo unless this tracker explicitly says so;
- update this tracker at every checkpoint with the new commit, tests, blocked gates, branch/stash changes, and next task.

All sequential P01–P12 implementation, verification commits, tracker changes, and release/test packages must come from the canonical implementation repo. Scratch repos, imported patches, reference branches, Ripwire caches/notes, and tooling source trees are never alternate application authorities.

**New-chat/container recovery rule:** absolute `/mnt/data/...` paths identify this workspace but may not survive a completely new chat/container. Stable recovery identifiers are the canonical repo-relative tracker/manifest paths, branch names, commit IDs, stash description, original source archive identity, and the portable continuation bundle generated at a checkpoint. If the workspace path is missing, do not improvise from a scratch/reference checkout: restore the canonical Git bundle/workspace package or ask for the continuation bundle to be attached, then run the status script and Ripwire doctor before editing. Detailed recovery order is in `docs/continuation/RC485-CONTINUATION-MANIFEST.md`.
The Git bundle recovery has one non-obvious rule: **do not rely on `git clone <bundle>` alone**. It does not recreate every saved branch/stash reflog. Use the explicit fetch refspec + `git stash store` procedure in the detailed continuation manifest/portable `README-RESTORE.md`; that procedure was clean-room verified to restore the sequential branches, reference branches, imported remote refs and paused P06.4 stash.

**Files/tools to find first in any continuation:**

1. tracker: `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`;
2. detailed manifest: `docs/continuation/RC485-CONTINUATION-MANIFEST.md`;
3. current P06.3 gate: `docs/qualification/RC485-P06.3-COMPLETION-GATE.md`;
4. status script: `scripts/diagnostics/continuation-status.sh`;
5. Ripwire wrapper: `scripts/diagnostics/ripwire-context.sh`;
6. agent rules: `AGENTS.md` and `docs/development/RIPWIRE-WORKFLOW.md`;
7. reference branch policy: `docs/qualification/RC485-REFERENCE-BRANCHES.md`;
8. historical approved-design provenance: the pre-sandbox copy path is not currently mounted; use checked-in continuation/qualification docs and preserved Git refs unless that original artifact is separately restored;
9. historical baseline archive provenance: the original upload is not currently mounted in this recovered sandbox; do not require it for ordinary continuation.

**Agent tooling installation evidence:** workspace-local Ripwire 0.6.1 was built offline from the user-provided archive (archive SHA-256 `5ae0fb9a8efde50e67cf0849a2170b8c93ba192101860bf9845696a6803b144c`; binary SHA-256 `78684f8f14840d360b9ab249e70d5e15bbac592809c5bbcdae716147da7e7747`) and `ripwire --doctor` passed 8/8. Repo-local rules are in `AGENTS.md` and `docs/development/RIPWIRE-WORKFLOW.md`.

**Current task:** **P11.4 available source/release-integration review is complete at `ed53fc5`, but genuine independent review remains BLOCKED; P11.1, P11.2 and P11.3 also remain BLOCKED for release acceptance where real runtime proof is unavailable.** P11.4 found and repaired two stale regression assertions only: the Android Smart Library audit now checks the current Progress-owned/user-scoped `reading_state_v1` contract, and the PostgreSQL-backup dependency pin gate no longer requires retired `curl`. Fresh source evidence: Web reading 31/31; Android source 8/8 plus full static audit; migration/quiescence 21/21 plus ordering; P09 ownership/security/readiness 34/34 + 28/28; P10 truthfulness/races 50/50; API ownership + 139/139 route coverage; resource guards; exact current-release validator PASS on its source/static path. Caveman exposes no independent reviewer/subagent integration here, so self-review is not counted as independent. Canonical evidence: `docs/qualification/2026-09-17-rc485-p11.4-release-integration-review.md` plus its TSV matrix. Do not advance to final release qualification until independent review and all required P11 runtime gates are actually executed. Real-host P12.2 deployment testing then exposed a host-Python launcher regression; source checkpoint `3397e5c` removes direct shell `python`/`python3` dependencies through one canonical host-or-Docker Python resolver. Real-host bootstrap then exposed Windows recovery-root normalization failures after fresh `.env` creation; `6f32a59` covered `/c/...` and `HOME` fallback, and `1d17ce5` hardens the central resolver for `/cygdrive/c/...` plus native `%USERPROFILE%` recovery through `cmd.exe` with MSYS path conversion disabled. The current source-test package `mreader-rc485-p12.2-source-test-3020fc3.zip` is the deployment-testing authority; direct Git-Bash tracing showed the repeated post-volume-check path error came from the Linux-only fresh-env regression fixture invoked by hybrid validation, not from the real recovery root. Fresh Windows/Git-Bash installs with no explicit database-protection root now use the dedicated `C:/mreader/database-protection` host mount; bootstrap persists and creates it before stateful adoption/preflight. These repairs do not close any P11 runtime/independent-review gate.

**Current deployment-test package:** `mreader-rc485-p12.2-source-test-a7d7a40.zip` from exact source `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6`; earlier P12.2 ZIPs and the milestone-1 package remain preserved. The next final package is P12.3 only after the remaining P11 runtime and independent-review gates actually pass.

This is the central progress record. Detailed implementation plans and dated test reports support it; they do not maintain a competing overall status. No overall percentage is reported because source completion, runtime verification, and release readiness are different facts.

## Global constraints

- Retain Docker Desktop Kubernetes for stateless user/admin planes; Compose for PostgreSQL, critical Valkey, cache Valkey, RabbitMQ, Image Edge, and the existing backup agent; external NAS SeaweedFS for published media.
- Retain KEDA/HPA and the existing resource limits. Browser scraping remains on demand. Do not introduce Azure deployment changes in this release.
- Keep the public gateway separate from the private admin gateway. Preserve both configured development-edge options; expose only the gateway.
- Preserve current NAS object identities and protected-image encoding metadata. Recovery validation must not rewrite NAS content.
- Keep chapter grants and protected v4 delivery. Unknown/unsupported clients or formats receive a clear contract error, not legacy fallback behavior.
- Preserve existing data, configuration, and authoritative volume selections. Removing duplicate code is not authority to reset storage.
- No live production restore or destructive migration is executed merely to test this release. Use isolated fixtures and explicit operator procedures.
- No new UI-backend service, application database, broker, or persistent Smart Library table. The only newly authorized business-support tables are `ingestion_operations` and `catalog_mutation_receipts`.
- Target final release: `1.3.0-rc4.85`; Android **Mreader / ver.1.1.0**, build code **485**. Update runtime labels together at the release gate; milestone 1 intentionally retains the existing RC4.84 labels/build 484.
- Recovery root: resolved host user's `.mreader/database-protection`, explicitly configured as `MREADER_DB_PROTECTION_ROOT`; dumps **4 days**, snapshots **2 days**, with explicit active-operation safety pins.
- The user's later instruction authorizes a full application **source test package when a major blocker is resolved**. It does not authorize representing an unqualified checkpoint as a final release or compiled APK.

## How progress is recorded

| LabelMeaning         |                                                                                              |
| -------------------- | -------------------------------------------------------------------------------------------- |
| Queued               | Work is identified; implementation has not started.                                          |
| Active               | The next implementation task being worked on.                                                |
| Source implemented   | Code exists and the recorded source/fixture checks ran; release gates may still be open.     |
| Partial              | Some parts exist; named integration or behavior is still missing.                            |
| Blocked verification | The required test has not run because its environment or dependency is unavailable.          |
| Verified             | The named acceptance gate ran successfully against the recorded source and required runtime. |

Check a subtask only when its stated outcome is achieved. In each update record task ID, source commit, command/test result, evidence type, remaining limitation, and next action. A skip never closes a gate. Reviews may reopen source-implemented tasks. Independent review is still required where listed; a self-review is not recorded as independent review.

At the start of each continuation, read this tracker, inspect the working-tree changes, and resume the current task. At a checkpoint, update this file before saving the source patch/package. Reconcile new requests into the affected task rather than starting a separate undocumented track. Do not include unrelated working-tree edits in packages.

## Workstream status

| IDWorkstream / domain ownerImplementation statusEvidence and remaining exit condition |                                                                            |                      |                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P01                                                                                   | Baseline and capabilities / release integration                            | **Verified**         | Sequential review `fda3b03`: package provenance and nine-surface capability matrix completed; table disposition is maintained forward and now covers the 38-current-table sequential schema plus retired identities through migration 060; `database_restore_state` is explicitly classified as a technical restore-generation mirror, not another business/recovery authority. BASE-01 closed; OWN-01 permission enforcement remains P09. |
| P02                                                                                   | Reading persistence and Library / Progress + Social projection             | **Source qualified / blocked runtime** | Sequential review `8ea00ff`: 7/7 focused source audits passed; normal HTTP commands own synchronous PostgreSQL ledger/resume/outbox writes, Social consumes `reading_state_v1`, and legacy stream drain is maintenance-only. Go/API/SQL runtime gates remain blocked by Go 1.23 vs required 1.25, absent PostgreSQL/Docker tooling and missing `psycopg`. |
| P03                                                                                   | Immediate local reading / Web repository                                   | **Source qualified / blocked browser runtime** | Sequential review `15ee796`: 31/31 focused production-state tests pass; one Web repository/account-origin journal owns pending state; Library/Catalog/Series consume canonical projections plus bounded pending overlays; test entrypoint now exposes loader errors correctly. Frontend build, real browser scenarios and independent review remain open. |
| P04                                                                                   | Android reading and origin alignment / Android repository                  | **Source qualified / blocked Android runtime** | Sequential review: 8/8 source audits + 11/11 pure-Kotlin journal behaviors pass; one build-configured origin, Smart Library history ownership, chapter-grant mobile reader, logout/account isolation and WebView host fencing confirmed. Full Gradle/device/upgrade and independent gates remain open. |
| P05                                                                                   | Reading migration and upgrade / migration executor                         | Partial              | One runner; preservation before pending 047/048; migration 052. Six shell cases passed. Actual PostgreSQL, writer quiescence and grants remain open.                                                                  |
| P06                                                                                   | Production publication / Catalog with Media evidence                       | **Source reconstructed / blocked runtime** | P06.4 caller cutover is reconstructed through `8ecc4c4` (historical `631ddbf`), scoped-secret prerequisite through `0f1fadb` (historical `4325575`), P06.5 private transport auth through `581c310` (historical `c82650a`), and P06.6 event/dedupe finalization through `d79e340` (historical `2954469`). P06.3 real PostgreSQL runtime suite remains deferred/unexecuted. |
| P07                                                                                   | Ingestion, cancellation, storage cleanup / Scraper coordinator + Lifecycle | **Source qualified / blocked runtime** | P07.1 header convergence is reconstructed at `24adb72`, P07.2 lease/cancel fencing at `f5c34a7`, P07.3 Stage/Retry repair + cover consolidation at `6e42f6b`, P07.4 generation-bound Lifecycle cleanup at `394e440`, and P07.5 canonical status/UI convergence at `26d80a1`. Actual PostgreSQL/worker/KEDA/browser qualification remains P11 runtime debt. |
| P08                                                                                   | Recovery catalog, downloads and restore / Protection module + backup agent | **Source-qualified / runtime-blocked through P08.8** | P08.1/P08.2 host root, catalog, queue and operator alignment are implemented; P08.3 private download `c5e6866`; P08.4 facade `c8a7c52`; P08.5 import/paging/retention `d264486`; P08.6 restore-source/catalog-only safeguards `f051fc7`; P08.7 drill source `8f01117`; P08.8 cutover fencing/interruption recovery `cbaf5a8`. Actual Docker/PostgreSQL drill/interruption rehearsal remains blocked here; runtime proof continues in P11/P09.4 integration. |
| P09                                                                                   | Permissions and API/event contracts / each domain + migration/deployment   | **P09.5 source-qualified / user-held recovery fallback accepted** | P09.1 scoped secrets `0f1fadb`; P09.2 ownership/routes `289337e`; P09.3 grants `67303f6`; P09.4 readiness/generation `56337e0`; P09.5 route/consumer denial `7c292fe`. Current authority is 139 routes with 10 proven direct HTTP→event effects; focused 24/24, full 345/10 skips/0 failures, Scraper 18/18, ownership/route 139/139, TypeScript/compile/static gates green. Android Gradle and Go >=1.25 remain toolchain-blocked; P09.3/P09.4 real runtime gates remain blocked. |
| P10                                                                                   | User/admin UI capability and failure behavior / Web + Android              | **P10.2 durably checkpointed** | P10.1 is durably checkpointed; P10.2 source stack `b15b417` + `cad8826` closes stale-response, account/origin, repeated-submit and outage ambiguity across existing UI owners with focused 50/50 and dependency-light 395/10 skips/0 failures. Tracker `65f0c2e` immutable/current Library packages independently round-tripped at SHA-256 `b92276c156797e27389b3b9c286c0e88052576a5df7a2d24609717035457c6d5` with 19 advertised / 17 real refs and exact stash. |
| P11                                                                                   | Runtime, recovery and load qualification / release integration             | **P11.1 blocked verification** | Same-checkpoint qualification at `65f0c2e` attempted every changed Go/Python/TypeScript/Web/Android build surface plus the API harness. Go 1.25, Node dependencies, Gradle, exact Python runtime packages and Docker/PostgreSQL/gateway runtime are unavailable and cannot be restored from local caches/blocked DNS. Python syntax compile passes only; no blocked build/API gate is marked passed. See `docs/qualification/2026-09-17-rc485-p11.1-same-checkpoint-build-runtime.md`. |
| P12                                                                                   | Delivery and continuation / release integration                            | Partial              | Milestone 1 source package delivered. Milestone 2 and the fully qualified release remain open.                                                                                                                        |

The assistant carries implementation and tracking. The domain column identifies the application's authority, not a second human assignee. Review status and test execution are recorded separately.

## Ownership rules used in every task

| Fact or responsibilityCanonical ownerWhat consumers may do |                                           |                                                                                                          |
| ---------------------------------------------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Users, sessions and avatar                                 | Auth                                      | Authenticate and read declared profile/session contracts.                                                |
| Series, chapters, pages, taxonomy, curation                | Catalog                                   | Read projections; submit domain commands for mutations.                                                  |
| Resume, exact chapter evidence, completion                 | Progress                                  | Submit ordered commands; read `reading_state_v1` through declared contracts.                             |
| Bookmark, follow, rating, comments                         | Social                                    | Read public aggregates/personal state and invoke Social mutations.                                       |
| Library counts, filters, Recently Opened, actions          | Social read projection                    | Consume one response; no independent history count merge or persisted Library owner.                     |
| Unsynced reading intent                                    | One repository per client/account/origin  | Render pending state, retain retryable commands, reconcile acknowledgements; never invent server totals. |
| Ingestion overall status and cancellation                  | Scraper ingestion coordinator             | Observe one operation header; detailed staging/media status remains subordinate.                         |
| Encoding, immutable object outputs, completion evidence    | Media (`services/image_service`)          | Catalog validates declared evidence; Media cannot publish production metadata.                           |
| Production-object deletion and retries                     | Lifecycle                                 | Execute transactionally recorded exact-object cleanup intent; events only wake the worker.               |
| Notification creation/deduplication                        | Notification worker                       | Social may mark read/prune through explicitly scoped permissions.                                        |
| Delivery state                                             | Outbox Relay                              | Publish/retry; domain owners append events with their own mutations.                                     |
| Recovery artifacts and operations                          | Protection module + existing backup agent | Admin facade/CLI use opaque IDs and one queue/restore engine.                                            |
| Migrations and grants                                      | Migration role                            | Runtime readiness checks required versions/permissions; no broad credential fallback.                    |

## Execution order and actionable tasks

### P01 — preserve the baseline and capability contract

**Files:** the approved spec and its archive-hash appendix; `tests/api/endpoint_coverage.tsv`; existing `tests/api/test_04_catalog_reads.py` through `test_27_mobile_reader_adapter.py`; create `docs/qualification/RC485-CAPABILITY-MATRIX.md` when mapping the remaining surfaces.

**Consumes:** the four original archives and the r5 source baseline `7d6b74c`. **Produces:** one capability-to-owner/API/test/disposition matrix for RC4.81 behavior and r2 corrections retained in RC4.85.

- [x] P01.1 Record the original archive identities/hashes and preserve r5 as the source baseline.
- [x] P01.2 Reconcile the current source commits and evidence into this tracker.
- [x] P01.3 Map Browse/Search, Series, Reader, Library, account/alerts, admin content, ingestion, curation and DB Protection controls to their current handlers and acceptance tests. Record removed mechanisms separately from retained capabilities.
- [x] P01.4 Complete a table-by-table disposition inventory: owner, current readers/writers, migration-only references, retained capability and retirement prerequisite. Include ORM writers; a text-search miss is not proof a table is unused.

**Acceptance:** BASE-01. OWN-01 also consumes the table inventory. Historical continuity-safe RC4.84 plans remain reference material, not the RC4.85 master plan.

### P02–P04 — qualify the reading work already implemented

**Files:** `services/progress_go/internal/progress/service.go`, its store/tests; `services/social_ts/src/routes.ts`; `frontend/src/reading/`; Android `core/repository/ReadingJournal.kt`, `ReadingRepository.kt`, `core/settings/ServerConfigStore.kt`; `tests/api/test_26_reading_commands.py`, `test_17_smart_library.py`, `tests/regression/test_web_reading_repository.mjs`, Android `ReadingJournalTest.kt`.

**Detailed plan:** Reading consistency.

**Consumes:** authenticated account, open/commit commands, canonical revision/session/sequence. **Produces:** committed PostgreSQL acknowledgement, one Library envelope, and account/origin-scoped local pending state on both clients.

- [x] P02.1 Implement atomic resume/ledger/outbox writes and the canonical reading projection; remove normal Redis write-behind acknowledgement. Sequential source re-review: `8ea00ff`; runtime qualification remains separate.
- [x] P03.1 Implement the shared Web journal, pending UI, immutable retry and account/late-response fixes; run the 31 focused Node cases. Sequential source re-review: `15ee796`; browser/build qualification remains separate.
- [x] P04.1 Implement Android's shared journal/current API and one-origin migration; remove the independent recent-read owner; write 11 Kotlin cases. Sequential source re-review reproduced 11/11 pure-Kotlin behaviors and 8/8 ownership/origin audits; runtime qualification remains separate.
- [ ] P02.2 Run actual API and SQL cases for immediate reads, duplicate/conflicting/reordered commands, account switch, exact checkpoint identity, explicit completion and reach-only evidence. **Blocked here:** Go 1.25/runtime PostgreSQL/Docker/`psycopg` unavailable; do not treat source audit as acceptance.
- [ ] P03.2 Finish independent scoped review and execute the real Web build/browser cases. **Source coverage advanced at `d7fd294`:** dedicated Playwright scenarios now cover two tabs, quota failure, offline refresh, late acknowledgement and media failure and are enforced by the current-release validator. Real Playwright execution and independent review remain outstanding, so P03.2 is not accepted.
-  P04.2 Finish independent review; compile/test Android and rehearse upgrade from obsolete origin preferences, process death, reconnect, logout and native/WebView contract alignment.

Reproduce the currently runnable Web evidence with:

```bash
node --test tests/regression/test_web_reading_repository.mjs

```

**Acceptance:** READ-01, READ-02, READ-03, READ-04, LOCAL-01, LOCAL-02, LOCAL-03, LIB-01, AND-01 and the reading portion of UI-01. The Node test alone does not close these combined runtime gates.

### P05 — complete the preservation and upgrade boundary

**Files:** `ops/migrate/render.sh`, `apply.sh`, `run.sh`; `db/upgrade/preserve-reading-evidence.sql`; migration `052_reading_evidence_provenance.sql`; `scripts/hybrid/stateful-up.sh`, `scripts/backup/backup-agent.sh`, `scripts/migrate.sh`; `tests/regression/test_migration_runner.py`, `test_reading_upgrade_postgres.py`.

**Detailed plan/evidence:** Reading upgrade preservation, recorded results.

**Consumes:** supported historical databases and their actual migration ledgers. **Produces:** preserved canonical evidence, one serialized migration result, and readiness only after invariants/grants pass.

-  P05.1 Share one migration executor between upgrade and restore; preserve evidence before pending 047/048 without changing their shipped bytes.
-  P05.2 Separate inferred reach from exact history/recency, and include reach-only evidence in Library unread calculations.
-  P05.3 Execute six shell-runner cases and write ten actual PostgreSQL cases, including the production Library SQL.
-  P05.4 Add coordinated old-writer/consumer quiescence and explicit legacy-stream drain before destructive steps; prevent mixed-version mutation services from resuming early.
-  P05.5 Run the actual runner against RC4.81, r2/r4/r5, fresh, partial, interrupted and concurrently started migrations. Validate counts, chapter links, completion evidence, roles and already-lost-history reporting.
-  P05.6 Reconcile legacy backup/scraper terminal and uncertain operations before retirement; never requeue completed work or infer missing historical data.

Available shell verification:

```bash
python3 -m unittest discover -s tests/regression -p test_migration_runner.py -v

```

The PostgreSQL suite requires `psql` and an explicitly configured disposable `MREADER_TEST_POSTGRES_DSN`; a skipped run is not acceptance.

**Acceptance:** MIG-01, MIG-02; final grants/readiness depend on P09. Real migration qualification precedes any release claim of safe upgrade.

### P06 — make Catalog the sole production publisher (current)

**Files:** Catalog `internal/httpapi/api.go`, `internal/store/store.go`, `internal/store/events.go`; Scraper `app/publication.py`, `drafts.py`, `batch_queue.py`, `series_drafts.py`; Media `app/services/chapter_ingestion.py`, `app/media_operations.py`; shared event schemas; new publication command/receipt schemas and focused tests under `contracts/` and the owning service test directories.

**Consumes:** operation ID, requesting-admin identity, source revision, stable idempotency key, payload digest, target identity, expected Catalog revision and durable Media output evidence. **Produces:** one authoritative Catalog mutation receipt and publication revision, with chapter/pages, outbox and cleanup effects in the same transaction.

-  P06.1 Trace all three production chapter writers and new-series/taxonomy creation. Findings and exact current files are recorded below.
-  P06.2 Write a focused implementation plan and failing command-contract fixtures for incomplete/unverified manifests, valid v4 metadata, bounded pages, invalid object paths, same-key/different-body conflict and retained admin identity. Define the private `/internal/v1/catalog` request/receipt interface before switching callers. Source evidence is recorded in `docs/qualification/RC485-CATALOG-PUBLICATION-CONTRACT.md`; this does not close PUB-01/PUB-02.
-  P06.3 Implement durable Media completion evidence and Catalog transaction/revision/idempotency receipts. Conversion/upload occurs before the short Catalog transaction. Add real DB tests for concurrent publish, stale replacement, response loss and receipt replay.
-  P06.4 Route manual upload, existing-series scrape, batch and new-series workflows through the same Catalog commands. Convert series/taxonomy/cover mutations as well as chapter/page commits. Preserve ZIP/CBZ/PDF and optional first/last pages.
-  P06.5 Make existing admin write routes invoke the same domain implementation; authenticate workload and retained admin identity; deny the internal interface through both gateways.
-  P06.6 Version publication events and notification deduplication by publication revision. A metadata edit or retry must not create a new chapter notification. Remove superseded production writers only after replacement paths are wired.

**Acceptance:** PUB-01, PUB-02 and relevant API-01 checks. Before this work is source-complete, verify by SQL and ORM inspection that Scraper/Media no longer implement production table writes. P09 then enforces that boundary with database permissions. Do not advertise a partially wired command as a resolved publication blocker.

### P07 — unify ingestion, cancellation and cleanup

**Files:** Scraper workflow files listed in P06, `app/storage_attempts.py`, `app/staging_store.py`, `app/operation_events.py`; Media `app/lifecycle_worker.py`, `app/routers/lifecycle.py`; Catalog delete/replacement commands; `frontend/src/pages/AdminScraperOperations.tsx`; existing scraper/admin storage screens and API fixtures.

**Consumes:** P06 receipts, immutable object references, draft revisions and worker generations. **Produces:** one `ingestion_operations` header, durable cancellation/reconciliation, and exact owned-object cleanup jobs.

-  P07.1 Create the common operation header for manual/batch/existing/new-series entry points. Preserve editable detail records and make acknowledgement a visibility field.
-  P07.2 Write and implement worker lease/fence and cancel-versus-commit cases. Known commit preserves published content; unknown outcome preserves objects and reconciles; cancelled means no worker can still publish.
-  P07.3 Restore explicit URL-backed Stage/Retry repair with revision/fence checks. Missing manual input requires re-upload; Publish/Preview remain strict staging readers. Consolidate covers through Media.
-  **P07.4 — source-qualified at `394e440`.** Catalog captures exact primary/responsive/cover references and generations in deletion/replacement transactions; Lifecycle alone performs production deletion after live ownership fencing; delayed cleanup cannot delete replacement output; legacy broad-prefix jobs are quarantined.
-  **P07.5 — source-qualified at `26d80a1`.** New-series series-level status is projected from a canonical parent `ingestion_operations` header; child publication operations link to that parent; coordinator transitions, retry and recovery synchronize it; admin UI separates canonical operation state from workflow detail; Catalog DELETE returns a cleanup receipt so metadata removal is distinct from asynchronous storage cleanup. Existing workflow-status/events routes remain because active UI consumers still require them; the obsolete publish-status alias remains retired. Actual PostgreSQL/worker/KEDA/browser execution remains P11 runtime debt.

**Acceptance:** ING-01, DEL-01; notification/outbox ownership and generation contracts integrate with P09. P06 and P07 together form the next major application-source milestone.

### P08 — finish host-local DB Protection and restore

**Files:** `scripts/env/db-protection-root.sh`, `scripts/env/resolve-db-protection-root.sh`, `scripts/backup/local-recovery-store.sh`, `backup-agent.sh`, `postgres-backup.sh`, `postgres-restore.sh`, `scripts/recovery/catalog-restore.sh`; current Scraper `app/database_protection.py`, `app/main.py`; `frontend/src/pages/AdminDatabase.tsx`; Compose/Kubernetes/gateway wiring and existing DB protection tests.

**Detailed plans:** Recovery root, mandatory safety capture, local catalog, operator alignment.

**Consumes:** one resolved host root and verified opaque recovery IDs. **Produces:** one compact catalog, capture/download/drill/restore capabilities and a recoverable, fenced cutover using the existing engine.

-  P08.1 Implement host-home root, full application dump plus globals, local verified-bundle catalog and a single `database_operations` queue.
-  P08.2 Align startup/doctor/CLI roots and one-time 4/2 retention migration; preserve custom settings and original configuration. Fourteen focused startup checks passed; milestone 1 delivered.
-  P08.3 After P09.1 narrows secrets, add a narrowly authenticated read-only bridge in the existing backup-agent deployment. Restore download by opaque ID without exposing host paths, adding a public file route, or mounting the user's home into Kubernetes API pods.
-  P08.4 **Source-qualified at `c8a7c52`.** Extract the facade from scraper staging readiness and move UI/gateway/API together to `/api/admin/database`. One `database_operations` queue/recovery catalog/restore engine remains authoritative; old `/api/scraper/admin/database*` aliases are retired after consumer migration.
-  P08.5 **Source-qualified at `d264486`.** Explicit import of verified legacy/NAS bundles re-verifies into the canonical local store with local provenance; incompatible PostgreSQL majors, unsafe roots and tampered bundles are rejected; active restore/drill sources and unresolved cutover markers become transient retention pins; current pre-upgrade/pre-restore safety points and the last verified recovery point are retained; capture completion UTC drives aging; recovery inventory uses bounded opaque keyset paging through the admin facade/UI.
-  P08.6 **Source-qualified at `f051fc7`.** Normal restore accepts only `latest`, `latest-snapshot` or opaque verified `bkp_...` IDs and resolves them through the canonical local store before destructive preparation; catalog-only recovery stages its verified donor through that same store, preserves empty-target exact seven-table scope, and creates its pre-import safety point through the existing backup-agent engine rather than a second direct dump path.
-  P08.7 **Source-prepared/runtime-blocked at `8f01117`.** Logical and snapshot drills reuse the canonical opaque-ID/`database_operations` restore engine, apply current migrations, publish structured row/FK/v4-encoding/database-encoding/latest-migration/runtime-grant/extra-database evidence, and the operator drill composes the existing read-only NAS/media validation with isolated restore-drill execution. Source gates are green; actual Docker/PostgreSQL drill execution remains open because Docker is unavailable in this sandbox.
-  P08.8 **Source-qualified/runtime-blocked at `cbaf5a8`.** Restore confirmation/queueing is bound to installation fingerprint + exact opaque source/hash + expected host generation; claim/pre-cutover rechecks fail closed; source and safety IDs are pinned; a host-owned v2 phase journal brackets destructive transitions and restart reconciliation; restored replay-unsafe ingestion/media/outbox work is selectively invalidated before PostgreSQL mirror/host generation commit; drills remain outside production cutover state. Actual Docker/PostgreSQL interruption rehearsal remains blocked because Docker is unavailable.

**Acceptance:** PATH-01, DBP-01, DBP-02, DBP-03, DBP-04. Logical scope is the configured MReader database plus globals; snapshot scope is the PostgreSQL cluster. The UI restore restores the MReader database even when the input is a snapshot.

### P09 — enforce ownership in credentials, routes and events

**Files:** `scripts/hybrid/deploy.sh`, `deploy/docker-desktop-hybrid/`, `deploy/compose/`, `db/migrations/`, each service readiness implementation; new machine-readable ownership/route manifest under `contracts/`; existing event schemas; `tests/api/endpoint_coverage.tsv`, `test_23_endpoint_contract_matrix.py`, `test_24_deep_route_coverage.py` and route source audits.

**Consumes:** P01 inventory, P06/P07 command boundaries, P08 transport needs. **Produces:** explicit allowed writers/read contracts, private secrets/routes, required readiness checks and attributable error/event contracts.

-  P09.1 **Source-reconstructed/qualified at `0f1fadb`.** Whole-environment copying is replaced with explicit namespace/workload secret selection; unrelated/public-plane workloads do not receive the scoped private credentials. Preserve this prerequisite; do not redo it in sequential P09.
-  P09.2 **Source-qualified at `289337e`.** The versioned 136-route ownership manifest, strict schema, handler provenance, same-tree route/gateway/auth/evidence audit, first-party consumer evidence and static validation integration are committed. Runtime route registration beyond available static/source evidence remains P11 debt.
-  P09.3 After replacement writers work, enforce non-superuser domain grants and column/function exceptions for notifications, outbox delivery, cleanup enqueue and authorized cascades. Execute permitted and forbidden SQL/ORM mutations under each real runtime role.
-  P09.4 Fail readiness on missing owner schema/grants; complete quiescence/restart and restore-generation fencing. Do not fall back to broad credentials.
-  P09.5 **Source-qualified at `7c292fe`.** Registered handlers, both gateway policies and Web/Android adapters are compared against the same-tree ownership authority; denial tests cover retired/private/admin/Catalog-write surfaces. Route discovery now includes the three registered Media `internal_router` handlers, expanding the canonical authority from 136 to 139 routes. The manifest records 10 source-proven direct HTTP→event effects, and safe owner/error/request/operation/revision metadata is propagated through gateways/clients and the existing outbox envelope without a second registry. Runnable evidence: focused 24/24; full dependency-light 345 with 10 skips; Scraper 18/18; ownership/route 139/139; API ownership/route/WebP, Python compile, TypeScript typecheck, `gofmt`, diff check; targeted Ripwire changed-scope `gating=0`. Android Gradle and Go >=1.25 compile remain blocked by sandbox tooling.

**Acceptance:** OWN-01, API-01, with MIG-01/MIG-02 and DBP-04 integration. P09.1 is an independent prerequisite for P08.3; final grants wait for the callers they restrict.

### Dependency checkpoints

| Before this actionRequired prerequisite   |                                                                                                                         |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| P06 caller/authentication cutover         | P06 command/receipt contract and tests; P09.1 secret selection before private credentials are wired.                    |
| P07 terminal cancellation                 | P06 receipt reconciliation and an enforced worker fence; unknown outcomes remain reconciling.                           |
| P08 private recovery download             | P09.1 secret selection; one authenticated host-owner interface and catalog capability contract.                         |
| P09 restrictive domain grants             | Replacement callers from P06/P07/P08 pass their applicable tests; then execute positive and negative permission checks. |
| Any destructive upgrade/restore rehearsal | Isolated fixtures, verified safety capture, appropriate writer fencing, and an explicit test target.                    |
| Final qualified package                   | P01–P11 acceptance gates and independent reviews complete against the exact integrated source.                          |

### P10–P11 — verify the whole application without removing capabilities

**Files:** P01 capability matrix; all user/admin screens and their adapters; `tests/api/`, `tests/regression/`, load fixtures, Android test sources; `scripts/validate-current-release.sh`, `scripts/hybrid/validate.sh`; qualification reports under `docs/qualification/`.

**Consumes:** integrated same-checkpoint services/clients and isolated test infrastructure. **Produces:** real build/runtime/recovery/load evidence attached to every acceptance gate.

-  P10.1 **Source-qualified at `c09227d`.** Verified all nine UI surface groups: Browse/Search, Series, Reader, Library, Account/Alerts, admin content, ingestion, curation and Database Protection. Concrete defects were repaired with RED→GREEN coverage: recoverable pagination, truthful optional-service/unknown states, account/filter-scoped Android notifications, PDF upload parity, actual staged-page replacement, Android announcement link/dismiss behavior, and fail-closed Database Protection unknown state. Fresh evidence: focused 43/43; dependency-light 388/10 skips/0 failures; Reader 31/31; Android Reader 8/8; ownership/route/WebP PASS; Python compile/diff PASS; committed-tree Ripwire `dd410f7..c09227d` `gating=0`. Frontend node_modules, Android Gradle wrapper, Scraper selectolax, and one backup-daily fixture remain environment/runtime blocked rather than passed.
-  P10.2 **Source-qualified through `cad8826` (behavior/source `b15b417`).** Delayed/out-of-order optional-service responses are generation/identity fenced; Web/Android notification results cannot cross account switches; Database Protection and Scraper polling reject stale page/filter results; bookmark/follow plus destructive series/chapter actions are single-flight and identity-scoped; staged-series polling is single-flight. Existing Reader/offline/local-pending, Realtime fallback and lifecycle/NAS ambiguity contracts remain green. Fresh evidence: focused P10.1+P10.2 50/50; dependency-light 395/10 skips/0 failures; Reader 31/31; Android Reader 8/8; lifecycle 5/5; ownership/route 139/139; WebP/pressure/storage/Python/diff PASS; Ripwire `ecb8c18..cad8826` `gating=0` with one targeted proven analyzer false-positive acknowledgement. Frontend node_modules, Android Gradle wrapper, Scraper selectolax and Go >=1.25 remain environment/toolchain blockers.
-  P11.1 **BLOCKED verification at `65f0c2e`:** all changed Go/Python/TypeScript services, Web and Android were attempted from the same detached checkpoint; exact commands/exits are recorded in `docs/qualification/2026-09-17-rc485-p11.1-same-checkpoint-build-runtime.md`. Required toolchains/dependencies/runtime are unavailable here, so build/API acceptance remains open.
-  P11.2 **BLOCKED acceptance / sequencing-waived:** all available source-version and recovery fixtures were executed at the unchanged checkpoint; 123 migration/recovery tests passed with 10 explicit real-PostgreSQL skips, dependency-light recovery contracts are green except two inherited fixture hangs, and real restore/backup entrypoints fail closed before mutation because Docker/PostgreSQL/Kubernetes topology is unavailable. Evidence: `docs/qualification/2026-09-17-rc485-p11.2-upgrade-restore-rehearsal.md`.
-  P11.3 **Dependency-light/source-qualified at `a88e275`; runtime acceptance BLOCKED:** stale KEDA regression expectation aligned to the already-enforced P09.3 dedicated scaler DSN; resource/queue/cache/concurrency source gates pass without raising limits; Smart Library SQL/index shape was inspected; reading and publication concurrency source suites pass. Real PostgreSQL plans, live service concurrency, spike/soak budgets, KEDA/HPA behavior and multi-replica cache behavior remain unexecuted because Docker/kubectl/psql/k6 are absent. Evidence: `docs/qualification/2026-09-17-rc485-p11.3-performance-resource-qualification.md`.
-  P11.4 **AVAILABLE SOURCE/RELEASE-INTEGRATION REVIEW COMPLETE at `ed53fc5`; INDEPENDENT REVIEW BLOCKED:** the current-release validator and available Web/Android/migration/P09/P10 source review scopes pass after two stale regression assertions were corrected. Production behavior/resources were unchanged. A genuinely separate reviewer/subagent is unavailable in this sandbox, so Web P03.2, Android P04.2, migration P05.5 independent review and P11.4 acceptance remain open. Preserve all P11.1-P11.3 runtime blockers as blockers.

**Acceptance:** UI-01, PERF-01, REL-01 and closure of every applicable gate listed below. Static/source regressions remain useful but cannot substitute for these runtime results.

### P12 — package at meaningful checkpoints and preserve continuity

**Consumes:** exact committed source plus verification evidence. **Produces:** a reproducible source archive and a self-contained continuation record.

-  P12.1 Deliver milestone 1 full source test package after the recovery startup blocker correction.
-  P12.2 **CURRENT DEPLOYMENT TEST PACKAGE at `3020fc3`.** Earlier P12.2 packages remain preserved. The current `mreader-rc485-p12.2-source-test-3020fc3.zip` packages exact clean tree `3020fc3` with the retained no-host-Python/shared Windows-path repairs plus the Git-Bash-safe fresh-env regression fixture. A blank Windows root resolves to the dedicated `C:/mreader/database-protection` host mount; if Git Bash still carries an invalid stale process-level `MREADER_DB_PROTECTION_ROOT`, bootstrap now ignores that stale value and persists the dedicated root instead. Valid intentional process overrides and existing explicit saved roots remain authoritative under the existing safety fences. Fresh evidence: TDD RED reproduced the exact real-host error; recovery-root 18/18; dedicated-root/explicit-root bootstrap PASS; local pre-upgrade 5/5; local database-protection 4/4; storage/pre-upgrade/volume/no-host-Python/MSYS contracts PASS; ownership 139/139; PostgreSQL role audit 15 capabilities / 18 workload identities; current-release validator PASS on source/static path. The ZIP contains 940 committed-tree files, 942 verified package checksum entries, deterministic rebuild is byte-identical, SHA-256 `8bd99bfdd6e0763d6a5b22977c450a2012e8682520b849340758cd96529f01b3`. Direct resolver tracing proved the real `C:/mreader/database-protection` value was valid; the repeated Git-Bash error came from the Linux-only `bootstrap-fresh-env.sh` fixture invoked by hybrid validation, now made platform-aware. P11.1-P11.4 acceptance blockers remain open.
-  P12.3 After all release gates pass, update release/image/documentation labels and Android build code together, validate the exact final tree, and publish the qualified package. Do not label source ZIPs as APKs.
-  P12.4 For each subsequent continuation, update this tracker and persist the source checkpoint. No new package is needed solely for documentation or a plan change.

## Current blocker register

| IDUser-visible consequenceEvidence / ownerResolution task |                                                                                                                                      |                                                                                                                          |                                                                                                                                                                                                 |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B01                                                       | Different ingestion paths can reach publication through different owners, making retry/status behavior hard to prove consistent.     | **Source boundary closed through `26d80a1`:** manual/existing/batch/new-series converge on Media evidence → Catalog, one canonical ingestion header/generation/cancellation model is used, and new-series parent status is synchronized across retry/recovery paths. P06.3 runtime DB evidence remains deferred/unexecuted. | Runtime PostgreSQL/worker/KEDA qualification remains P11 debt. |
| B02                                                       | Cancellation, delayed work and cleanup need a shared receipt/fence decision before the UI can truthfully claim cancelled or removed. | **Source/UI boundary closed through `26d80a1`:** canonical operation status is exposed separately from workflow detail; Catalog deletion returns a queued Lifecycle receipt instead of implying physical deletion; generation/receipt fences remain intact. | Actual restart/worker-loss/KEDA/browser runtime proof remains P11 debt. |
| B03                                                       | Recovery download lacked a private host-owner transport.                                                                              | **Source boundary closed through `c8a7c52`:** P08.3 adds the authenticated opaque-ID host bridge at `c5e6866`; P08.4 moves the admin facade/consumers together to `/api/admin/database` without exposing host paths or adding another recovery engine. | Real host/container/browser runtime proof remains P11 debt. |
| B04                                                       | New private credentials would spread too widely if added to current environment wiring.                                              | **Source boundary closed through `c5e6866`:** workload-specific secret rendering from `0f1fadb` is preserved and the recovery-bridge credential is limited to the backup-agent/Scraper transport boundary; frontend/browser scopes do not receive it. | Preserve this boundary through P08.4+ and prove runtime secret delivery/rotation under P11. |
| B05                                                       | Safe upgrade/restore must survive live writers, interrupted cutover and stale jobs.                                                   | **Source boundary closed through `cbaf5a8`:** P08.8 adds installation/source/generation confirmation fences, source+safety pins, external phased cutover journal, deterministic interruption reconciliation and selective stale-work invalidation. Actual Docker/PostgreSQL interruption rehearsal plus final runtime grants/readiness remain open. | Execute destructive/restart rehearsal on an authorized runtime, then complete P09.3–P09.4 grants/readiness integration and P11 qualification. |
| B06                                                       | Actual application/runtime acceptance cannot be claimed in this workspace.                                                           | Fresh 2026-09-15 probe on restored HEAD `0d60bcc`: exact P06.3 Docker gate exits 2 before DB startup because Docker is absent; podman/nerdctl and local PostgreSQL binaries are absent; local Go is 1.23.2 with no cached 1.25 toolchain; official runtime artifact/package downloads are blocked in this sandbox. Source qualification remains green but is not runtime acceptance. | P11; execute the unchanged combined Catalog + Notification PostgreSQL gate on an authorized Docker Desktop/disposable-PostgreSQL runtime; do not mark a runtime pass here. |
| B07                                                       | Independent review coverage is incomplete.                                                                                           | Fresh Web 31/31, Android 8/8 + full static audit, and migration 21/21 source reviews are green at `ed53fc5`, but Caveman reports no separate reviewer/subagent integration; self-review is not independent. | P03.2, P04.2, P05.5, P11.4                                                                                                                                                                      |

## P06.1 source trace completed in this continuation

| Path / current functionConfirmed behaviorConsequence for implementation |                                                                                                                                                        |                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Catalog `internal/store/store.go`: `PublishChapter`                     | Locks the chapter, updates visibility, and emits events when transitioning from unpublished.                                                           | Retain transaction/outbox behavior inside the new common command; add revision/receipt evidence.                                                                                                                                                          |
| Scraper `app/publication.py`: `publish_chapter_record`                  | Directly creates/replaces chapters/pages and emits publication events. Called by `drafts.py`, `batch_queue.py`, `series_drafts.py`.                    | Consolidated within Scraper but still a separate production writer; replace with Catalog command consumption.                                                                                                                                             |
| Scraper `app/series_drafts.py`: production-series creation              | Converts/uploads a cover and directly inserts series, genres/tags and junction rows.                                                                   | Chapter-only refactoring would be incomplete; route series/taxonomy/cover work through Media/Catalog ownership too.                                                                                                                                       |
| Media `app/services/chapter_ingestion.py`: `_ingest_chapter_source`     | Uploads pages, inserts `Chapter`/`Page` through ORM, updates series, emits events and completes a Media operation.                                     | SQL-text searches alone miss this writer. Preserve bounded conversion, retry-stable objects and ambiguous-outcome preservation while moving the production commit.                                                                                        |
| Media `app/media_operations.py`                                         | Durable queue/processing/heartbeat/completion evidence already exists.                                                                                 | Extend the existing mechanism for transformation evidence; do not add a second Media queue.                                                                                                                                                               |
| Catalog `internal/httpapi/api.go`: `Router`                             | Registers existing public/admin Catalog API and canary routes; no `/internal/v1/catalog` command interface.                                            | Private command authentication/routing and caller wiring are real remaining work.                                                                                                                                                                         |
| Catalog deletion + Media `app/lifecycle_worker.py`                      | Catalog captures exact references and enqueues cleanup; worker filters current references. Worker also accepts legacy storage-prefix cleanup payloads. | Preserve the useful exact-reference path; add generation/race qualification and inspect legacy producers. Current Catalog deletion sends an empty production `storage_prefixes` list, so this is not evidence it currently deletes a whole series prefix. |

These are source findings, not an executed publish/cancel race. The actual Media source directory is `services/image_service`, correcting the earlier design's `services/media_service` locator. The task is advanced to P06.2; no new runtime implementation is claimed by this planning checkpoint.

## Acceptance-gate ledger

No combined release gate below is closed yet. The evidence column names available supporting work; final closure requires the full acceptance result in the spec.

| GateResponsible tasksCurrent evidence / next required proof |                   |                                                                                                                                                                                                                                                          |
| ----------------------------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BASE-01                                                     | P01               | **Verified in sequential review `fda3b03`:** Milestone-1 ZIP digest rechecked; 729/729 package manifest entries verified; archive identities recorded; nine capability surfaces mapped to source/API/tests; current and retired table dispositions inventoried; focused P01 audit + ownership static + 133-route audit passed. |
| OWN-01                                                      | P01, P09          | Design registry exists; full table inventory and actual forbidden-write tests remain.                                                                                                                                                                    |
| API-01                                                      | P06, P08, P09     | Source route checks exist; integrated registered-route/gateway/client denial tests remain.                                                                                                                                                               |
| READ-01                                                     | P02, P05          | Sequential P02 source audit confirms ordered command/evidence boundary; actual PostgreSQL/API run remains blocked.                                                                                                                                       |
| READ-02                                                     | P02               | Sequential P02 audit confirms resume/ledger/outbox are in one PostgreSQL transaction; immediate runtime cross-screen canonical-read proof remains blocked.                                                                                               |
| READ-03                                                     | P02–P04           | Source and Web behavioral cases exist; actual concurrent API/client cases remain.                                                                                                                                                                        |
| READ-04                                                     | P02–P04           | Completion-evidence code exists; actual Web/Android rendering cases remain.                                                                                                                                                                              |
| LOCAL-01                                                    | P03, P04          | Web behavioral evidence; actual UI refresh/Android execution remain.                                                                                                                                                                                     |
| LOCAL-02                                                    | P03, P04          | Web journal cases pass; browser multi-tab and Android lifecycle tests remain.                                                                                                                                                                            |
| LOCAL-03                                                    | P03, P04, P11     | Coalescing/bounds implemented; real lifecycle/load/other-device convergence remains.                                                                                                                                                                     |
| LIB-01                                                      | P02–P04           | One envelope/query implemented; real SQL scopes/states/sorts and UI pagination remain.                                                                                                                                                                   |
| UI-01                                                       | P03, P04, P10     | Some reading cases covered; full screen/failure matrix remains.                                                                                                                                                                                          |
| AND-01                                                      | P04               | Source audit and 11 unexecuted tests; real build/upgrade/device evidence blocked.                                                                                                                                                                        |
| PUB-01                                                      | P06               | P06.2 contract plus P06.3 durable Media evidence/Catalog receipt-transaction/authority source are implemented and source-qualified; the real PostgreSQL P06.3 gate is still blocked. Private transport auth, caller cutover and proof that Scraper/Media no longer write production tables remain. |
| PUB-02                                                      | P06, P07          | Source tests now cover durable receipt replay/conflict, target revision, actor/source/generation/cancel fencing, concurrent create/replacement and response loss; P07.4 adds exact generation-bound cleanup intent plus delayed-job ownership fencing. Real PostgreSQL and runtime worker cancellation/redelivery races remain unexecuted. |
| ING-01                                                      | P07               | Common header/fencing and real restart/cancel/staging cases remain.                                                                                                                                                                                      |
| DEL-01                                                      | P06, P07          | P07.4 source-qualified at `394e440`: Catalog records exact generation-bound primary/responsive/cover cleanup intent transactionally; Lifecycle is the sole production deleter, rechecks live ownership, and quarantines broad-prefix jobs. Runtime retry/restart/worker-loss/KEDA-redelivery proof remains P07.5/P11. |
| MIG-01                                                      | P05, P09          | Six shell cases pass, ten PostgreSQL cases unexecuted; all versions/grants remain.                                                                                                                                                                       |
| MIG-02                                                      | P01, P05, P07–P09 | Reading/backup retirement source exists; final legacy reconciliation and absence tests remain.                                                                                                                                                           |
| PATH-01                                                     | P08, P11          | Root/operator fixtures pass; real Linux/Windows Docker bind/restart cases remain.                                                                                                                                                                        |
| DBP-01                                                      | P08               | Capture/catalog source implemented; real artifacts and retention pins remain.                                                                                                                                                                            |
| DBP-02                                                      | P08, P09          | P08.3 private download/security source is qualified at `c5e6866`; local catalog/inventory fixtures pass. Real host/container/browser download and credential-delivery runtime cases remain.                                                                 |
| DBP-03                                                      | P05, P08, P09     | P08.7 source-prepares logical/snapshot drill validation and read-only NAS/media orchestration at `8f01117`; actual PostgreSQL/Docker rehearsal remains blocked and is not claimed passed.                                                                                                             |
| DBP-04                                                      | P08, P09, P11     | Full fencing/journal/interruption/generation rehearsal remains.                                                                                                                                                                                          |
| PERF-01                                                     | P02–P04, P11      | P11.3 dependency-light/source evidence at `a88e275` covers bounded resource/queue/cache guards plus reading/publication concurrency source suites. Real PostgreSQL query plans, live concurrent service behavior, spike/soak budgets, KEDA/HPA and multi-replica cache measurements remain BLOCKED. |
| REL-01                                                      | P11, P12          | Milestone source checks recorded; full validator/build/runtime qualification blocked.                                                                                                                                                                    |

## Evidence and delivery history

| Source checkpointImplemented changeRecorded verification (scope matters) |                                                                                                     |                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `7d6b74c`                                                                | Preserved r5 baseline.                                                                              | Archive provenance recorded in spec.                                                                                                                                                                                                                                                                                                                                     |
| `7b229ab`–`e94f958`                                                      | Recovery root, mandatory safety bundle, local catalog and one protection owner.                     | Focused source/fixture results in detailed plans; actual restore remains open.                                                                                                                                                                                                                                                                                           |
| `16869c2`, `8ae8011`                                                     | Reading transaction, ordered commands and unified projections.                                      | Backend scoped source re-review passed; runtime API/SQL blocked.                                                                                                                                                                                                                                                                                                         |
| `adb5c4e`, `0bb937e`                                                     | Web journal and account/intent fixes.                                                               | 31 Node behavioral tests passed; independent scoped re-review remains open.                                                                                                                                                                                                                                                                                              |
| `de7e3ff`                                                                | Android journal, Library and origin consolidation.                                                  | Source audit passed; 11 Kotlin cases written, not run.                                                                                                                                                                                                                                                                                                                   |
| `842a2c2`                                                                | Migration executor and pre-drop reading preservation.                                               | Six shell cases + five pre-upgrade fixtures passed; ten PostgreSQL cases not run.                                                                                                                                                                                                                                                                                        |
| `bd7b358`, `9a24150`                                                     | Recovery operator/retention alignment and startup correction.                                       | Eight operator fixtures; 14 startup source/fixture/policy checks passed.                                                                                                                                                                                                                                                                                                 |
| 2026-09-14 tracking checkpoint                                           | Central plan, source ownership trace and blocker/gate ledger.                                       | Documentation/path/gate consistency check only; no new runtime behavior.                                                                                                                                                                                                                                                                                                 |
| `651ffe9`                                                               | Sequential review reference import: preserved recovered `17c28ac` P06.2 artifacts under `reference/imports/` without changing application paths. | All 13 reconstructed P06.2 files matched patch blob IDs; disposable overlay reproduced Python compilation, 28/28 focused tests and 8/8 JSON parse checks. Reference only until P06. |
| `fda3b03`                                                               | P01 sequential baseline/capability/table audit. | Fresh ZIP SHA-256 matched recorded Milestone-1 digest; `CHECKSUMS.sha256` 729/729; P01 audit 4/4; ownership static PASS; API route audit PASS with 133 classified routes. `SOURCE_SHA256SUMS.txt` recorded as stale historical manifest (582 match, 85 changed, 4 missing), not current package evidence. |
| `8ea00ff`                                                               | P02 sequential Progress/reading source requalification. | 7/7 focused P02 source audits passed; four Progress Go files verified format-only after gofmt; 31/31 Web behavior cases reproduced with Node 22 type stripping. Go tests blocked by Go 1.23 vs required 1.25; API/SQL tests blocked by absent PostgreSQL/Docker and missing `psycopg`. |
| `15ee796`                                                               | P03 sequential Web reading source requalification. | 31/31 focused production repository cases pass via the corrected TypeScript-loading wrapper; direct module imports now expose loader errors instead of masking them; API ownership static and browser-spec syntax checks pass. Frontend build/typecheck, dedicated P03 Playwright scenarios and independent review remain open. |
| `7bc7a7f`                                                                | Catalog publication contract implementation: Python validator, schemas, fixtures and focused tests. | Historical red contract run recorded; fresh focused suite and contract checks continued in the next checkpoint.                                                                                                                                                                                                                                                          |
| `17c28ac65f27314af65cc555dcefc6d62c82913b`                               | Corrected primary/responsive schema path roles after independent review.                            | 2026-09-15: 28/28 focused Python tests; `py_compile`; four schemas/four fixtures parsed; independent Node hashes, 34 local references, path roles, and git diff/show checks passed. Full JSON Schema execution blocked by unavailable `jsonschema`/Ajv; runtime tool probe also blocked Go/gofmt, psql, Docker, Gradle/Kotlin, pytest, frontend and Social dependencies. |
| `5c36831`                                                                | P06.3 durable Catalog publication boundary.                                                | Catalog receipt/revision transaction, durable Media evidence, Go/Python contract parity and PostgreSQL race/replay fixtures added; runtime DB execution remained open. |
| `6ea7294`                                                                | P06.3 prerequisite ingestion authority fence.                                              | Migration 055 plus actor/source/cancel/generation checks and concurrent-create coverage; source checks passed, real PostgreSQL gate remained open. |
| `6bdf2fa`                                                                | P06.3 Media evidence DB sealing.                                                           | Forward migration 056 + 2/2 immutability source checks; real PostgreSQL mutation check is included in the guarded P06.3 suite but remains blocked by unavailable runtime/toolchain. |
| `8a1a1d0`                                                                | P06.3 guarded runtime-suite selector completion.                                           | Guarded regex runs all `TestCommitPublication*` cases plus `TestMediaCompletionEvidenceIsDatabaseImmutable`; real execution remained blocked. |
| `b2fb861`                                                                | P06.3 disposable Docker runtime gate foundation.                                           | Added explicit Docker-mode DB isolation, pinned PostgreSQL 16.10, tmpfs storage and teardown. |
| `b1c156e`                                                                | P06.3 Docker-supplied runtime gate foundation.                                             | Docker mode supplies PostgreSQL 16.10 and project-standard Go 1.25 in an isolated network, applies real migrations, runs the focused DB suite and guarantees teardown. Later audit found Catalog dependency preparation still needed a writable module tree. |
| `ceb576a`                                                                | P06.3 read-only Media evidence consumption.                                             | Removed `FOR UPDATE` from the sealed Media evidence view read; focused boundary suite is 6/6 and full P06.3 source suite is 53/53. This preserves future SELECT-only Catalog evidence grants. |
| `3425145`                                                                | P06.3 least-privilege authority fencing.                                                | Catalog no longer needs row-lock/UPDATE privilege on Auth, Media or Scraper-owned authority reads; new commits use operation advisory fence seed `485063`. Full focused P06.3 source suite remains 53/53. |
| `d89eb6a`                                                                | Workspace-local Ripwire agent tooling activation.                                      | Ripwire 0.6.1 built offline from the uploaded source archive; wrapper regression 2/2, doctor 8/8, 16 MReader-relevant skills activated locally. |
| `2a9ff5c`                                                                | P06.3 receipt-replay authorization correction.                                          | Durable receipt replay now rechecks the actor's current `users.is_active` + `role='admin'` authorization before returning, while later ingestion-state fences remain bypassed after a proven commit. P06.3 focused source suite 53/53, migration runner 6/6, dependency-free Go contract tests 3/3; Ripwire quality gate reports 0 gating regressions. Real PostgreSQL execution remains blocked by absent Docker in this sandbox. |
| `2dbc64d`                                                                | P06.3 Docker gate writable-module repair.                                                | Gate harness 7/7; keeps the repo bind mount read-only, copies Catalog into writable container scratch, pins the provided Go 1.25 toolchain locally, runs `go mod tidy && go mod verify`, then executes the exact P06.3 DB tests. Docker/image/module availability is still required; the sandbox has no Docker daemon. |
| `ffc166f`                                                                | P06.3 qualification toolchain digest pin.                                               | Pins the Go 1.25/Alpine 3.22 qualification image to the official multi-platform digest; gate harness remains green. |
| `ad0aa0a`                                                                | P06.3 revision-scoped publication event identity.                                       | Catalog emits `chapter.published` v2 with committed `chapter_revision`; Notification Worker accepts v1/v2 and dedupes v2 by chapter+revision. Source/Go event tests pass; real DB confirmation remains open. |
| `78b5cf8`                                                                | P06.3 real Notification revision-dedupe DB evidence.                                    | Adds `TestChapterPublishedV2DedupeIsPublicationRevisionScoped`; focused source suite 60/60, migration 6/6, Catalog Go 3/3, Notification event Go 2/2, gate harness 8/8, Ripwire gating=0. Real Docker/PostgreSQL execution remains blocked here. |
| `0d60bcc` continuation reattempt                                          | Newest persistent continuation recovered and P06.3 runtime gate re-attempted without source mutation. | Bundle SHA-256/internal checks passed; 9 sequential + 4 reference + 2 reverse refs and the paused P06.4 stash were restored; Ripwire doctor 8/8. Exact combined gate exited 2 because Docker is absent. Fresh runnable checks reproduced Python 60/60, migration 6/6, Catalog Go 3/3, Notification Go 2/2, clean formatting/compile/diff checks and Ripwire `gating=0`. Runtime PostgreSQL assertions remain unexecuted. |
| `54ec3fd`                                                                | P06.4 manual chapter publication cutover.                                  | Manual ZIP/CBZ/PDF Media jobs retain actor/operation identity, seal evidence, reconcile response loss, and invoke Catalog via the private publication command route; Media no longer writes chapter/page metadata/events. |
| `b7af7fe`                                                                | P06.4 existing-series Scraper publication cutover.                         | Existing-series drafts freeze private staging, establish Scraper ingestion authority, send raw staged pages to Media for the sole final transform, reconcile Catalog receipts, and only then mark published/clean staging. 34/34 affected source regressions + ownership/route audits passed; frontend build blocked by absent node_modules. |
| `b709d03` (recovery; maps historical `ec273f9`)                       | Reconstructed P06.4 batch publication cutover after sandbox loss.          | Batch private staging is streamed into a spooled raw archive; retained actor/operation identity is sent to Media; Catalog receipt is authoritative; Scraper finalizes only after receipt. Fresh recovery gate: 78/78 focused publication tests + 18/18 runnable Scraper tests + ownership/WebP/134-route/compile/diff + Ripwire `gating=0`. |
| `8cdfdf4` (recovery; maps historical `5466101`)                       | Reconstructed P06.4 new-series chapter publication after sandbox loss.     | New-series chapter publication now uses canonical ingestion authority → retained-actor Media → Catalog receipt; legacy Scraper publisher/transform/event modules are removed. Fresh gate: 63/63 focused publication tests + 4/4 inventory + 18/18 runnable Scraper + ownership/WebP/RC4.84/134-route/direct-writer/compile/diff + Ripwire `gating=0`, preexisting-worse=0. |
| `8ecc4c4` (recovery; maps historical `631ddbf`)                       | Reconstructed P06.4 series/taxonomy/cover ownership after sandbox loss.    | Scraper delegates series/taxonomy to Catalog and cover to Media; Media keeps transform/evidence plus media lifecycle events; Catalog alone owns canonical series/taxonomy/cover mutation and Catalog-domain events. Fresh gate: 88/88 focused publication/ownership + 4/4 inventory + 18/18 runnable Scraper + ownership/WebP/RC4.84/136-route/direct-writer/event/compile/gofmt/diff + Ripwire `gating=0`. |
| `0f1fadb` (recovery; maps historical `4325575`)                       | Reconstructed P09.1 scoped-secret prerequisite for P06.5.                  | Exact workload allowlists/renderer ported from surviving `343eda6`; 8/8 secret-scope tests + five hybrid/static gates + shell/diff + broad-secret/future-private-credential scans pass; Ripwire `gating=0`. |
| `581c310` (recovery; maps historical `c82650a`)                       | Reconstructed P06.5 private workload authentication after sandbox loss.    | Internal Catalog/Media transport now requires exact scoped workload credentials plus retained active-admin authorization; both gateways deny `/internal`; public Catalog publish cannot bypass Media evidence; hybrid bootstrap generates only missing credentials. Fresh gate: 103/103 publication/security/authority + 18/18 runnable Scraper + ownership/WebP/136-route/direct-writer/compile/syntax/diff + credential preservation probe + Ripwire `gating=0`. `selectolax` and local Go >=1.25 runtime checks remain blocked, not passed. |
| `d79e340` (recovery; maps historical `2954469`)                       | Reconstructed P06.6 publication-event finalization after sandbox loss.     | `CommitPublication` is the sole production `chapter.published` writer; metadata `UpdateChapter` rejects draft→published without Media evidence; notification dedupe remains publication-revision scoped. RED reproduced against clean `53c1dd6`; fresh gate: 98/98 publication/security/authority + 18/18 runnable Scraper + ownership/WebP/136-route/sole-event-writer/compile/gofmt/diff + Ripwire `gating=0`. Generic test-gate remains conservative exit 4; `selectolax` and Go >=1.25 remain blocked. |

Latest delivered source-test/deployment package: `mreader-rc485-p12.2-source-test-3020fc3.zip`, exact committed tree `3020fc30bbbf1bd8fd7e89ce31145847469710c9`, 942 verified package checksum entries. Fresh Windows/Git-Bash installs now use the dedicated `C:/mreader/database-protection` host mount when no explicit root is configured, and invalid stale process-level recovery-root exports no longer defeat that blank saved-root bootstrap path. Earlier P12.2 packages remain preserved as historical evidence.

ZIP SHA-256: `8df2a7b6ece941aaad4a95556f45d5036183cd1ad15efef646eeca49e273e6d8`.

P12.2 is a full source-test/deployment checkpoint, not a compiled APK or a qualified final release. Its committed tree, per-file checksums, deterministic rebuild and ZIP integrity were verified. The earlier `mreader-rc485-milestone-1-source-test.zip` (`958e1580...`) and original uploaded archives remain preserved and unchanged.

**Continuation handoff:** stay on `sequential/p06.4-caller-cutover`. P11.4 source/release-integration repairs are committed at `ed53fc5`; available Web/Android/migration/P09/P10/current-release checks are green, but genuine independent review remains BLOCKED because no separate reviewer/subagent integration is available. P11.1 build/runtime, P11.2 destructive topology and P11.3 real performance/runtime gates remain BLOCKED for release acceptance; their sequencing waiver is not a pass. Resume from `docs/continuation/RC485-NEXT-CHAT-P11.4.md` and `docs/qualification/2026-09-17-rc485-p11.4-release-integration-review.md`. Preserve all prior ownership/security/truthfulness/race fences, existing resource limits and blocker truthfulness. The forensic stash remains `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` and must not be applied/popped.

### 2026-09-17 P12.2 real-host Git Bash pre-upgrade capture repair

- Source `c4bf03f1238f47faafaecff59705a9e44ced717d` fixes MSYS rewriting of Linux container `/tmp/preupgrade-*` arguments at Docker capture/copy/cleanup boundaries.
- Focused TDD RED reproduced missing path-conversion guard; GREEN: local pre-upgrade backup 6/6 plus adjacent ordering/MSYS/volume regressions.
- Replacement deployment artifact: `mreader-rc485-p12.2-source-test-c4bf03f.zip` (`7fd19bd2eb14be605139ed70e424d4b44f921cb3338da7e095a649fc138bb21f`).
- P11 runtime and independent-review blockers remain unchanged.

### 2026-09-17 initialization pre-upgrade backup bypass

Current P12.2 source checkpoint: `2b199295cc308fca764c7c2ce268e0a5d84fd8fb`. For explicit initialization/testing only, `MREADER_SKIP_PREUPGRADE_BACKUP=true` skips the mandatory pre-upgrade PostgreSQL bundle; safe default remains `false`. Current deployment ZIP: `mreader-rc485-p12.2-source-test-2b19929.zip`, SHA-256 `f4613bd0aab8448a0d2894aa46a95e7407a58cc96f8c9a214a1070297642708e`. Verification: bypass contract PASS, original ordering PASS, local pre-upgrade backup suite 6/6 PASS, current-release source/static validator PASS.


### 2026-09-17 P12.2 pre-upgrade host-jq runtime fallback

- Source `c9dde2b278cda2d67e3ad672d3935fdd06e7a045`: mandatory pre-upgrade recovery capture remains fail-closed, but missing host `jq` now falls back to the canonical recovery-store validator inside the pinned `backup_agent` image.
- Fresh TDD: exact no-host-jq failure RED, then local pre-upgrade backup **7/7 PASS**; ordering, initialization bypass, MSYS path, PostgreSQL volume and ownership contracts PASS.
- Replacement deployment artifact: `mreader-rc485-p12.2-source-test-c9dde2b.zip`; SHA-256 `2c3a04da5f8d17a8e985b19a646de970ef5e0250a73b10c1d11670911533a28b`; 944 committed files exact to Git, 947 package checksum entries, deterministic rebuild byte-identical.
- This repair does not close P11.1-P11.4 release-acceptance blockers.

### 2026-09-17 P12.2 Windows Compose-path repair

- Source `8b1415a8c330816e459ad5e7c29b73336961a105`: the backup-agent recovery-store fallback now preconverts Windows host `.env`/Compose paths before applying `MSYS_NO_PATHCONV=1`, while keeping Linux container paths unchanged.
- Regression coverage includes the real `C:\c\Users\...` failure class via a mixed MINGW host/container-path contract; local pre-upgrade suite is 8/8 PASS.
- Replacement deployment artifact: `mreader-rc485-p12.2-source-test-8b1415a.zip`; SHA-256 `101f879451a6b455516fce679ecb3b35e9033a4c19366ac0d87749d2a09be51b`; 945 committed files exact to Git, 948 package checksum entries, deterministic rebuild byte-identical.

### 2026-09-17 P12.2 backup-agent Alpine package constraint repair

Real-host Docker build exposed stale exact Alpine package revision pins in the backup-agent image. Current source `ac7bccc8cf5043584b9d7260055d38463bae448f` retains the digest-pinned base but uses minimum-compatible package constraints so v3.22 stable revision updates do not make `apk add` unsatisfiable. Current deployment ZIP: `mreader-rc485-p12.2-source-test-ac7bccc.zip`, SHA-256 `60323704899eae4d2bb5ce7f3497f76ba2855490d3857cf1ff5b45c8d2b994b7`. P11 blockers remain unchanged.

### 2026-09-17 P12.2 BusyBox recovery portability repair

Real-host backup-agent execution progressed past image build and BusyBox `find`, then exposed a checksum-format boundary: Git Bash/GNU may emit `HASH *filename` while the Alpine validator expected only text-mode names and GNU-only verification flags. Current source `9793fed4a7b5f9e47a5b3950826e6bfae1aa8e4c` normalizes the optional binary marker before fail-closed allowlist/duplicate validation and uses portable `sha256sum -c`. Current deployment ZIP: `mreader-rc485-p12.2-source-test-9793fed.zip`, SHA-256 `b41ea719b95f54f773fa56988bcc41388e1075a5e378af2db7e67d574aa540fa`. P11 blockers remain unchanged.


### 2026-09-17 P12.2 initial restore-generation seed

Real-host bootstrap progressed beyond the Windows recovery portability sequence and then stopped at P09.4 because a fresh database had no `restore-control.json` and migration 060 leaves the restore mirror at empty fingerprint / generation 0. Current source `4fbd847af7ae6f7a2f0bd8704ae34bc272fc8f4f` adds a canonical initialization step after migration + role reconciliation: `backup_agent initialize-restore-state` creates/reads host generation 1 and seeds the database singleton only from its migration-default state; exact matches are idempotent and all other states fail closed. Deployment ZIP: `mreader-rc485-p12.2-source-test-4fbd847.zip`, SHA-256 `8358d123386461c60ed3e0287deb327c294737b692fd0439867fa695e89da557`; 950/950 committed files exact, 953/953 package checksums, deterministic rebuild byte-identical. Focused P08.8/P09.4 tests 39/39 PASS; current-release source/static validator PASS. P11 acceptance blockers remain unchanged.

### 2026-09-17 P12.2 cross-platform boundary audit closure

Current deployment-test authority is `mreader-rc485-p12.2-source-test-a7d7a40.zip` from exact source `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6`, SHA-256 `907c7bc1f1bf88c4ae94786584d8f31fc99ec86dfa3074f0dc6ce4ca9b62a007`. The broader audit repaired confirmed Git-Bash/MSYS Docker path variants, host-tool assumptions in restore/readiness paths, catalog recovery-store host coupling, and systemic exact Alpine `-rN` package revision pins. Final evidence: 49/49 combined P08.6/P08.7/P08.8/P09.4, 8/8 local pre-upgrade, MSYS mixed/container path, initialization/pre-upgrade ordering, backup-agent/dependency/Dockerfile static gates and current-release source/static validator PASS. Package 955/955 Git files exact, 958/958 checksums, deterministic rebuild byte-identical. Real Docker/Kubernetes and independent-review P11 gates remain BLOCKED; this audit does not advance P12.3.

### 2026-09-17 P03.2 browser acceptance source coverage

- Source `d7fd2948f64920a8851780e64d94de6a795c6c7a` adds five real-browser acceptance scenarios and a validator-enforced source contract.
- Fresh evidence: Web reading 31/31, browser acceptance source contract PASS, browser-spec syntax PASS, current-release source/static validator PASS.
- Real Playwright execution and independent scoped review remain BLOCKED/open; this does not close P03.2 or P11.4.

P03.2 package authority: `mreader-rc485-p12.2-source-test-d7fd294.zip`, exact source `d7fd2948f64920a8851780e64d94de6a795c6c7a`, SHA-256 `12e37a434d9f2cd2e824d4ebee174563da57ba23b091c18b0df9c4ae25e22e51`; 957/957 committed files exact, 959/959 package checksum entries, deterministic rebuild byte-identical. Real Playwright execution and independent review remain open.

### 2026-09-17 P12.2 Windows drive-form Python host-input repair

- Source `b80c030327e16a9e05dfd7b979a5b5ee668ce2de` resolves Windows drive-form Python inputs with `cygpath -u` before Docker bind-mount eligibility checks.
- TDD corrected the platform-dependent `Z:/...` fixture: RED on pre-fix behavior, GREEN after runtime repair.
- Verification: no-host-Python, Python-runtime packaging, MSYS paths, P09.4/readiness/secret scopes, restore-generation/order and Windows path-budget gates PASS.
- Replacement deployment artifact: `mreader-rc485-p12.2-source-test-b80c030.zip`; SHA-256 `afe1cd9030ee64602a6840714af54bff1e083f204e15bca1499d1324d1e26ebc`; 960 exact Git files, 967 verified package entries, deterministic rebuild byte-identical.

### 2026-09-17 P12.2 real-host application CrashLoopBackOff repair

- [x] Reproduce source-level startup-contract mismatch for Auth/Image async SQLAlchemy DSN handling.
- [x] Reproduce missing `reading_state_v1` privilege in `progress_runtime`.
- [x] Add RED tests before production changes; verify GREEN after fixes.
- [x] Correct P09.3 schema-object audit so view grants are validated as views.
- [x] Run P09.3/P09.4 + Windows/no-host-Python/MSYS regressions.
- [x] Run full current-release validator (exit 0).
- [x] Build deterministic source-test ZIP and independently reopen/check source and package hashes.
- [ ] Real Windows/Docker Desktop rerun: verify `auth-service`, `auth-admin`, `image-service`, `progress-go` become `1/1 Running` and inspect fresh logs if any remain unhealthy.

Source: `4cd61f40019f84c90b491af52cdc69155c6efcce`. Package: `mreader-rc485-p12.2-source-test-4cd61f4.zip`, SHA-256 `93fa31dfca130aa772923ad7d1b06a27861037367cfda32eb426cf98c0cdd8e8`.

### 2026-09-17 real-host image-service import-cycle repair

- [x] Capture real-host `kubectl logs --previous` for the crash-looping image-service pod.
- [x] Trace import dependency to `jobs.py -> upload.py -> jobs.py` and identify the latent missing `IMAGE_MIME_TYPES` symbol from the same P07.3 change.
- [x] Add RED startup-contract regression.
- [x] Move shared media validation constants to neutral `app.media_validation`; keep durable thumbnail job ownership in `jobs.py`.
- [x] Run GREEN focused suite (27/27), compileall, API ownership and consolidation gates.
- [x] Run full current-release validator to exit 0.
- [x] Build/reopen deterministic `d055830` package with 970/970 package checksums, 964/964 exact Git files, and executable modes preserved.
- [ ] Real-host gate: redeploy `d055830` package and observe image-service `1/1 Running`; collect previous logs if not.

### 2026-09-18 dedicated containerized diagnostics module

- [x] Add one-command `./diagnose-mreader.sh` and `./test-mreader.sh --diagnose` interfaces.
- [x] Run diagnostics tests inside pinned `mreader/diagnostics:1.3.0-rc4.84` while keeping Windows/Docker Desktop evidence capture host-side and read-only.
- [x] Preserve evidence after failed/timed-out stages and produce `REPORT.md`, `REPORT.json`, `issues.json`, `endpoint-results.tsv`, `stages.tsv` and `REPORT_BUNDLE.zip`.
- [x] Add secret redaction, Kubernetes/Docker evidence capture and PostgreSQL/RabbitMQ/Valkey/gateway/SeaweedFS snapshots.
- [x] Verify 16/16 diagnostics units, diagnostics/static/MSYS guards, 139/139 source-route coverage and full current-release validator (exit 0).
- [x] Build/reopen deterministic source package: `mreader-rc485-p12.2-source-test-7f52ea5.zip`, SHA-256 `01f509870eab245ed6a2eb3054729d0d2810f93bc3cbcda6f0f544bcfc15c5a7`; 980/980 Git bytes + modes exact and 986/986 package checksums PASS.
- [ ] Run the diagnostics container against the real Windows/Docker Desktop deployment and use its first report bundle to drive remaining runtime fixes.

Diagnostics source: `7f52ea56269ee8c7a0103a432ec0b0691991ed25`. P11 runtime/independent-review blockers remain open; this module is an observability/test aid, not a waiver or release acceptance.

## 2026-09-18 P12.3 actor-journey diagnostics completion

Source `571190a4d5553ecaa57b92ef7df1c8255dafe1e5` completes the expanded diagnostics implementation. The next action is real-host execution of `./diagnose-mreader.sh` with optional external fixtures, followed by evidence-driven repair of genuine application findings. Do not interpret the earlier report's broad OOM/probe/RabbitMQ findings as authoritative because those classifier defects are fixed in this source.

## 2026-09-18 P12.4 Graphify development-reference completion

Source `887e0ec99e806f45416e84df13bb44960b6480f0` adds maintained Graphify/Ripwire development-reference tooling and packages a checkpoint-matched project graph for Drushti. Verification is green: 3/3 reference tests, static gate, 139/139 API routes, no Graphify/Ripwire evidence failures, Ripwire gating=0, current-release validator exit 0, deterministic package SHA-256 `50706c81f353cf225f0afb01fc9cc1e94a5e03056c043cbed2c2a88335e176c1`, 1,042 package checksum entries and 1,000 exact Git bytes+modes. The next debugging workflow should begin with `Drushti continue .` and use Graphify/Ripwire to localize the owning service/files/tests before edits. This is tooling/diagnostic support only; the real-host actor diagnostics and P11 release blockers remain open.

### 2026-09-18 P12.5 live-diagnostic repair closure

- [x] Separate diagnostic harness defects from genuine MReader runtime failures using the real-host report bundle.
- [x] Repair API actor/media collection helpers and pinned test dependency.
- [x] Repair Catalog taxonomy write grants and Social Smart Library view access; preserve upgrade role reconciliation.
- [x] Align realtime/admin browser acceptance with current session/privacy contracts.
- [x] Run 6/6 P12.5, 21/21 diagnostics, 3/3 development-reference, 139/139 route and full current-release validator gates.
- [x] Build/reopen deterministic `f6a2c14` package with 1,045 package checksums and 1,002 exact Git files/modes.
- [ ] Real-host rerun: `./hybrid-up.sh` then `./diagnose-mreader.sh`; analyze the resulting actor/browser report bundle.
