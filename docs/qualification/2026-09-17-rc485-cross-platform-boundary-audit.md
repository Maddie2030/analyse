# RC4.85 Cross-Platform Boundary Reliability Audit

Date: 2026-09-17
Branch: `sequential/p06.4-caller-cutover`
Audit baseline after sandbox recovery: `ec517c3e97bc78d402d6538258ea0c2b4a7322e9`
Recovered source content authority: exact tracked-tree bytes from prior verified package `58fa0274edde171e62a643897df1311bc01e4906`; the original Git object was absent from the last durable bundle, so the two-file delta was restored and recommitted as `ec517c3`.
Forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — preserved; never apply/pop.

## Purpose

After a sequence of real Windows/Git-Bash failures exposed one boundary defect at a time, this audit searches active RC4.85 source repository-wide for the same classes instead of waiting for another host bootstrap/recovery run to discover them serially.

Historical `reference/imports/**` copies are excluded unless active source executes/imports them. Search counts are candidate inventory only; a finding is confirmed only after tracing or reproducing the execution contract.

## Failure classes

1. Windows/Git-Bash/MSYS ↔ Docker/Linux path conversion.
2. Accidental host runtime/tool assumptions (`python`, `jq`, GNU utilities).
3. Alpine/BusyBox command portability.
4. Rolling Alpine `apk` revision pins and image-build stability.
5. Initialization/readiness generated-state producer/consumer ordering.

## Baseline evidence

- `Drushti doctor`: Superpowers active; Ripwire, Caveman, Headroom and RTK probe successfully.
- Ripwire baseline: 763 files, 7605 symbols, 5910 edges; `scripts/backup/backup-agent.sh` is a high-maintenance hotspot.
- Candidate inventories under `/mnt/data/mreader-audit-logs/` covered path/Docker boundaries, host tools, GNU-sensitive commands, image/package declarations, and readiness/generated state.
- Canonical deployment target remains Windows + Git Bash + Docker Desktop/Kubernetes, with PostgreSQL/Valkey/RabbitMQ/Image Edge in Compose and SeaweedFS on the external NAS.

## Reference incidents that defined the audit

| Incident | Root cause | Repair pattern |
|---|---|---|
| pre-upgrade `pg_dump` received `C:/Users/.../Temp/...` inside Linux container | MSYS rewrote `/tmp/...` | disable MSYS conversion on container-only path arguments |
| fallback Compose path became `C:\\c\\Users...` | path conversion disabled for host paths too | pre-convert host paths, then protect Linux container paths |
| backup-agent image stopped building | exact Alpine `-rN` package revision disappeared | compatibility floors on rolling `apk` packages |
| recovery validator failed on `find -printf` | BusyBox `find` lacks GNU `-printf` | `-print0` + shell basename handling |
| recovery validator rejected Windows checksum entries | GNU/Windows `sha256sum` may emit `*filename`; BusyBox lacks GNU check flags | normalize marker + portable `sha256sum -c` |
| P09.4 fresh initialization had no restore generation | readiness ran before initial state producer | idempotent restore-state initialization after migration |
| P09.4 could not read existing `C:/.../restore-control.json` without host Python | Docker-Python fallback forwarded a Windows path literally into Linux | shared runtime bind-mounts drive-form external files |

## Final findings ledger

Status values: `FIXED`, `COVERED`, `INTENTIONAL`, `CANDIDATE`, `REAL-HOST-GATE`.

