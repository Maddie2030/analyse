# RC4.85 next chat — P11.4 independent review remains blocked

## Resume authority

- branch: `sequential/p06.4-caller-cutover`
- canonical workspace: `/mnt/data/mreader-rc485-repo`
- P11.4 source/test checkpoint: `ed53fc51c96b299427781f4b2564911accba7c97`
- P12.2 current cross-platform reliability source: `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6`
- P03.2 browser acceptance source coverage: `d7fd2948f64920a8851780e64d94de6a795c6c7a` — five required Playwright scenarios present; real execution/independent review still open
- P12.2 prior initialization/readiness source: `4fbd847af7ae6f7a2f0bd8704ae34bc272fc8f4f`
- P12.2 prior Git-Bash pre-upgrade container-path repair source: `c4bf03f1238f47faafaecff59705a9e44ced717d`
- P12.2 prior Git-Bash fresh-env fixture repair source: `3020fc30bbbf1bd8fd7e89ce31145847469710c9`
- P12.2 prior stale-Git-Bash recovery-root repair source: `f12f26188b4c08d904b52ff1cadbe8bdab929ecb`
- P12.2 prior dedicated Windows recovery-root source: `1a682bb0a7d96af50fecb54cb77cbf13876dadcb`
- P12.2 prior Git Bash recovery-root hardening source: `1d17ce50604001f8e6462c8492ccc9582353f4a5`
- P12.2 prior Git Bash bootstrap repair source: `6f32a597951bf3c5516389a86e3ad5b3064ad677`
- P12.2 prior no-host-Python repair source: `3397e5c7ab5a30c315d9bc606c30be6d07076a78`
- P11.3 durability-closure tracker: `00e35924ca5dfe34358c4348cea43f656e7a230e`
- P11.3 source/test checkpoint: `a88e275294931fa70c875c34c0f3cb35af8826fe`
- forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — never apply/pop normally

## Current state

P11.4's available source/release-integration review has been executed. Two stale regression assertions were repaired without changing production behavior:

1. Android Smart Library static audit now checks the current Progress-owned/user-scoped `reading_state_v1` query contract instead of retired contiguous SQL text.
2. PostgreSQL backup dependency-pin regression no longer requires retired `curl`; it checks the exact current Alpine install line.

Fresh evidence at the P11.4 source/test checkpoint includes:

- Web reading repository 31/31;
- Android reading/origin source 8/8 plus full Android static audit;
- migration/quiescence/reconciliation/pre-upgrade 21/21 plus ordering;
- P09 ownership/security/readiness source fences 34/34 + 28/28;
- P10 truthfulness/race source fences 50/50;
- API ownership and 139/139 route coverage;
- resource/pressure guards;
- exact current-release validator PASS on its dependency-light/source path;
- Ripwire `untested=0`, with its one changed-test obligation executed green.

Canonical evidence:

1. `docs/qualification/2026-09-17-rc485-p11.4-release-integration-review.md`
2. `docs/qualification/2026-09-17-rc485-p11.4-release-integration-matrix.tsv`

## What is still blocked

P11.4 requires genuinely independent review. The tracker forbids counting self-review as independent, and this sandbox exposes no separate reviewer/subagent integration. Web P03.2, Android P04.2, migration P05.5 independent review and therefore P11.4 final review acceptance remain **BLOCKED**.

P11.1, P11.2 and P11.3 runtime gates also remain **BLOCKED for release acceptance**. Docker, kubectl, psql and k6 are absent; frontend `node_modules`, the Android Gradle wrapper and several Python runtime dependencies are unavailable; local Go is 1.23.2 rather than the required 1.25.

## Next action

Run the Web, Android and migration review through a genuinely separate reviewer/subagent in an environment that provides one, attach its findings to the exact integrated checkpoint, and address any Critical/Important findings with normal RED→GREEN discipline. Do not mark P11.4 complete from self-review alone.

After independent review is closed, the remaining P11.1-P11.3 runtime acceptance debt must still be executed in an authorized environment before P12.3/final release qualification.

Maintain the mandatory source + tracker + all-refs bundle + Library round-trip durability checkpoint after every meaningful milestone. Do not apply/pop the forensic stash.


## P12.2 test/deployment artifact now available

Current deployment-test authority is `mreader-rc485-p12.2-source-test-c4bf03f.zip` from exact clean source `c4bf03f1238f47faafaecff59705a9e44ced717d` with ZIP SHA-256 `7fd19bd2eb14be605139ed70e424d4b44f921cb3338da7e095a649fc138bb21f`. It supersedes `3020fc3` for Windows/Git-Bash testing. The latest real-host failure was caused by MSYS rewriting Linux container `/tmp/preupgrade-*` arguments passed to native `docker.exe` into Windows host temp paths before `docker exec`; PostgreSQL inside the Linux container therefore received a non-existent `C:/Users/.../AppData/Local/Temp/...` destination. The pre-upgrade capture now uses `MSYS_NO_PATHCONV=1` on capture, copy, and cleanup Docker commands carrying container paths. Focused backup tests are 6/6 green and the adjacent hybrid/MSYS/volume regressions pass. Package integrity: 945 checksum entries verify, all 941 committed files match Git archive bytes, deterministic rebuild is byte-identical. P11 runtime and independent-review blockers remain open.

