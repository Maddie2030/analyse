# MReader RC4.85 — Detailed Continuation Manifest

**Purpose:** make a new ChatGPT/Codex/agent session able to locate the correct repo, tools, plans, references, branches, tests, blockers, and paused work without relying on conversation memory.

**Primary authority:** `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`.

**Current task:** **P11.4 source/release-integration review is source-qualified at `ed53fc5`, but genuine independent review remains BLOCKED.** P12.2 has now produced a separately verified source-test/deployment package from exact clean tree `8f7c169` so the blocked runtime gates can be executed on the real MReader host. This packaging does not waive P11.1-P11.4 acceptance debt. Evidence: `docs/qualification/2026-09-17-rc485-p11.4-release-integration-review.md`, its TSV matrix, and `docs/qualification/2026-09-17-rc485-p12.2-source-test-package.md`. The forensic stash remains untouched.

## 1. Canonical workspace map

| Item | Path / ref | Authority | Notes |
| --- | --- | --- | --- |
| Workspace root | `/mnt/data/mreader-rc485-working` | Active recovery workspace authority | Restored from the persistent continuation bundle after sandbox loss. |
| Cross-chat recovery package | `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip` | Persistent recovery authority | Use when the active `/mnt/data` checkout is missing; verify the companion `.sha256` and embedded branch HEAD before editing. |
| Latest source-test/deployment package | `/MReader/RC4.85/mreader-rc485-p12.2-source-test-4fbd847.zip` | P12.2 test/deployment artifact | Exact committed tree `4fbd847`; SHA-256 `8358d123386461c60ed3e0287deb327c294737b692fd0439867fa695e89da557`. Fresh initialization now seeds the restore generation before P09.4. Not a final qualified release. |
| Canonical implementation repo | `/mnt/data/mreader-rc485-working` | **Only active implementation authority in this recovery** | All reconstructed code changes/tests/commits originate here until a later handoff explicitly changes the path. |
| Canonical tracker | `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md` | **Primary task/status authority** | Read first in every continuation. |
| This manifest | `docs/continuation/RC485-CONTINUATION-MANIFEST.md` | Workspace/navigation authority | Detailed map of repos, tools, files, branches, commands, and recovery. |
| Approved design specification | historical pre-sandbox path (not mounted) | Provenance only in this recovered sandbox | Use checked-in tracker/continuation/qualification docs and preserved Git refs for continuation unless the original artifact is separately restored. |
| Original copied action plan | historical pre-sandbox path (not mounted) | Historical/reference only | Canonical checked-in tracker is authoritative. |
| Baseline uploaded source ZIP | `/mnt/data/mreader-rc485-milestone-1-source-test(3).zip` | Original source artifact | Source from which the sequential repo was created. Do not overwrite it. |
| Original user tracker upload | `/mnt/data/Pasted markdown.md` | Original tracker artifact | Historical input; canonical tracker is the checked-in repo copy. |
| Original detailed design upload | `/mnt/data/Pasted markdown(1).md` | Original design artifact | Historical input; workspace reference copy is preferred. |
| Reverse P09 merge unit ZIP | `/mnt/data/mreader-rc485-p09.1-reverse-merge-unit.zip` | Reference artifact | Do not use as active source. |
| Preserved 17c28ac cumulative patch | `/mnt/data/reference_import_17c28ac/mreader-rc485-WIP-source-changes.patch` | Reference artifact | Used to reconstruct the validated P06.2 reference subset. Never apply wholesale. |
| Reverse-order repo | historical pre-sandbox path `/mnt/data/mreader_rc485_reverse_work/mreader-rc485-milestone-1` | Read/reference provenance only | Not mounted and no live Git remote is configured in the recovered sandbox; preserved imported reference refs in this repository remain the usable evidence. |

### Authority rule

If two copies disagree, use this order:

1. canonical implementation repo at its recorded sequential branch/HEAD;
2. canonical tracker;
3. approved design/spec reference;
4. qualification evidence under `docs/qualification/`;
5. reference branches/patches/old archives only for selective comparison.

Never replace the current tree with an older archive or reference branch just because it once worked.

## 2. Canonical Git state and branch roles

**Active branch:** `sequential/p06.4-caller-cutover`.

**Recorded continuation source checkpoint before this manifest update:** `289337e`, P09.2 source-qualified ownership/route manifest and same-tree auditor. Earlier post-recovery checkpoints are `8f01117` (P08.7 drill qualification), `f051fc7` (P08.6 restore-source/catalog-only safeguards), `d264486` (P08.5 verified import/inventory/pins/retention), `c8a7c52` (P08.4 canonical facade extraction), `c5e6866` (P08.3 private recovery download), `26d80a1` (P07.5 canonical status/UI convergence) and `394e440` (P07.4 generation-fenced Lifecycle cleanup). Sandbox-loss reconstruction remains complete through `6e42f6b`; always trust live `git rev-parse HEAD` after later documentation commits.

**Paused later work:**

`stash@{0}: On sequential/p06.4-caller-cutover: P06.4 WIP paused for P06.3 completion gate audit`

The stash modifies only:

- `services/image_service/app/media_operations.py`
- `services/image_service/app/routers/jobs.py`
- `services/image_service/app/services/chapter_ingestion.py`

The stash is now a **superseded rollback/forensic backup**. Do not apply/pop it during normal continuation because its useful manual-publication content has been reconstructed into committed P06.4 checkpoints. Keep it until caller cutover is complete.

### Sequential branches

| Branch | Tip at inventory | Meaning |
| --- | --- | --- |
| `sequential-baseline` | `4f142ed` | Untouched imported Milestone-1 sequential baseline. |
| `sequential/p01-baseline-audit` | `fe788e1` | P01 provenance/capability/table inventory checkpoint. |
| `sequential/p02-reading-review` | `c2265c6` | P02 source requalification then tracker advance. |
| `sequential/p03-web-reading-review` | `abc7ff0` | P03 Web reading review checkpoint. |
| `sequential/p04-android-reading-review` | `336a338` | P04 Android reading/origin requalification. |
| `sequential/p05-migration-review` | `c9948b8` | P05 migration quiescence/legacy work reconciliation. |
| `sequential/p06.3-prereq-ingestion-fence` | `6ea7294` | Minimal P07.1 authority header pulled forward solely as P06.3 prerequisite. |
| `sequential/p06.4-caller-cutover` | live; see current recovery handoff | **Current active implementation branch.** P10.2 is durably checkpointed; P11.1-P11.3 runtime acceptance remains blocked. P11.4 available source/release-integration review is source-qualified at `ed53fc5`, while genuine independent review remains blocked. |
| `sequential/p06-catalog-publication-review` | `b40645a` | Preserved P06.3 review/documentation branch; runtime DB gate remains debt, not a pass. |

### Reference branches — never merge wholesale

| Branch/ref | Tip | What it contains | Allowed use |
| --- | --- | --- | --- |
| `reference/p06.2-17c28ac-import` | `651ffe9` | Reconstructed/validated P06.2 publication contract subset from checkpoint `17c28ac...`. | Selective source reference; already promoted through `c57d3dc`. |
| `reference/p09-baseline` | `ac9cf4a` | Imported reverse repo baseline. | Provenance only. |
| `reference/p09.1-scoped-secrets` | `343eda6` | Reverse-order P09.1 workload-scoped secrets implementation. | Re-review/port later when sequential P09 is reached. |
| `reference/p09.2-manifest-wip` | `b444163` | RED ownership/route-manifest test work. | Historical evidence only; P09.2 is now source-qualified on the active branch and this reference must not be merged wholesale. |
| `reverse-reference/milestone1-baseline` | remote tracking | Reverse repo baseline. | Provenance only. |
| `reverse-reference/reverse-p09` | remote tracking | Imported reverse P09 work. | Reference only. |

