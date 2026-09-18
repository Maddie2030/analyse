# MReader Containerized Diagnostics Design

## Goal

Provide one non-destructive command, `./diagnose-mreader.sh`, that launches a dedicated Dockerized diagnostics module against the current Docker Desktop twin-plane MReader deployment, exercises the API/functionality surface, captures runtime evidence even after failures, and produces one reusable human/machine report bundle for debugging.

## Constraints

- Windows Git Bash and Linux hosts must both work.
- Host requirements are Bash, Docker/Docker Compose, kubectl and curl; no host Python or jq.
- The diagnostics container reuses the exact release API-test image and runs Python/pytest inside Docker.
- Default diagnostics are non-destructive. External scraper sources are opt-in; capacity/soak/destructive RabbitMQ chaos keep their existing explicit runners.
- Raw Kubernetes Secrets and raw Docker environment inspection must never be collected.
- A failed or timed-out test stage must not prevent post-failure evidence capture or report generation.
- The existing source API route audit remains the coverage authority. Current expected coverage is 139 classified source routes.

## Architecture

### Host evidence plane

`scripts/diagnostics/run-diagnostics.sh` is the only orchestration entry point. It validates the current `docker-desktop` context, creates a timestamped results directory, builds the canonical API-test image plus the dedicated diagnostics image, captures pre-test runtime evidence, launches one long-lived diagnostics container, waits for its test-complete sentinel, captures post-test evidence, acknowledges the capture to the container, streams the container log, and returns the container's final result.

The host collector `collect-runtime-evidence.sh` gathers only read-only operational evidence from Kubernetes, Docker/Compose and stateful dependencies. Collector failures are appended to `collector-errors.tsv` instead of aborting the run.

### Container test/report plane

`tests/diagnostics/runner.py` executes stages independently and records each in `stages.tsv`. It runs the source route audit and API pytest suite, creates `.container-tests-done`, waits for `.host-post-capture-done`, then runs report analysis and report generation. Each stage is bounded; timeout is represented as exit code 124.

The default mode is `full`, which runs the complete non-external API/functionality pytest surface. `--quick` still audits every route but limits pytest to health, Auth, Catalog, Reader/image/token, Progress, Media, lifecycle, Smart Library and endpoint-contract modules. `--external` enables the existing external scraper marker explicitly.

## Evidence

Each run writes `test-results/diagnostics/<run-id>/` with:

- `REPORT.md`
- `REPORT.json`
- `REPORT_BUNDLE.zip`
- `issues.json`
- `endpoint-results.tsv`
- `stages.tsv`
- `pytest/`
- `logs/`
- `snapshot/`

Runtime evidence covers both MReader namespaces, pod current/previous logs, pod descriptions, Deployments/Services/HPA/KEDA, events, Compose/Docker state and stats, PostgreSQL connectivity/migrations/runtime-operation counts, RabbitMQ queues, both Valkey instances, user/admin gateway health and SeaweedFS reachability.

## Analysis and privacy

`analyze_report.py` sanitizes HTTP exchanges and textual evidence before bundling. It redacts password/Authorization/Cookie/token/API-key/secret values, credentials embedded in PostgreSQL/Redis URLs, Bearer material and JWT-shaped values. Raw Kubernetes Secret objects and raw `docker inspect` are forbidden.

The analyzer reports direct evidence categories including CrashLoopBackOff, OOMKilled, probe failures, Python import/circular-import failures and tracebacks, Go panic/fatal, PostgreSQL auth/grant/relation failures, refused connections, DNS failures, timeouts, RabbitMQ/Valkey connectivity issues, HTTP 5xx, test/route-audit failures and dependency-collector failures. It must not infer an unsupported root cause.

## Reporting semantics

A failing test stage does not terminate diagnostics immediately. The host post-capture phase still runs, then `REPORT.md`, `REPORT.json`, `issues.json`, `endpoint-results.tsv`, and `REPORT_BUNDLE.zip` are generated. The process returns non-zero only after report generation when error-severity findings remain.

## Verification

The module has unit/regression coverage for stage continuation, timeout behavior, sentinel handshake, full/quick targets, classification, redaction, collector failure handling, report survival with partial evidence, bundle secret exclusions, MSYS Docker path behavior, dependency snapshot read-only policy, comprehensive test-harness integration and exact diagnostics base-image pinning.