| ID | Status | Severity | Surface | Evidence / disposition |
|---|---|---:|---|---|
| XP-01 | **FIXED** | High | `scripts/recovery/catalog-restore.sh` | Raw Docker `run/create/exec/cp` boundaries carried Linux container paths. Commit `b8051e6` introduced `scripts/docker/msys-paths.sh`; container-only arguments are MSYS-protected and mixed copy operations pre-convert only the host side. |
| XP-02 | **FIXED** | Medium | `scripts/tests/test-runner-common.sh::test_copy_results` | Mixed container-source/host-destination `docker cp` now uses the same helper. Simulated MINGW regression proves `/results/.` remains container-native while the host destination is converted. |
| XP-03 | **COVERED** | — | `scripts/hybrid/create-local-preupgrade-backup.sh` | Existing dedicated MINGW regressions cover Linux `/tmp` paths, Windows host Compose/env paths, and `/mreader-db-protection` fallback mounts. |
| XP-04 | **COVERED** | — | `scripts/hybrid/python-runtime.sh` | Recovered `58fa027` behavior binds Windows drive-form external input files into the Linux Python fallback; P09.4 control-file reads are covered by 18 readiness tests. |
| XP-05 | **COVERED** | — | raw `docker run -v` sites in volume inspection/adoption/staging tests | Remaining audited `-v` sources are Docker named volumes, not host filesystem paths, so no drive-path conversion is involved. |
| HT-01 | **FIXED** | High | `scripts/backup/postgres-restore.sh` | Commit `9252647` removes host `jq`; restore-request JSON is parsed through the shared Python runtime, retaining Docker fallback when host Python is absent. |
| HT-02 | **FIXED** | Medium | `scripts/test/p09-4-runtime-gate.sh` | Commit `817f0b0` removes false host `python`/`jq` prerequisites and uses the shared runtime for JSON handling. |
| HT-03 | **FIXED** | High | `scripts/recovery/catalog-restore.sh` | Commit `06f52c0` moves canonical recovery-store operations into the backup-agent runtime and parses returned JSON through the shared Python runtime; Windows host no longer needs recovery-store `jq/coreutils`. |
| HT-04 | **INTENTIONAL** | — | `scripts/backup/sync-local-recovery-catalog.sh` | Requires `jq`, `psql`, `sha256sum`, `mktemp`, but is copied/executed only inside the backup-agent image where these capabilities are provisioned. |
| HT-05 | **INTENTIONAL** | — | `scripts/storage/nas-verify-standalone.sh`, `ops/nas-seaweedfs/storage-contract.sh` | These scripts deliberately execute on the Ubuntu NAS and verify NAS-host `docker/findmnt/curl/jq/awk` prerequisites before publishing storage proof. They are not Windows deployment-host requirements. |
| HT-06 | **INTENTIONAL** | — | `scripts/ci/release-audit.sh` | `jq` is an explicit CI runner prerequisite only when the optional Azure release-audit satellite is configured; it is not invoked by local deployment. |
| BP-01 | **COVERED** | — | backup-agent/recovery-store | BusyBox `find` and `sha256sum` incompatibilities have explicit regression coverage. Remaining `realpath/stat/date/sort` uses are backed by `coreutils` installed in the image. |
| BP-02 | **COVERED** | — | `ops/migrate/**` | Alpine migration entrypoints contain no audited GNU-only option (`-printf`, GNU-only checksum flags, `grep -P`, `sed -r`, `date -d`, etc.). |
| BP-03 | **COVERED** | — | host validation scripts using GNU `find/stat` | Canonical local host is Git Bash or Linux, both within the supported GNU-tool contract. These commands are not copied into BusyBox-only images. |
| AP-01 | **FIXED** | High | six Go runtime images + diagnostics image | Commit `dac4985` replaces exact Alpine `package=x.y.z-rN` pins with explicit `>=` compatibility floors and updates `dependency-pins.sh` so future `apk` additions cannot reintroduce exact mutable revisions. |
| IM-01 | **CANDIDATE** | Low | exact patch-tagged base/runtime images without digests | Several service Dockerfiles use patch-exact tags (for example `alpine:3.22.1`, `golang:1.25.0-alpine3.22`) rather than digests. Existing policy rejects floating/broad tags but does not require digests universally. No real-host failure was observed from this class; converting all images to registry digests should be a separate supply-chain/reproducibility unit with registry verification. |
| IO-01 | **COVERED** | — | restore-generation initialization | Migration creates the mirror; `stateful-up.sh` then runs `initialize-restore-state` after migration + role reconciliation. Real-host diagnostic proved host control and DB mirror agree at positive generation. |
| IO-02 | **COVERED** | — | deploy readiness ordering | `deploy.sh` invokes `stateful-up.sh core`, data-path check, then P09.4 readiness, and only after the readiness token exists does it render/apply DB workload manifests. No second consumer-before-producer gap was found. |
| RG-01 | **REAL-HOST-GATE** | — | full Docker/Kubernetes execution | Sandbox has no Docker daemon/kubectl runtime, so image builds, Compose rendering, live Docker/NAS/Kubernetes paths remain real-host verification gates. Static/source regressions are not counted as runtime passes. |

## Fix commits produced by this audit

- `b8051e6` — `fix(recovery): harden Docker paths for Git Bash`
- `9252647` — `fix(recovery): remove host jq from restore CLI`
- `817f0b0` — `test(p09.4): remove host json tool prerequisites`
- `06f52c0` — `fix(recovery): containerize catalog recovery store access`
- `dac4985` — `fix(images): avoid mutable Alpine package revisions`

The recovered P09.4 drive-path runtime behavior from original source `58fa027` is represented in this restored repository by `ec517c3`.

## Alpine package policy after AP-01