Detailed branch policy: `docs/qualification/RC485-REFERENCE-BRANCHES.md`.

## 3. Commit chronology that matters for current work

Read `git log --oneline --decorate -35` for live history. Important checkpoints in order:

| Commit | Meaning |
| --- | --- |
| `4f142ed` | sequential baseline import |
| `fda3b03` / `fe788e1` | P01 implementation/evidence |
| `8ea00ff` / `c2265c6` | P02 reading source qualification |
| `15ee796` / `abc7ff0` | P03 Web reading qualification |
| `336a338` | P04 Android/origin qualification |
| `c9948b8` | P05 migration fence + legacy operation reconciliation |
| `c57d3dc` | validated P06.2 publication contract promoted into active source |
| `5c36831` | original P06.3 durable Catalog publication boundary |
| `ad0aa0a` | P06.3 `chapter.published` v2 revision identity + version-safe Notification dedupe |
| `78b5cf8` | P06.3 real Notification/PostgreSQL revision-dedupe qualification case |
| `6ea7294` | ingestion authority header/fence prerequisite |
| `6bdf2fa` | PostgreSQL-level Media completion-evidence sealing |
| `ce2868d`, `8a1a1d0` | guarded P06.3 PostgreSQL runner and evidence-sealing coverage |
| `b2fb861`, `b1c156e`, `2dbc64d`, `ffc166f` | Docker-provisioned P06.3 DB gate, writable Catalog module preparation, and Go image digest pin `sha256:f18a072054848d87a8077455f0ac8a25886f2397f88bfdd222d6fafbb5bba440` |
| `ceb576a`, `3425145` | least-privilege read-only Media/Auth/Ingestion boundary hardening |
| `d89eb6a` | workspace-local Ripwire activation/tooling integration |
| `2a9ff5c` | current-admin authorization recheck on durable receipt replay |
| `ca9df3b` | tracker/qualification reconciliation after replay authorization fix |
| `0d60bcc` | documentation checkpoint reconciling the `78b5cf8` Notification DB qualification |
| `54ec3fd` | P06.4 manual chapter publication cutover through Media evidence → Catalog |
| `b7af7fe` | P06.4 existing-series Scraper publication cutover through the same ownership chain |
| `b709d03` | Recovery reconstruction of historical `ec273f9`: P06.4 batch publication through the same Media → Catalog ownership chain |
| `8cdfdf4` | Recovery reconstruction of historical `5466101`: P06.4 new-series chapters through Media → Catalog; orphan Scraper publisher/transform/event stack removed |
| `8ecc4c4` | Recovery reconstruction of historical `631ddbf`: P06.4 series/taxonomy/cover mutation ownership moved behind Catalog; final non-Catalog production writer/event scan clean |
| `0f1fadb` | Recovery reconstruction of historical `4325575`: P09.1 workload-scoped secret prerequisite ported/requalified from surviving `343eda6` |
| `581c310` | Recovery reconstruction of historical `c82650a`: P06.5 scoped private transport auth/gateway denial |
| `d79e340` | Recovery reconstruction of historical `2954469`: P06.6 sole publication-event writer + revision-scoped notification dedupe |
| `24adb72` | Recovery reconstruction of historical `ae6f4c7`: P07.1 canonical ingestion-operation convergence |
| `f5c34a7` | Recovery reconstruction of historical `cd921e6`: P07.2 lease/cancel/generation fencing |
| `6e42f6b` | Recovery reconstruction of historical `b5ddd8a`: P07.3 fenced Stage/Retry repair + durable cover-job compatibility |
| `394e440` | P07.4 exact generation-bound cleanup ownership: Catalog transactional intent, Lifecycle-only production deletion, live replacement fence, broad-prefix quarantine |
| `26d80a1` | P07.5 canonical parent operation/status convergence plus Catalog deletion cleanup receipts and migration 059 backfill |
| `193357b` | P09.3 Tasks 1–7 restrictive PostgreSQL grants checkpoint: audited role contract, deterministic reconcile, scoped role DSNs, fail-closed service loaders, disposable permission gate and hybrid validation integration; runtime grant execution remains blocked here |
| `67303f6` | P09.3 final source qualification: closes effective-privilege/PUBLIC/future-function and real-login/cross-domain-DML proof gaps; exact-tree qualification is green while the real PostgreSQL permission gate remains BLOCKED (exit 2). |

The current source checkpoint is `67303f6` for P09.3 final source qualification. Task 8 exact-tree qualification and the `32c4383` external all-refs Library durability gate have passed; immutable/rolling packages were independently re-materialized at SHA-256 `257c894549eef3917989454f379c76c416505cdc61b1c0ee41cdc85feebc682c`. The real PostgreSQL permission gate remains BLOCKED (exit 2). This closure commit must now be persisted under the same standing durability rule before P09.4 source edits.

## 4. Superpowers usage contract

Superpowers is the **process/correctness framework**. It governs *how* changes are made.

### Required skills by moment

| Moment | Skill | Rule |
| --- | --- | --- |
| Start/resume work | `using-superpowers` | Check applicable skills before any code action. |
| Execute tracker tasks | `executing-plans` | Treat the tracker as the written plan; follow task order/gates. |
| New behavior / bug fix | `test-driven-development` | RED → verify RED → minimal GREEN → verify GREEN → refactor. |
| Failure/unexpected result | `systematic-debugging` | Root-cause investigation before fixes. |
| Parallel isolated work | `using-git-worktrees` | Use isolation; do not develop on the wrong branch/tree. |
| Before completion/advance | `verification-before-completion` | Fresh evidence required before any completion claim. |
| Major checkpoint | `requesting-code-review` | Review diff/requirements before integrating. |
| Branch finish/merge decision | `finishing-a-development-branch` | Run after verified implementation when actually ready to land. |

### Superpowers + MReader rule

Superpowers never overrides the tracker or approved design. If a skill recommends asking a question but the tracker already provides the answer, use the tracker. Never advance P06.3 solely because source tests pass when the tracker requires a real PostgreSQL gate.

## 5. Ripwire installation and usage

Ripwire is the **repository-context/change-risk framework**. It maps what to read/change/test; it does not replace executable tests.

### Installed tooling

| Item | Path |
| --- | --- |
| Ripwire v0.6.1 binary | `$HOME/.local/bin/ripwire` |
| Ripwire source from user ZIP | historical pre-sandbox copy (not mounted) |
| Ripwire installation record | historical pre-sandbox copy (not mounted) |
| Upstream staged skills | current installed Drushti/Ripwire layer; old workspace copy not mounted |
| Activated MReader skills | current installed Drushti/Ripwire layer |
| Checked-in wrapper | `scripts/diagnostics/ripwire-context.sh` |
| Checked-in workflow rules | `docs/development/RIPWIRE-WORKFLOW.md` |
| Agent entry rules | `AGENTS.md` |

**Source ZIP SHA-256:** `5ae0fb9a8efde50e67cf0849a2170b8c93ba192101860bf9845696a6803b144c`.

**Binary SHA-256:** `78684f8f14840d360b9ab249e70d5e15bbac592809c5bbcdae716147da7e7747`.

**Expected health:** `scripts/diagnostics/ripwire-context.sh doctor` → 8/8.

### Drushti umbrella workflow

`Drushti` is the user-facing invocation for **Superpowers + Ripwire + Caveman + RTK + Headroom**. The cross-chat recovery source is the verified Library artifact `/Drushti/drushti-global-agent-bundle-2026-09-15.zip`; the current materialized root is `/mnt/data/drushti-global/drushti-global-agent-bundle-2026-09-15`.

Current verified runtime state:

