# RC4.85 Sandbox-Loss Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production reconstruction uses RED -> GREEN -> review -> verification. The original later Git objects are unavailable; do not claim recovered commits use the historical hashes.

**Goal:** Reconstruct the clean P07.3 handoff state that historically ended at source checkpoint `b5ddd8a` and tracker checkpoint `5b774b7`, starting from the last persistently recoverable source checkpoint `5ca3f41`, then resume P07.4.

**Architecture:** Preserve the already-approved ownership model. Scraper owns private staging/coordinator state; Media owns transforms and durable Media evidence; Catalog owns production catalog mutations and publication receipts; Lifecycle owns physical production deletion. Rebuild the missing slices in their original dependency order so every later reconstruction consumes a verified earlier boundary rather than an approximation.

**Tech Stack:** Go Catalog service, FastAPI/Python Media and Scraper services, PostgreSQL migrations, React/TypeScript admin client, shell/static regression gates, Ripwire, Caveman, RTK, Headroom.

**Spec:** `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md` plus the historical checkpoint/error/fix record captured in this conversation.

## Global Constraints

- Historical hashes after `5ca3f41` are recovery targets/provenance only; new reconstructed commits receive new hashes.
- Never apply the forensic P06.4 stash during normal reconstruction.
- P06.3 real PostgreSQL qualification remains deferred/unexecuted unless a suitable runtime becomes available; source-green is not a DB-runtime pass.
- Preserve existing data/migrations; add forward migrations only.
- No resource-limit increases; no unrelated architecture changes.
- Production publication remains Scraper -> Media evidence -> Catalog mutation.
- Internal publication transport remains private, authenticated, retained-admin authorized, and denied by public gateways.
- After every meaningful reconstructed source+tracker checkpoint: create `git bundle --all`, verify the new HEAD and required refs/stash, build continuation ZIP + SHA-256, persist/replace Library copy, and verify the Library bytes/checksum before reporting **DURABLY CHECKPOINTED**.

---

## Recovery inventory

### Survived and verified

- `5ca3f41` — tracker advanced P06.4 to batch cutover.
- `b7af7fe` — existing-series Scraper publication already converges on Media -> Catalog.
- `54ec3fd` — manual chapter publication already converges on Media -> Catalog.
- P06.3 durability/revision foundation, including `ad0aa0a` / `78b5cf8` event revision work.
- Reference branch `reference/p09.1-scoped-secrets` at `343eda6`.
- Forensic stash `stash@{0}`; do not apply.

### Historical checkpoints whose Git objects were lost

| Historical checkpoint | Historical meaning | Reconstruction status |
|---|---|---|
| `ec273f9` / `753f676` | P06.4 batch publication -> Media -> Catalog | reconstructed as source `b709d03`; durable handoff `ff28fd1` |
| `5466101` / `179af34` | P06.4 new-series chapters -> Media -> Catalog; remove orphan Scraper publisher/transform stack | reconstructed source `8cdfdf4`; handoff/durability checkpoint being advanced by current tracker update |
| `631ddbf` / `b52222a` | P06.4 series/taxonomy/cover mutation -> Catalog; final direct-writer scan | reconstructed source `8ecc4c4`; tracker/durable handoff advancing now |
| `4325575` | P09.1 scoped-secret prerequisite | reconstructed as `0f1fadb` from surviving reference `343eda6`; durable handoff advancing now |
| `c82650a` / `f6a78a8` | P06.5 private transport auth, retained-admin auth, gateway denial, close direct Catalog publish bypass | reconstructed source `581c310`; durable handoff advancing now |
| `2954469` / `8107e66` | P06.6 publication-event revision/dedupe finalization | reconstructed source `d79e340`; handoff advancing to P07.1 |
| `ae6f4c7` / `d9a8417` | P07.1 canonical ingestion-operation convergence | reconstructed source `24adb72`; handoff advancing to P07.2 |
| `cd921e6` / `550cf92` | P07.2 lease/fence and cancel-vs-commit races | reconstructed source `f5c34a7`; tracker/durable handoff is the immediate persistence gate before P07.3 edits |
| `b5ddd8a` / `5b774b7` | P07.3 fenced Stage/Retry repair + cover consolidation; handoff to P07.4 | reconstructed source `6e42f6b`; tracker/durable handoff is the final recovery persistence gate before P07.4 |

### Recovery evidence already checked

- All surviving refs/reflogs/packs inspected.
- `git fsck --full --unreachable --no-reflogs` found no hidden later commits.
- Direct `git cat-file` lookups for all historical target hashes fail in the surviving object database.
- Persistent Library continuation bundle resolves to `5ca3f41`; no later bundle exists.
- Saved WIP source patch predates this work and does not contain P06.4/P07 reconstruction changes.
- Conversation history preserves checkpoint order, changed-file sets for several milestones, RED failures, review findings, exact bug fixes, pass counts, and blocked runtime gates.

---

## Task 0: Establish a durable recovery anchor

**Files:**
- Create: this plan.
- Create: `docs/continuation/RC485-SANDBOX-LOSS-RECOVERY.md`.

