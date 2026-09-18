# RC4.85 Containerized Diagnostics Module Qualification — 2026-09-18

## Scope

This checkpoint adds a dedicated MReader fault-finding module that launches from one Bash entry point, runs its test workload inside a pinned Docker diagnostics image, captures application/runtime/dependency evidence, sanitizes it, and writes one reusable report bundle for debugging.

Source checkpoint: `7f52ea56269ee8c7a0103a432ec0b0691991ed25`  
Deployment/source-test package: `mreader-rc485-p12.2-source-test-7f52ea5.zip`  
Package SHA-256: `01f509870eab245ed6a2eb3054729d0d2810f93bc3cbcda6f0f544bcfc15c5a7`

## Operator interface

Primary:

```bash
./diagnose-mreader.sh
```

Equivalent:

```bash
./test-mreader.sh --diagnose
```

Modes:

- default / `--full`: canonical 139-route source audit plus the complete non-external API/functionality pytest suite;
- `--quick`: the full source-route audit plus a bounded core API/functionality subset;
- `--external`: explicit opt-in external scraper tests;
- `--keep-test-data`: preserve test data when requested.

## Evidence and reporting contract

The host launcher builds/runs `mreader/diagnostics:1.3.0-rc4.84` and coordinates pre/post evidence capture with the long-lived test container. Failed or timed-out stages are recorded instead of aborting later evidence collection. Stage timeout is represented as exit 124.

Each run writes under `test-results/diagnostics/<run-id>/` with:

- `REPORT.md` and `REPORT.json`;
- `REPORT_BUNDLE.zip`;
- `issues.json`;
- `endpoint-results.tsv`;
- `stages.tsv`;
- pytest/test logs;
- Kubernetes/Docker/runtime snapshots.

Runtime capture covers both MReader namespaces, pod describe/current/previous logs, events, Deployments, Services, HPA/KEDA, bounded Docker/Compose state, and read-only PostgreSQL/RabbitMQ/Valkey/gateway/SeaweedFS health. Raw Kubernetes Secrets and raw Docker environment inspection are excluded. Known credentials, Authorization/Cookie material, database passwords, API keys and token-like values are redacted before bundling.

The analyzer classifies direct evidence for CrashLoopBackOff, OOMKilled, probes, Python import/traceback failures, Go panic/fatal output, PostgreSQL auth/grant/relation failures, DNS/refused/timeout failures, RabbitMQ/Valkey failures, HTTP 5xx, route/test failures and collector failures without inventing a root cause when evidence is insufficient.

## Verification evidence

Fresh exact-source verification on `7f52ea56269ee8c7a0103a432ec0b0691991ed25`:

- diagnostics Python unit suite: **16/16 PASS**;
- diagnostics harness/evidence/dependency snapshot static regressions: **PASS**;
- comprehensive test harness static integration: **PASS**;
- MSYS Docker host/container path regression: **PASS**;
- canonical API source-route audit: **139/139 PASS** — 58 functional, 53 integration, 27 validation, 1 browser-E2E;
- Ripwire changed-surface quality delta after deduplication: **gating=0**;
- full `scripts/validate-current-release.sh`: **PASS**, `VALIDATE_RC=0`; Docker Compose render is intentionally skipped in this sandbox because no configured local `.env`/Docker Desktop runtime is available.

Package qualification:

- deterministic rebuild: byte-identical;
- package checksums: **986/986 PASS**;
- committed Git source bytes: **980/980 exact**;
- committed source file modes: **980/980 exact**;
- extracted-package diagnostics unit/static/source-route regressions: **PASS**.

## Runtime acceptance status

The module is source/package qualified, but a real execution against the user's Windows + Docker Desktop MReader deployment is still required to validate host-side Docker/Kubernetes collection and to generate the first real `REPORT_BUNDLE.zip`. This does not close P11.1-P11.4 runtime/independent-review blockers and does not advance the release lane.