### 2026-09-17 initialization pre-upgrade backup bypass

Current P12.2 source checkpoint: `2b199295cc308fca764c7c2ce268e0a5d84fd8fb`. For explicit initialization/testing only, `MREADER_SKIP_PREUPGRADE_BACKUP=true` skips the mandatory pre-upgrade PostgreSQL bundle; safe default remains `false`. Current deployment ZIP: `mreader-rc485-p12.2-source-test-2b19929.zip`, SHA-256 `f4613bd0aab8448a0d2894aa46a95e7407a58cc96f8c9a214a1070297642708e`. Verification: bypass contract PASS, original ordering PASS, local pre-upgrade backup suite 6/6 PASS, current-release source/static validator PASS.


### 2026-09-17 pre-upgrade host-jq fallback

Current deployment-test authority is `mreader-rc485-p12.2-source-test-c9dde2b.zip` from exact clean source `c9dde2b278cda2d67e3ad672d3935fdd06e7a045` with ZIP SHA-256 `2c3a04da5f8d17a8e985b19a646de970ef5e0250a73b10c1d11670911533a28b`. The prior `jq` failure occurred after PostgreSQL capture succeeded: host-side canonical recovery validation required `jq`. The pre-upgrade script now falls back to the same recovery-store validator inside the `backup_agent` image when host `jq` is unavailable. Fail-closed validation, the existing `/mreader-db-protection` bind mount, and Git-Bash `MSYS_NO_PATHCONV=1` protections are preserved. Focused backup suite is 7/7 green, including a no-host-jq regression.

## Current Windows pre-upgrade recovery-path repair

Current deployment-test authority is `mreader-rc485-p12.2-source-test-8b1415a.zip` from exact clean source `8b1415a8c330816e459ad5e7c29b73336961a105` with ZIP SHA-256 `101f879451a6b455516fce679ecb3b35e9033a4c19366ac0d87749d2a09be51b`. The previous `c9dde2b` fallback correctly protected Linux container paths with `MSYS_NO_PATHCONV=1`, but also left `/c/Users/...` host paths unconverted; Docker Compose then interpreted them as `C:\c\Users\...`. The current source preconverts only host `.env`/Compose paths to `C:/...`, preserving container paths and canonical recovery validation. Focused pre-upgrade suite is 8/8 green.

## Latest P12.2 real-host backup-agent image repair — 2026-09-17

Current deployment-test source is `ac7bccc8cf5043584b9d7260055d38463bae448f`; package `mreader-rc485-p12.2-source-test-ac7bccc.zip`, SHA-256 `60323704899eae4d2bb5ce7f3497f76ba2855490d3857cf1ff5b45c8d2b994b7`. The backup-agent Dockerfile no longer exact-pins mutable Alpine `-rN` package revisions; it uses explicit minimum-compatible constraints while retaining the digest-pinned base image. The real-host image build still needs execution on Docker Desktop.

## 2026-09-17 P12.2 BusyBox recovery portability repair

Current deployment-test source is `9793fed4a7b5f9e47a5b3950826e6bfae1aa8e4c`; package `mreader-rc485-p12.2-source-test-9793fed.zip`, SHA-256 `b41ea719b95f54f773fa56988bcc41388e1075a5e378af2db7e67d574aa540fa`. Real-host recovery validation then exposed Windows/GNU binary checksum markers (`*filename`) and GNU-only `sha256sum --strict --status` assumptions inside the Alpine fallback. Canonical validation now normalizes only the optional binary marker before exact allowlist/duplicate checks and verifies with portable `sha256sum -c`. Local recovery catalog 10/10 PASS, local pre-upgrade suite 8/8 PASS, BusyBox/Windows checksum regression PASS, current-release source/static validator PASS. P11 blockers remain unchanged.


## 2026-09-17 P12.2 initial restore-generation seed

Current deployment-test source is `4fbd847af7ae6f7a2f0bd8704ae34bc272fc8f4f`; package `mreader-rc485-p12.2-source-test-4fbd847.zip`, SHA-256 `8358d123386461c60ed3e0287deb327c294737b692fd0439867fa695e89da557`. Real-host bootstrap progressed to P09.4 and exposed a fresh-install contract gap: migration 060 creates the restore mirror at empty/0, but no host control/generation was seeded before readiness. The backup agent now initializes generation 1 only against that migration-default mirror, is idempotent for an exact match, and fails closed for any other state. Focused P08.8/P09.4 suite is 39/39 PASS.