**Produces:** A checked-in loss ledger from which recovery can continue without relying on chat prose alone.

- [ ] Record the surviving and lost checkpoint chain.
- [x] Record the persistence root cause and mandatory durability gate.
- [x] Verify repository remains at `5ca3f41` except recovery documentation and the isolated untracked RED batch test.
- [x] Commit the recovery documentation at `3d66594`.
- [x] Generate and verify a fresh all-refs Git bundle + continuation ZIP for `3d66594`.
- [x] Persist it to `/MReader/RC4.85` and re-materialize/verify the Library copy.

## Task 1: Reconstruct historical `ec273f9` batch publication cutover

**Files:**
- Modify: `services/scraper_service/app/publication_bridge.py`
- Modify: `services/scraper_service/app/ingestion.py`
- Modify: `services/scraper_service/app/batch_queue.py`
- Modify: `services/image_service/app/routers/jobs.py`
- Modify: `services/image_service/app/main.py`
- Modify: publication ownership regression/static tests.

**Produces:** Batch uses canonical ingestion authority, streams raw staged pages into a spooled ZIP, submits/reconciles one deterministic Media operation with retained actor identity, and finalizes Scraper state only after Catalog receipt. `process_item()` no longer transforms/writes final pages or calls the legacy Scraper publisher.

- [x] Run recovered batch RED contract and confirm failure is ownership-related.
- [x] Implement retained-actor internal Media submission/status transport and shared public/internal Media core.
- [x] Implement streamed/spooled raw batch archive and deterministic operation reuse.
- [x] Preserve same Media operation after a Catalog receipt if Scraper finalization fails.
- [x] Verify original publication suite + Scraper focused tests + ownership/route/compile/diff + Ripwire quality (78/78 + 18/18; `gating=0`).
- [x] Commit reconstruction at `b709d03` and map it to historical `ec273f9`.
- [x] Update tracker/manifest and durable-persist batch checkpoint at `ff28fd1`.

## Task 2: Reconstruct historical `5466101` new-series chapter cutover

**Files:**
- Modify: `services/scraper_service/app/series_drafts.py`
- Remove only after Ripwire proves no callers: `publication.py`, `draft_image_processor.py`, `tilepack_codec.py`, `events.py`.
- Update ownership/static regressions.

**Produces:** `_publish_one_chapter_commit()` uses ingestion authority -> Media -> Catalog with deterministic chapter operation/fence and retained draft actor. Scraper has no chapter/page production writer or `chapter.published` emitter.

- [x] RED: new-series chapter path still uses legacy publisher/transform/final writes.
- [x] GREEN: route raw staging archive through Media/Catalog and reconcile receipt.
- [x] Prove legacy modules are unreachable before deletion.
- [x] Run publication/Scraper/ownership/route/WebP/RC4.84/direct-writer/compile/diff/quality gates (63/63 + 4/4 + 18/18; Ripwire `gating=0`, preexisting-worse=0).
- [x] Commit reconstructed source at `8cdfdf4`. Tracker commit + durable Library persistence are the immediate handoff gate and must complete before any Task 3 source edit.

## Task 3: Reconstruct historical `631ddbf` P06.4 series/taxonomy/cover ownership

**Produces:** Catalog is sole production authority for series/taxonomy/cover mutations. Media owns cover transform/evidence. Restore `shared.lifecycle` if the public `enqueue_cleanup_job` lazy export still requires it. Final AST/SQL scan shows no Scraper/Media production Catalog-domain writers.

- [x] RED ownership contract for remaining series/taxonomy/cover writers.
- [x] Route mutations through Catalog commands and cover through Media evidence.
- [x] Run dangling shared-export regression and preserve `enqueue_cleanup_job` compatibility.
- [x] Final direct-writer/event scan; fresh gate: 88/88 focused publication/ownership + 4/4 inventory + 18/18 runnable Scraper + ownership/WebP/RC4.84/136-route + compile/gofmt/diff + Ripwire `gating=0`.
- [x] Commit reconstructed source at `8ecc4c4`. Tracker + durable Library persistence are the immediate handoff gate before Task 4 source edits.

## Task 4: Reconstruct P09.1 prerequisite and P06.5 transport auth

**Produces:** Per-workload secret allowlists; independent private Media/Catalog workload credentials; retained-admin reauthorization; `/internal` denied by both gateways; direct Catalog public publish bypass fail-closed; route auditor remains able to classify every private path.

- [x] Reapply/requalify `reference/p09.1-scoped-secrets` rather than inventing alternate secret distribution; reconstructed source `0f1fadb`, 8/8 scope tests + hybrid/static gates + Ripwire `gating=0`.
- [x] RED 7-case auth/denial contract.
- [x] Implement minimal credential graph and upgrade-safe secret generation.
- [x] Keep private Catalog handlers behind `requireInternalWrite`; route audit remains 136/136 and both gateways explicitly deny `/internal`.
- [x] Remove dead `Store.PublishChapter`; keep metadata CRUD.
- [x] Run publication/auth/Scraper/route/ownership/hybrid-secret/format/diff/quality gates: 103/103 + 18/18 + 136/136 routes + Ripwire `gating=0`; blocked runtime checks remain explicit.
- [x] Commit prerequisite separately at `0f1fadb` and P06.5 source at `581c310`; tracker/durable persistence is the immediate handoff gate before Task 5 edits.