- custom Drushti/Caveman/RTK/Headroom/Ripwire skills installed under `$HOME/.agents/skills`;
- Ripwire 0.6.1 callable from both the MReader workspace-local binary and `$HOME/.local/bin/ripwire`;
- Caveman task-relevant `investigate-first` and `verify-and-stop` workflows available and used for blocker investigation/acceptance-proof discipline;
- Headroom source restored from saved `headroom-main.zip` to `$HOME/.local/share/dev-agents/headroom-0.37.0`; `$HOME/.local/bin/headroom --help` exits 0. No persistent proxy/routing is enabled;
- RTK skill is installed, but no native `rtk` executable is present. Apply the RTK skill's reversible-compression/evidence rules only; never claim RTK CLI execution.

Superpowers remains process authority. Ripwire/Caveman/RTK/Headroom never replace executable acceptance tests, and failed/migration/security evidence must remain available uncompressed.

### Activated Ripwire skills

- `ripwire-before-you-build`
- `ripwire-change-check`
- `ripwire-find-bug`
- `ripwire-fresh-eyes`
- `ripwire-graph-query`
- `ripwire-handoff`
- `ripwire-layers`
- `ripwire-mcp`
- `ripwire-navigate`
- `ripwire-orient`
- `ripwire-perf-target`
- `ripwire-quality-bar`
- `ripwire-reuse-first`
- `ripwire-router`
- `ripwire-security-scan`
- `ripwire-write-tests`

The Ripwire contributor-only optimization-remarks skill is intentionally not activated for MReader application work.

### Ripwire commands used for MReader

```bash
# Resume/orient
scripts/diagnostics/ripwire-context.sh doctor
scripts/diagnostics/ripwire-context.sh handoff
scripts/diagnostics/ripwire-context.sh pack "<current task>"

# Direct CLI when a wrapper mode is not exposed
../../tools/ripwire/bin/ripwire . --impact=SYMBOL --legend=compact
../../tools/ripwire/bin/ripwire . --callers=SYMBOL --legend=compact
../../tools/ripwire/bin/ripwire . --affected=SYMBOL --legend=compact
../../tools/ripwire/bin/ripwire . --quality-delta --legend=compact
../../tools/ripwire/bin/ripwire . --pr-context --legend=compact
../../tools/ripwire/bin/ripwire . --test-gate --legend=compact
```

Interpretation rules:

- `--test-gate` naming tests means **run them**; it does not mean they passed.
- Ripwire `quality-delta` gating findings must be inspected before commit.
- Ripwire output stamped `+dirty` is evidence for the local working tree only; rerun after commit when recording reproducible evidence.
- Ripwire does not close PostgreSQL/Docker/device/browser acceptance gates.

## 6. Key documentation index

### Start here