## 2026-09-17 P12.2 cross-platform boundary audit closure

Current deployment-test authority is `mreader-rc485-p12.2-source-test-a7d7a40.zip` from exact source `a7d7a40b55660f3f19f73adc5d0895ba6b6b19c6`, SHA-256 `907c7bc1f1bf88c4ae94786584d8f31fc99ec86dfa3074f0dc6ce4ca9b62a007`. The broader audit covered Windows/Git-Bash/MSYS Docker path boundaries, accidental host `jq`/Python dependencies, BusyBox/Alpine portability, rolling Alpine package revision pins, and first-run readiness sequencing. Confirmed repairs: shared MSYS Docker path helper; no-host-`jq` PostgreSQL restore CLI; host-tool-free P09.4 runtime JSON path; containerized catalog recovery-store access; compatibility floors across active Alpine service/diagnostics images. Final source/static evidence: combined P08.6/P08.7/P08.8/P09.4 **49/49 PASS**, local pre-upgrade **8/8 PASS**, both MSYS regressions PASS, initialization/pre-upgrade ordering PASS, backup-agent/dependency/Dockerfile static gates PASS, current-release validator PASS. Package integrity: **955/955 committed files exact**, **958/958 internal checksums**, deterministic rebuild byte-identical. Live Docker/Kubernetes gates remain real-host blockers in this sandbox; P11 acceptance blockers remain unchanged.

## P03.2 browser source coverage update

Source `d7fd294` adds the five previously missing browser acceptance scenarios and validator enforcement. Do not mark P03.2 or P11.4 complete: real Playwright execution and genuinely independent review are still required.

P03.2 package authority: `mreader-rc485-p12.2-source-test-d7fd294.zip`, exact source `d7fd2948f64920a8851780e64d94de6a795c6c7a`, SHA-256 `12e37a434d9f2cd2e824d4ebee174563da57ba23b091c18b0df9c4ae25e22e51`; 957/957 committed files exact, 959/959 package checksum entries, deterministic rebuild byte-identical. Real Playwright execution and independent review remain open.

## Latest P12.2 Windows drive-form Python host-input repair — 2026-09-17

Use source `b80c030327e16a9e05dfd7b979a5b5ee668ce2de` and package `mreader-rc485-p12.2-source-test-b80c030.zip` (SHA-256 `afe1cd9030ee64602a6840714af54bff1e083f204e15bca1499d1324d1e26ebc`) for the next Windows/Docker Desktop rerun. The no-host-Python regression now models a drive path portably, and `python-runtime.sh` resolves drive-form host inputs through `cygpath -u` before bind-mounting them into the fallback Python container. Package verification: 960/960 exact Git files, 967/967 checksums, deterministic rebuild. P11 runtime/independent-review blockers remain open.

## 2026-09-17 P12.2 application crash-loop repair

Current deployment-test source is `4cd61f40019f84c90b491af52cdc69155c6efcce`. It fixes the real-host CrashLoopBackOff set (`auth-service`, `auth-admin`, `image-service`, `progress-go`) by normalizing Python async SQLAlchemy DSNs to `postgresql+asyncpg://` at the shared runtime boundary and granting `progress_runtime` read access to canonical `reading_state_v1`. Use `mreader-rc485-p12.2-source-test-4cd61f4.zip` (SHA-256 `93fa31dfca130aa772923ad7d1b06a27861037367cfda32eb426cf98c0cdd8e8`) for the next Windows/Docker Desktop rerun. Source/package gates are green; real-host observation of those four pods returning to `Running 1/1` is still required. Preserve forensic stash `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` and all P11 blockers.

## Latest real-host deployment follow-up — image-service import cycle

Use deployment-test source `d0558300318c422853c50904b003aaa9067364fe` / package `mreader-rc485-p12.2-source-test-d055830.zip` (SHA-256 `68e60f6b02a0a6dc750bb5fb49e171d62fb0b8b1a1567684b90c2c71c070213c`). This supersedes `4cd61f4` for Windows/Docker reruns.

The real-host failure was not a probe/DB issue: Uvicorn exited 1 on a `jobs.py -> upload.py -> jobs.py` circular import, with a missing `IMAGE_MIME_TYPES` definition latent behind it. Shared media validation now lives in neutral `app.media_validation`; `jobs.py` no longer imports `upload.py`.

Next host gate: deploy `d055830` and confirm `mreader-admin/image-service` reaches `1/1 Running`. If it still crashes, collect `kubectl logs -n mreader-admin <image-service-pod> --previous --timestamps` before changing source. Do not relax probes or resource limits to mask startup errors.

