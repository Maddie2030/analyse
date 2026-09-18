# Testing and diagnostics — current twin-plane deployment

The supported integrated runner targets only the current Docker Desktop Kubernetes twin-plane deployment. It does not start or validate the historical single-Compose application topology.

Recommended baseline:

```bash
./test-mreader.sh --full
```

Fast smoke run:

```bash
./test-mreader.sh --quick
```

Capacity-only and deeper breakpoint runs:

```bash
./test-mreader.sh --capacity
./test-mreader.sh --capacity-deep
```

The host needs Docker Desktop, Kubernetes (`docker-desktop` context), Bash, Docker and kubectl. Pytest and k6 run inside locally built Docker images run as ordinary Docker containers.

## Coverage

- `tests/api/`: pytest functional/integration suite across both user and admin gateways.
- `tests/load/`: k6 catalog, Reader/image, authenticated Progress and Admin-plane scenarios.
- `tests/regression/`: static/deep regression guards for API ownership, storage, RabbitMQ, KEDA, resource budgets and packaging.

Test containers are temporary and use deterministic test-owned users/series. k6 test data is cleaned after the run unless `--keep-test-data` is supplied.

## Reports

Pytest correctness runs create:

```text
test-results/hybrid/<run-id>/
├── REPORT.md
├── SUMMARY.txt
├── pytest.log
├── pytest-results/
└── cluster-after.txt
```

Capacity runs create their own `test-results/capacity/<run-id>/` bundle so per-API breakpoint data cannot be confused with functional pytest results. `cluster-after.txt` captures pods, Deployments, HPA/KEDA state and recent Kubernetes warning events.

## Gradual API capacity discovery (RC4.46 test harness)

Use `./test-mreader.sh --full` for functional pytest validation followed by isolated k6 breakpoint ladders. Pytest is the correctness gate; if it fails, the capacity phase is reported as blocked rather than silently disappearing. You can still run `./test-mreader.sh --capacity` explicitly for diagnostic load testing.

The standard HTTP staircase is `1 → 2 → 5 → 10 → 15 → 20 → 30 → 40 → 60 → 80 → 100` RPS. The deep profile continues `125 → 150 → 200 → 250 → 300` RPS. Realtime uses the same levels as concurrent authenticated WebSocket connections. Each workload is isolated; the first failed step is cooled down and repeated once, and only a second failure establishes the breaking point.

Every step records achieved throughput, p50/p95/p99 latency, HTTP/logical failure rate, dropped iterations, HTTP 429 count, user/admin pod state, pod CPU/RAM, user/admin HPA, user/admin KEDA ScaledObjects, deployment replica state, Docker CPU/RAM/network/block I/O, and recent Kubernetes warning events. The report derives the highest optimal level (<=0.1% failures, zero drops, p95<=70% SLO, p99<=75% SLO), highest sustainable level (<1% failures, within p95/p99 SLO, <0.5% drops), and first confirmed breaking level.

For focused diagnosis:

```bash
./test-mreader.sh --workload catalog_discover
./test-mreader.sh --workload reader_manifest
./test-mreader.sh --workload reader_image
./test-mreader.sh --workload progress_put
./test-mreader.sh --workload realtime_ws
```

Capacity results are written separately from pytest results:

```text
test-results/capacity/<run-id>/
├── CAPACITY_REPORT.md
├── CAPACITY_SUMMARY.tsv
├── results.tsv
├── logs/
└── snapshots/
```

Do not infer background worker capacity from queue length alone. Scraper/media/lifecycle/outbox/notification throughput tests must use valid durable jobs because actual work includes database state, storage, acknowledgements and recovery semantics. The current capacity ladder therefore measures request-serving flows only; worker correctness/activation remains covered by valid-job pytest scenarios rather than fake RabbitMQ payloads.


## Live test visibility

The current twin-plane test runner is self-observing. Docker image builds use plain progress output; the runner prints the exact Docker test container name and streams pytest/k6 output live. Stopped test containers are retained for inspection and are replaced automatically by the next run, so they consume no CPU/RAM while stopped.

From another terminal:

```bash
./test-mreader.sh --status
```

This also reports the host-side phase before any Docker test container exists (for example `preflight` or `building-image`) through `test-results/.runner-status`. To follow the current/recent test container:

```bash
./test-mreader.sh --follow
```

A pytest-only run builds only the pytest/seed image; it does not build the k6 image. Capacity runs build the seed image and k6 image because both are required.

## Dedicated one-command diagnostics

Use the dedicated diagnostics module when the goal is to **find as many functional/runtime failures as possible in one run and keep the evidence needed to repair them**:

```bash
./diagnose-mreader.sh
./test-mreader.sh --diagnose
```

The default is `--full`: the container runs the canonical source-route audit, then a permissions-first architecture pass before functional tests. The current architecture layer contains **832 individually named PostgreSQL checks** (capability grants, workload effective privileges, database/schema baselines, and positive/negative workload-to-capability membership isolation) plus **272 gateway/routing/CORS boundary cases** (all 139 owned routes, admin-plane fences, and both-plane parity), for **1,104 architecture cases before the normal API suite starts**. The runner then executes the complete non-external API/functionality suite, actor journeys, and the Playwright browser journeys unless `--no-browser` is supplied. `--quick` keeps the all-route audit and architecture layers but bounds the core functional modules. `--external` adds live external scraper journeys without replacing the core suite.

Reports keep permissions, boundary, API, external, actor, and browser evidence separate. `REPORT.md` includes per-layer totals and failure-cascade guidance: permission failures are prioritized before downstream 500/503s, boundary failures point to gateway/routing/CORS/service reachability, and application/state-propagation failures are prioritized only after those upstream layers are clean. The browser reading suite also verifies one complete Reader → IndexedDB → Progress → PostgreSQL → Smart Library API → Library UI chain.

The host Bash layer requires Docker Desktop, `kubectl` with context `docker-desktop`, `curl` and `.env`; it does **not** require host Python or jq. Each run writes `test-results/diagnostics/<run-id>/` with `REPORT.md`, `REPORT.json`, `REPORT_BUNDLE.zip`, `issues.json`, `endpoint-results.tsv`, `stages.tsv`, `pytest/`, `logs/` and `snapshot/`.

The bundle contains sanitized HTTP exchanges, stage logs, current/previous pod logs, pod descriptions, warning events, HPA/KEDA state, Docker/Compose state, PostgreSQL migration/outbox/operation summaries, RabbitMQ queue health, Valkey memory/health, gateway checks and NAS/SeaweedFS reachability. Raw Kubernetes Secret objects are never collected; password/token/cookie/DSN material is redacted before bundling. A failed or timed-out stage does not stop evidence collection; timeout is recorded as exit `124` and report creation continues. Capacity, soak and destructive RabbitMQ chaos remain explicit separate runners.