1. `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`
2. `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
3. `docs/qualification/RC485-P06.3-COMPLETION-GATE.md`
4. `docs/qualification/RC485-P06-CATALOG-PUBLICATION-SOURCE-REVIEW.md`
5. `docs/qualification/RC485-WORK-IN-PROGRESS.md`

### Provenance / ownership / prior phases

- `docs/qualification/RC485-BASELINE-PROVENANCE.md`
- `docs/qualification/RC485-CAPABILITY-MATRIX.md`
- `docs/qualification/RC485-TABLE-DISPOSITION.md`
- `docs/qualification/RC485-REFERENCE-BRANCHES.md`
- `docs/qualification/RC485-P02-READING-SOURCE-REVIEW.md`
- `docs/qualification/RC485-P03-WEB-READING-SOURCE-REVIEW.md`
- `docs/qualification/RC485-P04-ANDROID-READING-SOURCE-REVIEW.md`
- `docs/qualification/RC485-P05-MIGRATION-SOURCE-REVIEW.md`
- `docs/qualification/RC485-READING-UPGRADE.md`

### P06 contract/gate docs

- `docs/qualification/RC485-CATALOG-PUBLICATION-CONTRACT.md`
- `docs/qualification/RC485-P06-CATALOG-PUBLICATION-SOURCE-REVIEW.md`
- `docs/qualification/RC485-P06.3-INGESTION-AUTHORITY.md`
- `docs/qualification/RC485-P06.3-COMPLETION-GATE.md`

### Tooling docs

- `AGENTS.md`
- `docs/development/RIPWIRE-WORKFLOW.md`
- `scripts/diagnostics/ripwire-context.sh`
- `scripts/diagnostics/continuation-status.sh`

## 7. Current P06.3 implementation surface

### Core source

- `services/catalog_go/internal/store/publication.go`
- `services/catalog_go/internal/store/publication_postgres_test.go`
- `services/catalog_go/internal/model/publication.go`
- Media evidence implementation under `services/image_service/app/media_operations.py`
- P06 publication schemas/fixtures under `contracts/`

### Migrations relevant to P06.3

- migration 054: durable Media evidence + Catalog revisions/receipts
- migration 055: canonical ingestion operation actor/revision/cancel/generation authority row
- migration 056: seal completed Media evidence at PostgreSQL level

Use the actual filenames in `db/migrations/`; do not renumber or edit previously shipped migration identities.

### Focused source tests

- `tests/regression/test_catalog_publication_contract.py`
- `tests/regression/test_catalog_publication_boundary_source.py`
- `tests/regression/test_media_publication_evidence.py`
- `tests/regression/test_media_publication_evidence_immutability.py`
- `tests/regression/test_p06_3_ingestion_authority.py`
- `tests/regression/test_p06_3_postgres_gate_script.py`
- `tests/regression/test_migration_runner.py`
- Catalog dependency-free Go model tests under `services/catalog_go/internal/model/`

Exact dependency-free Go model command used in this workspace:

```bash
cd services/catalog_go/internal/model
GO111MODULE=off go test publication.go publication_contract.go publication_contract_test.go -count=1 -v
```

### Real completion gate

Preferred Docker Desktop gate:

```bash
MREADER_TEST_POSTGRES_MODE=docker ./scripts/test/p06-3-postgres-gate.sh
```

External disposable DB mode:

```bash
MREADER_TEST_POSTGRES_DSN='postgres://...disposable...' \
MREADER_TEST_POSTGRES_CONFIRM=disposable \
./scripts/test/p06-3-postgres-gate.sh
```

The sandbox used for this work has no Docker daemon, so the real DB gate is currently **blocked**, not passed. Docker mode supplies PostgreSQL/Go runtimes, but it is not offline: the pinned images and Catalog Go modules must be cached or downloadable. Commit `2dbc64d` prepares Catalog in writable container scratch before the test run because the repository intentionally has no committed Catalog `go.sum`; `ffc166f` pins the Go runtime image to `sha256:f18a072054848d87a8077455f0ac8a25886f2397f88bfdd222d6fafbb5bba440`.

**Fresh reattempt after restoring the newest persistent continuation:** bundle and internal checksums passed; HEAD `0d60bcc`/source `78b5cf8`, branch/stash/refs and Ripwire doctor were verified. `MREADER_TEST_POSTGRES_MODE=docker ./scripts/test/p06-3-postgres-gate.sh` exited **2** at preflight with `ERROR: Docker is required...`; no database process started. Podman/nerdctl and local PostgreSQL binaries are absent, Go is 1.23.2 with no cached 1.25 toolchain, and the available download/package channels could not fetch official runtime artifacts. Runnable evidence was freshly reproduced: 60/60 focused Python, 6/6 migration runner, Catalog Go 3/3, Notification Go 2/2, clean `gofmt`/`py_compile`/`git diff --check`, and Ripwire `gating=0`. This is blocker evidence only, not a runtime pass.

## 8. Exact current task / stop condition

**Task:** close the P10.2 tracker/all-refs checkpoint around source stack `b15b417` + quality evidence `cad8826`. Exact-tree P10.2 source qualification is complete. Preserve P09.1–P09.5 ownership/security/readiness boundaries plus P10.1 truthfulness semantics and P10.2 generation/account/single-flight guards. After checkpoint verification, P11.1 same-checkpoint build/runtime qualification is the next legal lane.

Current accepted checkpoints:

- `54ec3fd`: manual ZIP/CBZ/PDF publication routes through Media durable evidence and Catalog publication commands.
- `b7af7fe`: existing-series Scraper drafts freeze private staging, establish Scraper ingestion authority, send raw staged pages to Media for final v4 transform, reconcile the durable Catalog receipt, then finalize/clean private staging.
- `b709d03` (recovery; historical `ec273f9`): batch publication uses the same retained-actor Media → Catalog chain.
- `8cdfdf4` (recovery; historical `5466101`): new-series chapters use the same chain and the orphan Scraper chapter publisher/transform/event stack is removed.
- `8ecc4c4` (recovery; historical `631ddbf`): Scraper delegates series/taxonomy to Catalog and cover bytes to Media; Catalog alone owns canonical series/taxonomy/cover mutation and Catalog-domain events; final non-Catalog production writer/event scan is clean.
- `0f1fadb` (recovery; historical `4325575`): workload-specific secret allowlists/renderer are active; broad namespace secret bundles are retired after rollout; future private credentials remain unallocated until P06.5.
- `581c310` (recovery; historical `c82650a`): private Catalog/Media routes require scoped workload credentials and a retained active admin; internal callers send exact scoped credentials; both gateways deny `/internal`; the public Catalog chapter-publish route is fail-closed behind Media evidence; hybrid bootstrap generates only missing private tokens. Fresh gate: 103/103 publication/security/authority + 18/18 runnable Scraper + ownership/WebP/136-route/direct-writer/compile/syntax/diff + Ripwire `gating=0`.
- `d79e340` (recovery; historical `2954469`): ordinary Catalog `UpdateChapter` rejects draft→published without Media evidence; `CommitPublication` is the sole Catalog `chapter.published` writer; the HTTP update route maps blocked promotion to 409; Notification dedupe remains publication-revision scoped. Fresh gate: 98/98 publication/security/authority + 18/18 runnable Scraper + dependency-free Notification event tests + ownership/WebP/136-route/writer/gofmt/diff + Ripwire `gating=0`.
- `24adb72` (recovery; historical `ae6f4c7`): manual Media acceptance atomically creates `manual-upload` ingestion authority with durable Media acceptance; internal Scraper calls validate an existing exact actor/source-kind/source-revision/lease-generation/cancel authority row; existing-series, batch and new-series submit their canonical source kinds. Fresh gate: 102/102 publication/security/authority/P07.1 + 18/18 runnable Scraper + 5/5 mapped Media evidence + ownership/WebP/136-route/compile/diff + Ripwire `gating=0`.
- `f5c34a7` (recovery; historical `cd921e6`): stale Scraper takeover and cancellation share Catalog's advisory operation fence and receipt-first decision; batch and series-draft recovery project canonical committed/cancelled/recovered outcomes before legacy requeue; Media heartbeat/retry/completion/failure transitions require the exact claimed `media_generation`; lease loss preserves deterministic outputs for reconciliation. Fresh gate: 94/94 publication/security/authority/P07.1/P07.2 + direct runnable Scraper files rc=0 + ownership/WebP/136-route/compile/diff + Ripwire `gating=0`; hardening and Catalog Go runtime remain blocked by missing `selectolax` and Go 1.23.2 vs >=1.25.
- `6e42f6b` (recovery; historical `b5ddd8a`): URL-backed missing staging bytes can be repaired only via explicit Stage/Retry under revision + stage-generation fences; missing manual bytes require re-upload; Preview/Publish remain staging-only; stale stage recovery increments generation; fence-loss exact-path cleanup is committed before conflict; the thumbnail compatibility route is a 202 alias to the durable Media job and the Admin client waits for completion. Fresh gate: 104/104 publication/security/authority/P07 regressions + 18/18 runnable Scraper + ownership/WebP/136-route/compile/diff + Ripwire `gating=0`; hardening, Catalog Go, frontend dependency, and API `psycopg` runtime checks remain blocked, not passed.
- `394e440`: P07.4 records exact page-primary/page-responsive/cover cleanup refs plus the relevant Media generation in Catalog delete/replacement transactions; page and cover state persist production generation; Media hands production-output cleanup to durable Lifecycle jobs; Lifecycle rejects legacy `storage_prefixes`, checks live Catalog path ownership and Media generation before deletion, and is the sole production physical deleter. Fresh gate: dependency-light regression suite OK with 223 tests reported and 10 intentional skips; 18/18 runnable Scraper tests; API ownership + WebP + 136-route audits; changed Python compile, Go formatting and diff checks; 6/6 ingestion-authority tests; Ripwire `gating=0`. Hardening remains blocked by missing `selectolax`; Go runtime partner remains blocked by local Go 1.23.2 vs >=1.25; frontend dependencies and API `psycopg` remain absent; P06.3 PostgreSQL runtime remains deferred/unexecuted.
- `26d80a1`: P07.5 adds one canonical new-series parent ingestion header, links chapter operations to it, synchronizes coordinator retry/recovery/cancel transitions, projects canonical operation status/phase/generation to admin surfaces without discarding editable workflow detail, and returns Catalog DELETE cleanup receipts so the UI distinguishes metadata removal from asynchronous Lifecycle cleanup. Migration 059 backfills existing drafts/child links without media mutation. Fresh gate: 233 dependency-light regression tests with 10 intentional skips, explicit P07.5 10/10, 18/18 runnable Scraper, 6/6 ingestion-authority, API ownership, WebP, 136-route, changed Python compile, Go formatting, diff checks and Ripwire `gating=0`. The broad static shell runner was attempted but exceeded the 120-second harness limit after its first four tests passed, so no full-pass claim is made. Hardening/Go/frontend/API runtime blocks remain unchanged.
- `c5e6866`: P08.3 keeps recovery bytes/root ownership in the host-local backup agent and adds a narrowly authenticated read-only bridge by opaque `bkp_...` ID. Scraper proxies verified download without learning host paths; neither gateway exposes the bridge; Kubernetes workloads do not mount the protection root; bridge staging rejects symlinked root/staging paths; the bridge credential is limited to the backup-agent/Scraper boundary. Fresh gate: 237 dependency-light regression tests with 10 intentional skips, 18/18 runnable Scraper, recovery-bridge Go tests + vet, 11 targeted backup/deployment/ownership/route/WebP gates, syntax/format/diff checks and Ripwire `gating=0`; one narrow acknowledgement documents the intentional historical future-secret test evolution.
- `c8a7c52`: P08.4 moves the database-protection HTTP facade into `app/database_facade.py` at canonical `/api/admin/database`; admin Caddy explicitly proxies that namespace while the user gateway denies it; frontend and API coverage move in the same checkpoint; old `/api/scraper/admin/database*` aliases are retired. Scraper staging initialization may degrade without preventing the facade process from starting, but scraper readiness remains false when staging is unavailable. The existing `database_operations` queue, recovery catalog and backup-agent restore engine remain the only authorities, and P08.3 private download boundaries are preserved. Fresh gate: 242 dependency-light regression tests with 10 intentional skips, focused P08.3/P08.4 10/10, 18/18 runnable Scraper, database-protection static contract, API ownership, WebP, 136/136 route audits, changed Python compile/diff checks and Ripwire `gating=0`. Runtime registration/hybrid validation remains blocked by absent `asyncpg`/Docker/frontend dependencies.
- `d264486`: P08.5 adds explicit verified legacy/NAS bundle import into the canonical local store with local provenance, rejects tampered/unsafe/incompatible inputs, makes capture completion UTC the retention age, generates fail-closed transient pins for active restore/drill and unresolved cutover sources, preserves current pre-upgrade/pre-restore safety points plus the last verified recovery point, and exposes bounded opaque keyset paging through the canonical facade and admin UI. Fresh gate: 253 dependency-light regression tests with 10 intentional skips, focused P08.5 11/11, all 10 recovery/database shell contracts, 18/18 runnable Scraper, API ownership, WebP, 136/136 route audits, syntax/compile/diff checks and Ripwire `gating=0`. Runtime/browser/combined-hybrid qualification remains blocked by absent Docker/frontend dependencies/`asyncpg`; other known blockers remain unchanged.
- `f051fc7`: P08.6 aligns normal and catalog-only restore source selection on the canonical verified local recovery store. Normal restore accepts `latest`, `latest-snapshot` or opaque verified `bkp_...` IDs and preflights opaque IDs before confirmation/quiescence; catalog-only recovery accepts only an opaque ID, stages the verified artifact under the canonical root, preserves the empty-target exact seven-table SQL contract, and creates its pre-import safety point through `backup_agent pre-restore` instead of a second direct dump path. Fresh gate: 258 dependency-light regression tests with 10 intentional skips, focused P08.6 5/5, all 11 recovery/database shell contracts, 18/18 runnable Scraper tests, API ownership, WebP, 136/136 route audits, shell/Python syntax plus `git diff --check`, and Ripwire `gating=0`. Known Docker/frontend/asyncpg/psycopg/selectolax/Go blockers remain unchanged.
- `8f01117`: P08.7 source-prepares logical and physical-snapshot restore drills on the existing canonical queue/restore engine. Both drill paths apply current migrations and publish structured counts, UTF8 encoding, chapter/page orphan integrity, v4 protected-page encoding, validated-FK state, latest migration, runtime CONNECT/series SELECT and extra-database evidence; `postgres-restore-drill.sh` composes the existing read-only NAS/media check with opaque-ID restore-drill execution. Fresh source gate: 262 dependency-light regressions with 10 skips, focused P08.7 4/4, all 11 recovery/database shell contracts, 18/18 runnable Scraper, API ownership, WebP, 136-route, shell/Python syntax/diff and Ripwire `gating=0`. Actual Docker/PostgreSQL drill execution remains blocked, not passed.
- `cbaf5a8`: P08.8 binds destructive restore to installation fingerprint + exact opaque source/hash + expected host generation, rechecks at claim and pre-cutover, pins exact source+safety IDs, journals every destructive phase externally, deterministically reconciles interruption states, selectively invalidates replay-unsafe restored ingestion/media/outbox work, mirrors committed generation into PostgreSQL and only then advances host generation. Fresh exact-tree gate: 282 dependency-light regressions with 10 skips; P08.8 20/20; all 10 current recovery/database shell contracts; 18/18 runnable Scraper; API ownership, WebP, 136-route, syntax/compile/diff and Ripwire `gating=0`. Actual Docker/PostgreSQL interruption rehearsal remains blocked.
- `56337e0`: P09.4 readiness/generation enforcement is source-qualified. One canonical host-side readiness gate reuses P09.3 catalog privilege verification and checks schema/migration, narrow workload credentials and the P08.8 restore-generation mirror; deterministic generation stamping covers all 17 database-dependent Deployments including replica-zero workers; rollout/live-template proof precedes HPA/KEDA restoration; production restore re-enters canonical deploy rather than directly reviving workloads. Fresh exact-tree P09.4 evidence on `56337e0`: focused P09.4 18/18 PASS; inherited P09.3 20/20 PASS; PostgreSQL role audit PASS (15 capabilities / 18 workload identities); inherited P08.8 + secret-scope regressions 28/28 PASS; pre-upgrade ordering PASS; all 10 current recovery/database shell contracts PASS; full dependency-light discovery 335 tests with 10 intentional skips and 0 failures; runnable Scraper 18/18; ownership/route 136/136 plus API ownership, route coverage and WebP PASS; shell syntax, Python compile and `git diff --check` PASS; Ripwire `e03ef17..56337e0` `gating=0`. The P09.3 real PostgreSQL permission gate remains BLOCKED rc=2 because Docker is unavailable and no authorized disposable DSN is present. The P09.4 real runtime gate remains BLOCKED rc=2 because no explicitly authorized current-hybrid target was supplied; neither blocker is a PASS.

- `7c292fe`: P09.5 route/consumer denial is source-qualified. Both gateways explicitly fence retired and private/internal routes; the public gateway additionally fences admin and Catalog-write surfaces. Web and Android are checked against the same-tree route manifest and preserve safe domain/request metadata. Route discovery now includes Media `internal_router`, expanding authority from 136 to 139 current routes; the manifest declares 10 source-proven direct HTTP→event publish effects. Existing Catalog/Progress/Media outbox producers attach safe owner/request/operation/revision/error metadata, and outbox-relay exposes only the allowlisted metadata in the broker envelope. Fresh exact-tree evidence: focused P09.5+P09.2 24/24; dependency-light 345 tests / 10 skips / 0 failures; Scraper 18/18; ownership/route 139/139; PostgreSQL role audit 15 capabilities / 18 identities; API ownership, route coverage, WebP, Python compile, TypeScript typecheck, `gofmt` and diff check PASS. Android Gradle compile remains BLOCKED by DNS/download unavailability; Catalog/Progress/Outbox Go compile remains BLOCKED by local Go 1.23.2 vs required 1.25. Ripwire raw ref-pair surfaces three unchanged pre-existing dead-code false positives; excluding exactly those three byte-unchanged files yields `gating=0` over the P09.5 changed surface.
- P09.4 durability exception: after the P09.4 package itself was verified in-chat, the user explicitly authorized a **one-time** waiver of the Library re-materialization rule so P09.5 could begin. This is provenance, not a general rule change; P09.5 and later checkpoints return to the normal durability gate.
- P06.3 PostgreSQL runtime qualification remains **deferred/unexecuted**, not Verified; preserve it as runtime debt.

Next legal implementation order:

1. complete the P11.3 tracker/all-refs/Library durability checkpoint around source/test commit `a88e275`;
2. continue P11.4 independent source/release review under the explicit sequencing waiver;
3. rerun P11.1/P11.2/P11.3 runtime acceptance in an authorized topology before any release claim;
4. preserve P09.1–P09.5 credential/route/event/readiness boundaries plus P10.1 truthfulness and P10.2 race/outage guards; do not invent fallback contracts or raise resource limits.

P07.5 runtime restart/worker-loss/KEDA/browser execution remains P11 qualification debt; do not reopen P07 source ownership merely because this sandbox lacks those runtimes.

The old `stash@{0}` is superseded by committed work and is forensic only. Do not reapply it over the active branch. Frontend TypeScript typecheck is now runnable and passed at P09.5; browser-level/P03 behavior qualification remains open until its specific Playwright/runtime cases and independent review are completed.

## 9. Fresh-chat resume commands

Run these before editing:

```bash
cd /mnt/data/mreader-rc485-working