## 2026-09-18 diagnostics module continuation note

A dedicated containerized diagnostics module is now source/package-qualified at `7f52ea56269ee8c7a0103a432ec0b0691991ed25`. Use `./diagnose-mreader.sh` for the first real Windows/Docker Desktop run (`--quick` for bounded triage). The resulting `test-results/diagnostics/<run-id>/REPORT_BUNDLE.zip`, `REPORT.md` and `issues.json` should become the primary evidence for subsequent runtime fixes. Package authority: `mreader-rc485-p12.2-source-test-7f52ea5.zip` SHA-256 `01f509870eab245ed6a2eb3054729d0d2810f93bc3cbcda6f0f544bcfc15c5a7`. This does not close P11 runtime or independent-review acceptance.

## P12.3 diagnostic authority update — 2026-09-18

Use source `571190a4d5553ecaa57b92ef7df1c8255dafe1e5` and package `mreader-rc485-p12.3-source-test-571190a.zip` (SHA-256 `144edffbd96f449dfb56cd3ce5d4779c1f8ecfcb0289c4947b29faf9a218351e`). The next runtime step is to run `./diagnose-mreader.sh` on the real Docker Desktop hybrid stack. Add real fixture flags only when available; omitted fixtures are reported as skipped. Use the resulting `REPORT_BUNDLE.zip` to repair the genuine runtime failures, especially PostgreSQL grant errors, without relying on the false OOM/probe/RabbitMQ classifications from the earlier report.

## P12.4 Graphify development-reference authority — 2026-09-18

Use source `887e0ec99e806f45416e84df13bb44960b6480f0` and package `mreader-rc485-p12.4-source-test-887e0ec.zip` (SHA-256 `50706c81f353cf225f0afb01fc9cc1e94a5e03056c043cbed2c2a88335e176c1`). The package contains checkpoint-matched `graphify-out/graph.json` plus the deeper `development-reference/` evidence directory. Start future debugging with `export PATH="$HOME/.local/bin:$PATH"`, `Drushti doctor`, then `Drushti continue .`; Graphify should report the existing project graph and can be queried immediately. Regenerate the reference after architectural/ownership changes with `./scripts/development-reference/build-reference.sh --out development-reference --checkpoint "$(git rev-parse HEAD)" --install-project-graph`. Preserve the P11 runtime and independent-review blockers; Graphify/Ripwire evidence guides impact/testing but does not waive those gates.

## 2026-09-18 P12.5 runtime-repair continuation

Current repaired source is `f6a2c14aeace8c9f16d08fb28f91063120a483ac`, package `mreader-rc485-p12.5-source-test-f6a2c14.zip`, SHA-256 `009c1af914d2fcb34d19bd6549cb60c12e46d5cb99c7f574a99f92f05ae00279`. On the real Windows/Docker Desktop host, run `./hybrid-up.sh` first to reconcile database roles, then `./diagnose-mreader.sh` and return the new report bundle. Use the packaged Graphify map plus Ripwire to localize any remaining actor/browser failures. Do not claim P11 release qualification from source/static evidence alone.

### P12.6 no-host-Python Graphify reference repair — 2026-09-18

- Source `7bea1fc6817a6560b45bc30f8e76d3233dd76622` removes direct host-Python calls from the Graphify/development-reference shell path and uses the shared Docker-capable Python runtime.
- Package `mreader-rc485-p12.6-source-test-7bea1fc.zip`, SHA-256 `3ecaaa9753d2bec5e9cd66dbc85245c66eb001c45f4b43760d943323fa9dba5d`.
- Verification: no-host-Python PASS; development-reference 4/4 + static PASS; 139/139 route audit; release validator PASS; Ripwire gating=0; package 1,036/1,036 checksums and 1,003/1,003 Git files/modes exact.
- Real host must rerun `./scripts/bootstrap.sh`, `./hybrid-up.sh`, then `./diagnose-mreader.sh`.
- P11 runtime/independent-review gates remain open.

## P12.7 diagnostic authority — 2026-09-18

Use source `a081944a335c899223d057dead9c0803c8887bf0` and package `mreader-rc485-p12.7-source-test-a081944.zip` (SHA-256 `928de38d6fb2e3b033bfa3f2950682bc9b410e2dc38c415e10ffe1b54cafef46`). Run `./scripts/bootstrap.sh`, `./hybrid-up.sh`, then `./diagnose-mreader.sh` on the real Windows/Docker Desktop stack. Interpret the report in layer order: permissions -> boundary -> API -> actor/browser. The first two layers contain 1,104 architecture checks and are designed to expose permission/CORS/routing/service-boundary causes before downstream 500/503 cascades. Preserve all P11 runtime/independent-review blockers.
