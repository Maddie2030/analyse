# RC4.85 Cross-Platform Boundary Reliability Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find, prove, fix, and record repository-wide variants of the Windows/Git-Bash ↔ Docker/Linux, host-tool, BusyBox/Alpine, dependency-pin, and initialization/readiness failures uncovered during P12.2 qualification.

**Architecture:** Audit by failure class rather than by service. Each class starts with exhaustive source search + Ripwire impact mapping, promotes only evidence-backed candidates to confirmed findings, adds a RED regression before any production change, applies the smallest shared-boundary fix, and reruns both focused and release-level validation. Findings and non-findings are recorded in one qualification report so future work does not rediscover the same surfaces.

**Tech Stack:** Bash, Git Bash/MSYS/MINGW, Docker Compose, Alpine/BusyBox, Python fallback container, PostgreSQL, Ripwire, Drushti/Caveman/Headroom/RTK, repository regression scripts.

**Spec:** `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md` (P12.2 reliability continuation) plus the 2026-09-17 user request for a broader similar-issue audit.

## Global Constraints

- Preserve the existing Windows-local database-protection root; do not move it to NAS.
- Preserve existing user data and volumes; no destructive restore or volume deletion during audit.
- Keep P08.8/P09.4 restore fencing fail-closed; fix initialization/read boundaries instead of bypassing readiness.
- Do not require host Python or host `jq` for deployment paths that already have container fallbacks.
- Keep Linux container paths protected from MSYS argument rewriting while converting only Windows host paths that Docker must consume.
- Prefer BusyBox/POSIX-compatible shell utilities inside Alpine images; do not add GNU tool packages solely to support avoidable GNU-only flags.
- Keep pinned base-image digests; package revisions inside rolling Alpine repositories may use compatibility floors where exact `-rN` pins are not stable.
- For every production fix: RED → minimum repair → GREEN → affected regressions → release/static validator → focused commit.
- Never apply/pop the forensic stash `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4`.
- After the audit milestone: source commit(s), tracker/evidence commit, fresh `git bundle --all`, package/recovery verification, Library upload, Library read-back.

---

### Task 1: Establish baseline and audit inventory

**Files:**
- Create: `docs/qualification/2026-09-17-rc485-cross-platform-boundary-audit.md`
- Read: `scripts/**`, `deploy/**`, `tests/regression/**`, relevant Dockerfiles and Compose manifests.

**Interfaces:**
- Consumes: restored branch `sequential/p06.4-caller-cutover` and verified P09.4 Windows host-input tree.
- Produces: categorized candidate inventory with exact file/line evidence and disposition (`confirmed`, `covered`, `false-positive`, `blocked-real-host`).

- [x] **Step 1: Record baseline**

Run:
```bash
export PATH="$HOME/.local/bin:$PATH"
Drushti doctor
git status --short
git rev-parse HEAD
git rev-parse refs/stash
```
Expected: clean tree and unchanged forensic stash.

- [x] **Step 2: Build repository maps**

Run:
```bash
ripwire . --report
ripwire . --hotspots --top-k=80
ripwire . --seams
```
Expected: architecture/hotspot/seam evidence saved under `/tmp` for audit triage.

- [x] **Step 3: Create the qualification report with the audit taxonomy and baseline**

Record the five failure classes, commands used, baseline commit, and a findings table. Do not classify a candidate as confirmed until a concrete execution/path contract proves it.

- [x] **Step 4: Commit plan + baseline report shell**

```bash
git add docs/superpowers/plans/2026-09-17-rc485-cross-platform-boundary-audit.md \
        docs/qualification/2026-09-17-rc485-cross-platform-boundary-audit.md
git commit -m "docs: start cross-platform boundary reliability audit"
```

### Task 2: Audit Windows/Git-Bash ↔ Docker/Linux path boundaries

**Files:**
- Inspect: `scripts/**/*.sh`, `deploy/**/*.yml`, `tests/regression/**/*.sh`.
- Test: add/extend targeted regressions only for confirmed uncovered boundaries.

**Interfaces:**
- Consumes: host path forms `C:/...`, `/c/...`, POSIX container paths `/tmp/...` and `/mreader-db-protection/...`.
- Produces: every Docker/Compose/Python boundary either normalized, MSYS-protected, or explicitly proven safe.

- [x] **Step 1: Search every Docker/Compose call that passes path-like arguments**

Run:
```bash
ripwire . --regex='docker( compose)?|docker cp|docker exec|--env-file| -f |/tmp/|/mreader-db-protection|cygpath|MSYS_NO_PATHCONV' --grep-in=any
rg -n 'docker( compose)?|docker cp|docker exec|--env-file|cygpath|MSYS_NO_PATHCONV|[A-Za-z]:/|/c/' scripts deploy tests
```

- [x] **Step 2: Trace each candidate through callers and existing regressions**

Use `ripwire --callers`, `--uses`, and `--affected` for shared helpers such as `python-runtime.sh` and database-protection path resolution.

- [x] **Step 3: For each confirmed uncovered boundary, write a failing Git-Bash/MINGW regression**

The regression must assert both sides: host path becomes Docker-native Windows form, container path remains POSIX and is not MSYS-rewritten.

- [x] **Step 4: Apply the smallest shared-boundary fix and rerun the direct regression plus P09.4/P08.8 when affected**

- [x] **Step 5: Commit each independent path-boundary fix separately**

### Task 3: Audit host runtime/tool assumptions

**Files:**
- Inspect: `scripts/**/*.sh`, Docker entrypoints, validation wrappers, test helpers.