# 1. Read authorities
sed -n '1,240p' docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md
sed -n '1,320p' docs/continuation/RC485-CONTINUATION-MANIFEST.md
sed -n '1,320p' docs/qualification/RC485-P06.3-COMPLETION-GATE.md

# 2. Verify repo identity/state
git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline --decorate -20
git stash list
git remote -v

# 3. One-command workspace summary
./scripts/diagnostics/continuation-status.sh

# 4. Verify Ripwire
./scripts/diagnostics/ripwire-context.sh doctor
./scripts/diagnostics/ripwire-context.sh handoff
./scripts/diagnostics/ripwire-context.sh pack "P07.5 operation status UI retry restart KEDA redelivery"
```

Then compare live state to the tracker. If different, inspect/record the difference **before** editing.

## 10. Portable continuation artifact

The workspace checkpoint is exported as:

- rolling container path: `/mnt/data/mreader-rc485-continuation-recovery-<tracker-head>.zip`;
- checksum sidecar: matching `.zip.sha256`;
- **persistent Library authority:** `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip`;
- persistent companions: `/MReader/RC4.85/mreader-rc485-continuation-recovery-current.zip.sha256`, the sequential tracker, this manifest, and `RC485-SANDBOX-LOSS-RECOVERY.md`.

The ZIP is a **handoff/recovery package, not an MReader release**. It contains a Git bundle created from `--all`; the bundle must include `refs/stash`, all `sequential/*` branches, all local `reference/*` branches, and the imported `reverse-reference/*` tracking refs. It also contains key tracker/qualification/reference docs, a live status snapshot, the verified Ripwire binary and skills archive, restore instructions, and internal SHA-256 checksums.

After every meaningful continuation-manifest/branch/stash/tooling change, regenerate this artifact before treating it as current. The `.sha256` sidecar is authoritative for the bytes; the hash is intentionally not embedded in this tracked document because doing so would recursively change the exported repository contents.

## 11. If the `/mnt/data` workspace is missing in a new chat

A new chat may receive a new sandbox. Absolute `/mnt/data` paths are therefore location hints, not a guarantee of persistence.

Recovery order:

1. Prefer the portable continuation bundle generated from this canonical repo if available. It contains a Git bundle of all refs plus the tracker/manifest/tooling instructions.
2. **Do not rely on `git clone <bundle>` alone**: Git clone checks out the default branch but does not reconstruct every local branch or the stash reflog. Restore all refs explicitly as shown below.
3. Restore the workspace-local Ripwire tool bundle or rebuild from the user-provided `ripwire-main.zip`; then run doctor 8/8.
4. If no Git bundle exists, start from `mreader-rc485-milestone-1-source-test(3).zip`, then use the continuation manifest/recorded commits/reference patches to recover work. This is a last resort because it loses the easiest branch/stash continuity.
5. Never substitute the reverse-order repo, P09 merge-unit ZIP, or 17c28ac patch for the canonical sequential history.

### Proven clean-room Git-bundle restore

```bash
BUNDLE=/path/to/mreader-rc485-sequential-all.gitbundle
mkdir -p /work/mreader-rc485/mreader-rc485-milestone-1
cd /work/mreader-rc485/mreader-rc485-milestone-1
git init

# Restore all sequential/reference branches and imported remote-tracking refs.
# Put the saved stash commit under a temporary recovery ref first.
git fetch "$BUNDLE" \
  'refs/heads/*:refs/heads/*' \
  'refs/remotes/*:refs/remotes/*' \
  'refs/stash:refs/recovery/p06.4-stash'

git switch sequential/p06-catalog-publication-review

# Recreate the stash reflog so `git stash list` works normally.
git stash store \
  -m 'On sequential/p06.4-caller-cutover: P06.4 WIP paused for P06.3 completion gate audit' \
  refs/recovery/p06.4-stash

# Optional after verifying the stash exists:
git update-ref -d refs/recovery/p06.4-stash

git stash list
git branch --list 'sequential*'
git branch --list 'reference/*'
git for-each-ref refs/remotes/reverse-reference --format='%(refname)'
```

This procedure was clean-room tested from the generated bundle: it restored 9 sequential branches, 4 local reference branches, 2 `reverse-reference/*` tracking refs, and the three-file paused P06.4 stash.

After restoration, update the absolute paths in the tracker/manifest if the repo root changed. The **relative repo paths, branch names, commit IDs, stash description, tracker path, and gate commands** are the stable identifiers.

## 12. Anti-footgun rules

- Do not work from `/mnt/data/mreader_rc485_reverse_work/...`.
- Do not use `reference/*` branches as implementation branches.
- Do not apply the cumulative `17c28ac` WIP patch wholesale.
- Do not reapply/pop the superseded P06.4 stash during normal continuation; preserve it for forensic comparison until P06 caller cutover completes.
- Do not modify old migration files to repair already-shipped behavior; use forward migrations.
- Do not count static/source tests as runtime PostgreSQL verification.
- Do not let Ripwire findings substitute for tests; execute the tests it names.
- Do not increase resource limits to make a failing gate pass.
- Do not package Milestone 2 until the tracker says the P06/P07 competing publication/cancellation paths are removed.
- Update tracker + continuation manifest whenever branch, HEAD, stash, canonical repo path, tool install path, current task, blocker, or required resume command changes.


## P11.4 source/release-integration review state

- Source/test checkpoint `ed53fc51c96b299427781f4b2564911accba7c97` repairs two stale release-validator assertions only; no production behavior/resource limit changed.
- Fresh source evidence: Web 31/31; Android 8/8 + full static audit; migration/quiescence 21/21 + ordering; P09 source fences 34/34 + 28/28; P10 truthfulness/races 50/50; API ownership + 139/139 route coverage; pressure/resource guards; exact current-release validator source/static path PASS.
- Ripwire reports `untested=0`; its one changed-test obligation (`dependency-pins.sh`) was run green.
- Independent review remains BLOCKED because no separate reviewer/subagent integration is available. Self-review is not recorded as independent.
- P11.1-P11.3 runtime gates remain BLOCKED and RC4.85 is not release-qualified.
- Resume from `docs/continuation/RC485-NEXT-CHAT-P11.4.md`; preserve forensic stash `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4`.


## P12.2 source-test/deployment package

- Historical artifacts through `mreader-rc485-p12.2-source-test-3020fc3.zip` remain preserved.
- Current packaged tree: `c4bf03f1238f47faafaecff59705a9e44ced717d`.
- Current artifact: `mreader-rc485-p12.2-source-test-c4bf03f.zip`.
- SHA-256: `7fd19bd2eb14be605139ed70e424d4b44f921cb3338da7e095a649fc138bb21f`.
- Root cause repaired: Git Bash/MSYS rewrote Linux container `/tmp/preupgrade-*` arguments passed to native Docker into Windows host temp paths, causing `pg_dump -f` inside the Linux PostgreSQL container to target a non-existent `C:/Users/.../AppData/Local/Temp/...` path.
- Repair scope: `scripts/hybrid/create-local-preupgrade-backup.sh` Docker capture/copy/cleanup boundaries now use `MSYS_NO_PATHCONV=1`; no database migration or schema behavior changed.
- Verification: local pre-upgrade backup 6/6, hybrid ordering, MSYS container-path contract, PostgreSQL volume inspection, explicit volume ownership/adoption, shell syntax and current-release source/static validator PASS.
- Package integrity: 945 checksum entries, 941 exact committed files, byte-identical deterministic rebuild.
- P11.1-P11.4 release blockers remain unchanged.

### 2026-09-17 initialization pre-upgrade backup bypass

Current P12.2 source checkpoint: `2b199295cc308fca764c7c2ce268e0a5d84fd8fb`. For explicit initialization/testing only, `MREADER_SKIP_PREUPGRADE_BACKUP=true` skips the mandatory pre-upgrade PostgreSQL bundle; safe default remains `false`. Current deployment ZIP: `mreader-rc485-p12.2-source-test-2b19929.zip`, SHA-256 `f4613bd0aab8448a0d2894aa46a95e7407a58cc96f8c9a214a1070297642708e`. Verification: bypass contract PASS, original ordering PASS, local pre-upgrade backup suite 6/6 PASS, current-release source/static validator PASS.


### 2026-09-17 P12.2 pre-upgrade host-jq runtime fallback

Current P12.2 source checkpoint: `c9dde2b278cda2d67e3ad672d3935fdd06e7a045`. Pre-upgrade recovery capture no longer requires `jq` on the Windows/Git-Bash host: host `jq` is used when present; otherwise the exact canonical `local-recovery-store.sh publish-staged` validator runs inside the pinned `backup_agent` runtime against `/mreader-db-protection`, with MSYS argument conversion disabled. Validation remains fail-closed. Current deployment ZIP: `mreader-rc485-p12.2-source-test-c9dde2b.zip`, SHA-256 `2c3a04da5f8d17a8e985b19a646de970ef5e0250a73b10c1d11670911533a28b`. Verification: local pre-upgrade suite 7/7 PASS including no-host-jq fallback, ordering/bypass/MSYS/volume checks PASS, current-release source/static validator PASS.

## 2026-09-17 P12.2 Git-Bash Compose host-path normalization

Current P12.2 source checkpoint: `8b1415a8c330816e459ad5e7c29b73336961a105`. The no-host-`jq` fallback still runs canonical recovery-store validation inside `backup_agent`, but Windows host paths used for `--env-file` and `-f` are now preconverted to native `C:/...` form before `MSYS_NO_PATHCONV=1` is applied. Linux container paths such as `/mreader-db-protection/...` remain untouched. Current deployment ZIP: `mreader-rc485-p12.2-source-test-8b1415a.zip`, SHA-256 `101f879451a6b455516fce679ecb3b35e9033a4c19366ac0d87749d2a09be51b`. Verification: local pre-upgrade suite 8/8 PASS including mixed MINGW host/container-path coverage; ordering/MSYS/volume/bootstrap/current-release source-static checks PASS.

## 2026-09-17 P12.2 backup-agent Alpine compatibility repair

Current P12.2 source checkpoint: `ac7bccc8cf5043584b9d7260055d38463bae448f`. The backup-agent image keeps its PostgreSQL Alpine base digest pinned but replaces brittle exact Alpine `-rN` runtime package revisions with minimum-compatible constraints (`bash>=5.2.37`, `jq>=1.8.1`, `coreutils>=9.7`, `tzdata>=2026a`). This prevents stable-repository revision rollovers from making the image unbuildable while preserving explicit compatibility floors. Current deployment ZIP: `mreader-rc485-p12.2-source-test-ac7bccc.zip`, SHA-256 `60323704899eae4d2bb5ce7f3497f76ba2855490d3857cf1ff5b45c8d2b994b7`. Verification: dependency policy PASS, backup-agent static PASS, local pre-upgrade 8/8 PASS, ordering/MSYS/bootstrap/current-release source-static checks PASS.

### 2026-09-17 P12.2 BusyBox recovery portability repair

Current P12.2 source checkpoint: `9793fed4a7b5f9e47a5b3950826e6bfae1aa8e4c`. After BusyBox `find` portability was repaired, real-host canonical recovery validation exposed Windows/GNU binary checksum markers (`HASH *filename`) and GNU-only `sha256sum --strict --status` assumptions. The validator now accepts text/binary mode markers while normalizing the filename before exact allowlist and duplicate checks, and uses portable `sha256sum -c` after strict structural validation. Current deployment ZIP: `mreader-rc485-p12.2-source-test-9793fed.zip`, SHA-256 `b41ea719b95f54f773fa56988bcc41388e1075a5e378af2db7e67d574aa540fa`. Verification: Windows binary-marker + BusyBox regression PASS, local recovery catalog 10/10 PASS, local pre-upgrade suite 8/8 PASS, ordering/MSYS/bootstrap/current-release source-static checks PASS.


### 2026-09-17 P12.2 initial restore-generation seed

Current P12.2 source checkpoint: `4fbd847af7ae6f7a2f0bd8704ae34bc272fc8f4f`. Fresh initialization now creates/reads the canonical host restore control and seeds PostgreSQL `database_restore_state` only while the singleton remains the migration default (empty fingerprint / generation 0). Matching existing state is idempotent; any non-default mismatch remains fail-closed. `stateful-up.sh` invokes this after migration + role reconciliation and before P09.4 readiness. Current deployment ZIP: `mreader-rc485-p12.2-source-test-4fbd847.zip`, SHA-256 `8358d123386461c60ed3e0287deb327c294737b692fd0439867fa695e89da557`. Verification: P08.8/P09.4 39/39 PASS, initialization/pre-upgrade/MSYS/bootstrap checks PASS, package 950/950 Git files exact, 953/953 package checksums PASS, deterministic rebuild byte-identical. P11 blockers remain unchanged.

## 2026-09-17 P12.2 cross-platform boundary reliability audit

Current P12.2 source checkpoint: `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6`. Repository-wide audit fixed the remaining confirmed variants of the real-host portability failures: catalog/test Docker path boundaries now share one MSYS-safe helper; PostgreSQL restore and P09.4 runtime validation no longer require host `jq`/Python; catalog recovery-store operations execute in the backup-agent runtime; and all active Alpine service/diagnostics `apk` packages use compatibility floors instead of exact mutable `-rN` revisions. BusyBox copied-script and readiness producer/consumer sweeps found no additional confirmed production defect. Deployment ZIP: `mreader-rc485-p12.2-source-test-a7d7a40.zip`, SHA-256 `907c7bc1f1bf88c4ae94786584d8f31fc99ec86dfa3074f0dc6ce4ca9b62a007`. Verification: 49/49 P08.6/P08.7/P08.8/P09.4, 8/8 pre-upgrade, MSYS mixed/container paths, initialization/pre-upgrade ordering, backup-agent static, dependency pins, Dockerfile static and current-release source/static validator PASS. Package: 955 committed files exact, 958 checksums PASS, deterministic rebuild byte-identical. Residual IM-01 (patch-exact base image tags without universal digests) is recorded as a separate low-severity reproducibility candidate, not silently closed.

## 2026-09-17 P03.2 browser acceptance source coverage

Source `d7fd2948f64920a8851780e64d94de6a795c6c7a` adds validator-enforced Playwright source scenarios for two-tab durability, quota failure, offline refresh/reconnect, late-ack race, and media failure without false completion. Fresh locally runnable evidence: Web reading 31/31 PASS, browser acceptance source contract PASS, all browser specs parse, current-release source/static validator PASS. Real Playwright execution and independent review remain open; P03.2/P11.4 are not accepted.

P03.2 package authority: `mreader-rc485-p12.2-source-test-d7fd294.zip`, exact source `d7fd2948f64920a8851780e64d94de6a795c6c7a`, SHA-256 `12e37a434d9f2cd2e824d4ebee174563da57ba23b091c18b0df9c4ae25e22e51`; 957/957 committed files exact, 959/959 package checksum entries, deterministic rebuild byte-identical. Real Playwright execution and independent review remain open.

## 2026-09-17 P12.2 Windows drive-form Python host-input repair

Current deployment-test source is `b80c030327e16a9e05dfd7b979a5b5ee668ce2de`. Git Bash regression execution exposed that the synthetic `Z:/...` fixture was Linux-relative but a real drive path on Windows, while the Docker-Python fallback also relied on the shell's direct `-e` check for drive-form inputs. The runtime now resolves such inputs through `cygpath -u` before existence checks, then bind-mounts them read-only and passes `/mreader-host-input-N` to Linux Python. The regression uses an explicit conversion fixture and demonstrates RED on the pre-fix behavior. Deployment ZIP: `mreader-rc485-p12.2-source-test-b80c030.zip`, SHA-256 `afe1cd9030ee64602a6840714af54bff1e083f204e15bca1499d1324d1e26ebc`; 960/960 Git files exact, 967/967 package checksums, deterministic rebuild byte-identical. Real Windows/Docker remains the acceptance gate.

### 2026-09-17 P12.2 application crash-loop startup contract repair

Real-host Kubernetes deployment exposed four CrashLoopBackOff workloads after cluster bootstrap: `auth-service`, `auth-admin`, `image-service`, and `progress-go`. Source `4cd61f40019f84c90b491af52cdc69155c6efcce` fixes two exact startup contracts: shared Python SQLAlchemy converts portable dedicated `postgresql://`/`postgres://` DSNs to `postgresql+asyncpg://`, and `progress_runtime` receives read-only `reading_state_v1` view access required by `ValidateReadingSchema()` and series-state reads. The P09.3 ownership audit now models views separately from tables. Deployment ZIP: `mreader-rc485-p12.2-source-test-4cd61f4.zip`, SHA-256 `93fa31dfca130aa772923ad7d1b06a27861037367cfda32eb426cf98c0cdd8e8`; 962/962 exact Git files, 968/968 package checksums, deterministic rebuild byte-identical. Full current-release validator exit 0; Windows/Docker pod-health rerun remains the host acceptance gate.

## 2026-09-17 P12.2 image-service router startup import-cycle repair

Real-host Kubernetes logs from `mreader-admin/image-service` proved Uvicorn exited before serving `/health`: `jobs.py` imported upload validation constants from `upload.py`, while `upload.py` imported `_submit_thumbnail_job` back from partially initialized `jobs.py`. The earlier P07.3 cutover had also deleted `IMAGE_MIME_TYPES` from `upload.py`, so a second import failure was latent behind the cycle.

Current deployment-test source is `d0558300318c422853c50904b003aaa9067364fe`. Shared media validation constants now live in neutral `services/image_service/app/media_validation.py`; both routers import that module and `jobs.py` no longer imports `upload.py`. Deployment ZIP: `mreader-rc485-p12.2-source-test-d055830.zip`, SHA-256 `68e60f6b02a0a6dc750bb5fb49e171d62fb0b8b1a1567684b90c2c71c070213c`. Verification: startup contract 2/2, affected media/staging/ownership 27/27, compileall, API ownership, consolidation and full current-release validator PASS; package reopen 970/970 checksums and 964/964 exact Git files with executable modes preserved. Real Windows/Docker pod health remains open; P11 blockers remain unchanged.

## 2026-09-18 containerized diagnostics checkpoint

- Current diagnostics source package authority: `mreader-rc485-p12.2-source-test-7f52ea5.zip`.
- Exact source: `7f52ea56269ee8c7a0103a432ec0b0691991ed25`.
- Package SHA-256: `01f509870eab245ed6a2eb3054729d0d2810f93bc3cbcda6f0f544bcfc15c5a7`.
- Module entry points: `./diagnose-mreader.sh` and `./test-mreader.sh --diagnose`.
- Fresh qualification: diagnostics unit 16/16; diagnostics/static/MSYS guards PASS; API route audit 139/139; full current-release validator `VALIDATE_RC=0`; Ripwire changed-surface `gating=0`.
- Package reopen: 986/986 internal checksums, 980/980 Git bytes exact, 980/980 Git modes exact; deterministic rebuild byte-identical.
- First real Windows/Docker Desktop diagnostics execution remains OPEN. P11.1-P11.4 runtime/independent-review blockers are not waived or closed.

## 2026-09-18 P12.3 actor-journey diagnostics

- Source commit: `571190a4d5553ecaa57b92ef7df1c8255dafe1e5`.
- Package: `mreader-rc485-p12.3-source-test-571190a.zip`.
- SHA-256: `144edffbd96f449dfb56cd3ce5d4779c1f8ecfcb0289c4947b29faf9a218351e`.
- Full diagnostics now covers self-contained user/admin API actor journeys plus Playwright browser journeys.
- Optional real fixtures: scraper series URL, scraper chapter URL, ZIP/CBZ/PDF chapter file, cover image.
- First live report analyzer false positives fixed; real PostgreSQL grant findings remain application evidence for the next debugging cycle.
- Qualification: `docs/qualification/2026-09-18-rc485-p12.3-actor-journey-diagnostics.md`.

## 2026-09-18 P12.4 Graphify development-reference authority

Current source checkpoint: `887e0ec99e806f45416e84df13bb44960b6480f0`. Current deployment-test package: `mreader-rc485-p12.4-source-test-887e0ec.zip`, SHA-256 `50706c81f353cf225f0afb01fc9cc1e94a5e03056c043cbed2c2a88335e176c1`. P12.4 adds reproducible repository-relative Graphify/Ripwire code/development maps, issue→change tooling, bounded evidence generation and a packaged root `graphify-out/graph.json` for immediate `Drushti continue .` graph discovery. Qualification evidence: 3/3 development-reference tests, static gate, 139/139 route audit, Graphify/Ripwire evidence build, Ripwire gating=0, full current-release validator exit 0, deterministic rebuild, 1,042/1,042 package checksum entries and 1,000/1,000 exact Git bytes+modes. Native Graphify Tree-sitter extraction remains LIMITED in this sandbox; deterministic builders mark EXTRACTED vs INFERRED edges. P11 runtime and independent-review blockers remain unchanged.

## 2026-09-18 P12.5 live-diagnostic repair checkpoint

Source `f6a2c14aeace8c9f16d08fb28f91063120a483ac` repairs the concrete failures found by the first actor/browser diagnostic runs: API collection helper/dependency gaps, Catalog taxonomy write grants, Social `reading_state_v1` read access, realtime explicit-login acceptance and the current admin database privacy UI contract. Deployment package: `mreader-rc485-p12.5-source-test-f6a2c14.zip`, SHA-256 `009c1af914d2fcb34d19bd6549cb60c12e46d5cb99c7f574a99f92f05ae00279`. Existing deployments must run `./hybrid-up.sh` before `./diagnose-mreader.sh` so PostgreSQL role reconciliation repairs live grant drift. P11 blockers remain open.

### P12.6 no-host-Python Graphify reference repair — 2026-09-18

- Source `7bea1fc6817a6560b45bc30f8e76d3233dd76622` removes direct host-Python calls from the Graphify/development-reference shell path and uses the shared Docker-capable Python runtime.
- Package `mreader-rc485-p12.6-source-test-7bea1fc.zip`, SHA-256 `3ecaaa9753d2bec5e9cd66dbc85245c66eb001c45f4b43760d943323fa9dba5d`.
- Verification: no-host-Python PASS; development-reference 4/4 + static PASS; 139/139 route audit; release validator PASS; Ripwire gating=0; package 1,036/1,036 checksums and 1,003/1,003 Git files/modes exact.
- Real host must rerun `./scripts/bootstrap.sh`, `./hybrid-up.sh`, then `./diagnose-mreader.sh`.
- P11 runtime/independent-review gates remain open.

## 2026-09-18 P12.7 deep permission and architecture diagnostics

Current source is `a081944a335c899223d057dead9c0803c8887bf0`; package `mreader-rc485-p12.7-source-test-a081944.zip`, SHA-256 `928de38d6fb2e3b033bfa3f2950682bc9b410e2dc38c415e10ffe1b54cafef46`. P12.7 adds an 832-case live PostgreSQL effective-permission oracle and a 272-case gateway/routing/CORS boundary matrix, for 1,104 architecture checks before existing API/actor/browser suites. It also adds the Reader UI -> IndexedDB -> Progress -> PostgreSQL -> Smart Library API -> History UI browser chain and layered failure-cascade reporting. Verification: P12.7 5/5 + 4/4 PASS, diagnostics 25/25 PASS, 139/139 route audit, 15-capability/18-workload role audit, full release validator PASS, Ripwire gating=0, deterministic package, 1,052/1,052 package checksums and 1,010/1,010 Git files/modes exact. Real-host Docker/Kubernetes execution remains required; P11 blockers remain open.

## P12.8.1 qualification isolation checkpoint — 2026-09-18

Source/test commit `dc456f1c61835d29d71223afdf30ecca5a1f3fde` fixes the P12.8 user-qualification orchestration so it has no executable host-Python dependency. The 800-case qualification remains container-first: API/functional/integration/admin/scraper tests execute in the dedicated diagnostics image, browser E2E in the Playwright image, and the two Python source/report helpers are forced through the pinned Docker Python runtime. `tests/regression/user-perspective-qualification-static.sh` itself is shell-only so the static gate does not introduce a Docker/Python dependency before the runtime phase.