Active Alpine `apk add` packages now use minimum-compatible constraints rather than exact repository revisions. Examples:

- service runtimes: `ca-certificates>=20260611`, `wget>=1.25.0`;
- diagnostics: floors for Bash, Python, YAML, Node/npm, ripgrep, Git, coreutils, grep, sed and findutils;
- backup-agent: existing floors for Bash, jq, coreutils and tzdata.

`tests/regression/dependency-pins.sh` now enforces compatibility floors for every `apk add` token and still enforces exact Debian/Ubuntu `apt-get install` versions under the existing policy.

## Readiness input → producer map

| Readiness input | Consumer | Producer / owner | First-run behavior |
|---|---|---|---|
| `.env` + PostgreSQL bootstrap user/database | P09.4 shell | `bootstrap.sh` / env reconciliation | created before preflight/stateful work |
| PostgreSQL migrations | P09.4 SQL | migration container in `stateful-up.sh` | applied before readiness |
| restrictive runtime roles/DSNs | P09.4 role verification + deploy secrets | `reconcile-postgres-roles.sh` | reconciled after migration, before readiness |
| `control/restore-control.json` | P09.4 metadata | backup-agent `initialize-restore-state` | generation 1 is seeded idempotently on first initialization |
| `database_restore_state` mirror | P09.4 SQL | migration + `initialize-restore-state` | empty/0 migration default becomes exact host generation; mismatches fail closed |
| absence of unresolved restore cutover journal | P09.4 shell | restore engine journal lifecycle | unresolved marker deliberately blocks deploy |
| deployment generation token | manifest renderer | P09.4 readiness | generated only after all above checks pass |

No additional producer-before-consumer gap was confirmed.

## Verification evidence

Final audit verification before source closure:

- simulated MINGW mixed host/container path regression: **PASS**;
- existing MSYS container-path regression: **PASS**;
- combined P08.6 + P08.7 + P08.8 + P09.4 Python suites: **49/49 PASS**;
- mandatory local pre-upgrade suite: **8/8 PASS**;
- restore-generation initialization ordering: **PASS**;
- pre-upgrade backup ordering: **PASS**;
- backup-agent static regression: **PASS**;
- Alpine dependency policy: **RED before AP-01, PASS after repair**;
- Dockerfile static regression: **PASS**;
- `git diff --check`: **PASS**;
- `scripts/validate-current-release.sh`: **PASS** on the complete available source/static path; Docker Compose rendering is explicitly skipped because Docker is unavailable in this sandbox;
- Ripwire PR-context/test-gate reviewed the indexed shell/Python blast radius. Direct named shell obligations `scripts/tests/test-runner-common.sh`, `scripts/tests/load-runner-common.sh`, and `tests/regression/staging-volume-permissions.sh` are **PASS**;
- authorized P09.4 live runtime gate stops at `docker is required`, which is recorded as `RG-01`, not a pass;
- Caveman reports no independent-agent backend (`codex`, `claude`, `gemini`, etc. unavailable), so no self-review is labeled independent review;
- Headroom probe could not download its optional `scc` helper because network/DNS was unavailable; this does not affect repository qualification;
- RTK compatibility execution of `git diff --check` completed without error.

## Residual recommendations

1. Treat IM-01 digest pinning as a separate reproducibility/supply-chain unit rather than mixing registry digest changes into this portability audit.
2. Keep NAS host prerequisites explicit in NAS installation documentation; do not silently shift NAS verification into application containers because `findmnt` must inspect the actual NAS host mount topology.
3. Preserve the shared MSYS path helper and shared Python runtime as the only supported cross-boundary primitives; new scripts should not reimplement ad-hoc path conversion or host JSON parsing.
4. Real-host bootstrap should be rerun from the final package to exercise Docker image builds and P09.4 end-to-end after this audit.

## Durability closure

The verified deployment ZIP was uploaded to persistent ChatGPT Library under `/MReader/RC4.85`, then rematerialized and compared byte-for-byte with the local verified artifact. The Library copy retained SHA-256 `907c7bc1f1bf88c4ae94786584d8f31fc99ec86dfa3074f0dc6ce4ca9b62a007` and all **958/958** package checksums passed.

The all-refs continuation recovery ZIP was likewise uploaded/rematerialized and restored into a fresh Git repository. The read-back copy restored the exact tracker checkpoint used for the verification cycle, all **17 refs**, the untouched forensic stash `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4`, source checkpoint `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6` as an ancestor, all **14/14** recovery checksums, and a clean checkout. A final tracker-only closure commit follows this evidence and therefore requires one final regenerated rolling recovery bundle before milestone completion.