## Task 5: Reconstruct historical `2954469` P06.6 event boundary

**Produces:** `CommitPublication` is the sole production caller of `enqueueChapterPublishedTx`; `UpdateChapter` is metadata-only and rejects draft->published; receipt replay happens before event enqueue; notification dedupe is chapter + publication revision.

- [x] RED store-level event-writer/promotion contract reproduced against clean durable `53c1dd6`; GREEN on reconstructed tree.
- [x] Add/restore `ErrPublicationRequiresMedia`; remove `UpdateChapter` publication/event branch.
- [x] Requalify v2 revision + notification dedupe behavior: 98/98 publication/security/authority + 18/18 runnable Scraper + static ownership/route/WebP/sole-writer gates + Ripwire `gating=0`.
- [x] Source committed at `d79e340`; tracker/durable persistence is the immediate handoff gate before Task 6 edits.

## Task 6: Reconstruct historical `ae6f4c7` P07.1 ingestion-operation convergence

**Produces:** Public/manual Media acceptance atomically creates `manual-upload` ingestion header with media operation; internal Scraper calls validate an existing header. Actor/source revision/lease generation/source kind/status/cancel timestamp form one canonical authority decision.

- [x] RED manual-header + internal-validation contract reproduced, then GREEN.
- [x] Shared typed expectation/authority context added without high-arity helper debt; Ripwire `gating=0`.
- [x] Media validates source kind, actor, source revision, lease generation, status and `cancel_requested_at`; Scraper-originated callers carry exact source kind.
- [x] Source committed at `24adb72`; tracker/durable persistence is the immediate handoff gate before Task 7 edits.

## Task 7: Reconstruct historical `cd921e6` P07.2 lease/cancel fences

**Produces:** Stale Scraper takeover advances canonical `lease_generation` under Catalog advisory fence; cancellation uses same operation fence; Media heartbeat/retry/completion/failure mutations are conditioned on claimed `media_generation`; known receipt wins, unknown outcome preserves objects, cancelled work never requeues.

- [x] RED stale-takeover/cancel/Media-generation contracts.
- [x] Prevent stale worker cleanup from deleting deterministic outputs potentially owned by replacement generation.
- [x] Reproduce and guard against historical recursive `_current_ingestion_outcome_tx()` bug.
- [x] Ensure stale batch and series-draft recovery consult canonical cancellation/receipt authority before queue transition.
- [x] Source committed at `f5c34a7`; tracker + durable persistence is the immediate handoff gate before Task 8 edits.

## Task 8: Reconstruct historical `b5ddd8a` P07.3 staging repair + cover consolidation

**Files known from historical commit:**
- `.ripwire_quality_acks`
- `frontend/src/api/client.ts`
- `services/image_service/app/routers/upload.py`
- `services/scraper_service/app/drafts.py`
- `services/scraper_service/app/series_drafts.py`
- `tests/api/helpers.py`
- `tests/api/test_13_media.py`
- `tests/api/test_19_media_events.py`
- Create: `db/migrations/057_scraper_staging_repair_fences.sql`
- Create: `tests/regression/test_p07_3_staging_repair.py`

**Produces:** URL-backed Stage/Retry can repair only missing staging bytes under revision+generation fence; missing manual bytes require re-upload; Preview/Publish remain strict readers; stale recovery advances stage generation; fence-loss cleanup commits before 409; legacy thumbnail convenience endpoint is 202 alias to durable Media job; frontend waits for that job.

- [x] Recreate migration 057 from the recorded historical contract.
- [x] RED P07.3 source contract, including final fence-loss cleanup durability case.
- [x] Implement existing-draft Retry repair and series Stage repair helpers with exact-path generation-specific cleanup.
- [x] Keep Preview/Publish reconstruction-free.
- [x] Delegate thumbnail route; update frontend polling and API helper tests.
- [x] Re-run expanded current gate: 104/104 backend regressions + 18/18 Scraper + ownership/136-route/WebP/compile/diff + Ripwire `gating=0`.
- [x] Record dependency blocks: frontend `node_modules` absent; API integration collection missing `psycopg`; hardening missing `selectolax`; Catalog Go 1.23.2 vs >=1.25.
- [x] Commit reconstruction at `6e42f6b` and map it to historical `b5ddd8a`; tracker handoff maps to historical `5b774b7`.
- [x] **Durably persist and independently verify Library bundle before declaring recovery complete.** First external proof completed at tracker handoff `291cf13`; the final recovery-closure docs commit is repackaged and independently verified before handoff.

## Task 9: Resume P07.4 only after Task 8 is durably checkpointed

No P07.4 production implementation is part of recovery. Recreate its RED contract only after the P07.3-equivalent source state is verified and persisted.