**Interfaces:**
- Consumes: hosts where `python`, `python3`, `jq`, GNU `find`, GNU `sha256sum`, `realpath`, `readlink -f`, `sed -r`, or `date -d` may be absent/different.
- Produces: explicit fallback or portability guarantee for every deployment-critical external tool.

- [x] **Step 1: Inventory direct command requirements**

Run:
```bash
rg -n 'command -v|python3?|\bjq\b|\bfind\b|sha256sum|realpath|readlink|sed |date |stat |mktemp|xargs' scripts tests deploy
ripwire . --external-surface
```

- [x] **Step 2: Separate intentional hard requirements from accidental host dependencies**

Deployment-critical scripts must not rely on a host tool when a canonical container fallback exists. Tests/dev-only utilities may remain explicit requirements if documented.

- [x] **Step 3: RED/GREEN each confirmed accidental dependency and commit independently**

### Task 4: Audit Alpine/BusyBox and container-runtime portability

**Files:**
- Inspect: `deploy/**/Dockerfile*`, `scripts/backup/**`, shell entrypoints copied into Alpine images.

**Interfaces:**
- Consumes: BusyBox `find`, `sha256sum`, `awk`, `sed`, `stat`, Alpine `apk`.
- Produces: no deployment-critical Alpine image path using unsupported GNU-only flags.

- [x] **Step 1: Enumerate Alpine images and copied shell scripts**

Run:
```bash
rg -n '^FROM .*alpine|alpine[0-9.:@-]*|apk add|COPY scripts/' deploy Dockerfile* scripts
```

- [x] **Step 2: Scan copied scripts for GNU-only options**

Run:
```bash
rg -n -- '-printf|--strict|--status|--sort|--version-sort|--parents|--relative|readlink -f|realpath|stat -c|date -d|sed -r|grep -P|xargs -r' scripts deploy
```

- [x] **Step 3: Reproduce confirmed cases using BusyBox binaries where available, then make them portable**

- [x] **Step 4: Run backup/recovery catalog, pre-upgrade, and image static regressions**

### Task 5: Audit dependency pins and image build stability

**Files:**
- Inspect: Dockerfiles, Compose image tags/digests, `tests/regression/dependency-pins.sh`.

**Interfaces:**
- Consumes: immutable image digests and rolling package repositories.
- Produces: stable dependency policy that catches unpinned images without exact-pinning rolling `apk` revisions that disappear.

- [x] **Step 1: Search exact `apk` revision pins and mutable container tags**

```bash
rg -n 'apk add[^\n]*=|[a-z0-9._/-]+:[^ @"'"']+( |$)|image:' deploy scripts .github azure-pipelines*.yml 2>/dev/null || true
```

- [x] **Step 2: Cross-check every candidate against `dependency-pins.sh` policy**

- [x] **Step 3: RED/GREEN any policy hole; keep base digest pinning and compatibility floors for rolling Alpine packages**

### Task 6: Audit initialization/readiness sequencing and generated-state ownership

**Files:**
- Inspect: `scripts/bootstrap.sh`, `scripts/preflight.sh`, `scripts/hybrid/{validate,stateful-up,deploy}.sh`, migrations and readiness scripts.

**Interfaces:**
- Consumes: first initialization, repeated bootstrap, existing data, restore generation/fingerprint, migration state.
- Produces: every readiness prerequisite has an earlier idempotent producer; no readiness check requires state that only a later phase creates.

- [x] **Step 1: Map bootstrap/preflight/validate/stateful/deploy order**

Use Ripwire path/caller maps plus direct shell inspection.

- [x] **Step 2: Enumerate readiness inputs and their producers**

For every control file/table/marker read by readiness, record where it is created, whether first-run creation is idempotent, and whether mismatch behavior remains fail-closed.

- [x] **Step 3: Add ordering/first-run regressions for confirmed producer-before-consumer gaps**

- [x] **Step 4: Apply minimum sequencing fixes and rerun P08.8/P09.4 plus bootstrap/stateful regressions**

### Task 7: Record results, verify release surface, and durable-checkpoint

**Files:**
- Update: `docs/qualification/2026-09-17-rc485-cross-platform-boundary-audit.md`
- Update: `docs/continuation/RC485-CONTINUATION-MANIFEST.md`
- Update: `docs/continuation/RC485-NEXT-CHAT-P11.4.md`
- Update: `docs/qualification/RC485-CAPABILITY-MATRIX.md`
- Update: `docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`

**Interfaces:**
- Consumes: all confirmed findings/fixes and verification logs.
- Produces: auditable finding ledger, exact source/tracker commits, deterministic deployment ZIP, all-refs recovery ZIP, verified Library copies.

- [x] **Step 1: Run final verification**

```bash
bash -n $(git ls-files 'scripts/*.sh' 'scripts/**/*.sh' 'tests/regression/*.sh')
git diff --check
./scripts/validate-current-release.sh
ripwire . --quality-delta
ripwire . --test-gate
```
Run all directly affected regression suites identified during Tasks 2–6.

- [x] **Step 2: Record every candidate disposition**

The audit report must include confirmed fixes, already-covered safe patterns, false positives, and real-host-only gates.

- [x] **Step 3: Commit tracker/evidence**

- [x] **Step 4: Generate exact-source deployment ZIP and verify committed-tree identity + internal checksums + deterministic rebuild**

- [x] **Step 5: Generate `git bundle --all` recovery ZIP and verify exact HEAD, source ancestor, all refs, stash, internal checksums, and clean restore**

- [x] **Step 6: Upload package/recovery/docs to `/MReader/RC4.85`, rematerialize, and independently verify Library bytes before declaring the milestone durable**
