# MReader Containerized Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development to implement this plan task-by-task. TDD is mandatory.

**Goal:** Add one Dockerized MReader diagnostics command that exercises APIs/functionality, captures runtime/dependency evidence despite failures, and emits a sanitized reusable report bundle.

**Architecture:** A Git-Bash-safe host Bash plane builds/launches the diagnostics container and captures Kubernetes/Docker/dependency state. A long-lived container plane runs route/API tests, waits for host post-capture, analyzes evidence, and generates reports.

**Tech Stack:** Bash, Docker/Docker Compose, Kubernetes/kubectl, Python 3.12, unittest/pytest, existing MReader API-test image.

**Spec:** `docs/superpowers/specs/2026-09-18-mreader-containerized-diagnostics-design.md`

## Global Constraints

- Exact release version is `1.3.0-rc4.84`.
- No host Python or jq dependency.
- Default mode is non-destructive and full; `--quick` is bounded.
- Preserve Windows Git-Bash/MSYS Docker-path behavior.
- Never collect raw Kubernetes Secrets or Docker `Config.Env`.
- Continue evidence/report generation after individual stage failures and timeouts.

---

### Task 1: Dedicated runner contract

Create `diagnose-mreader.sh`, `scripts/diagnostics/run-diagnostics.sh`, `tests/regression/diagnostics-harness-static.sh`; add `--diagnose` to `scripts/test-mreader.sh`. Test the static contract RED then GREEN.

### Task 2: Container protocol

Create `tests/diagnostics/runner.py`, its unittest contract, and the pinned `tests/diagnostics/Dockerfile`. Prove stage failures do not abort subsequent stages and sentinel handshake works.

### Task 3: Runtime evidence collector

Create `collect-runtime-evidence.sh` and static guards. Capture both namespaces, previous/current pod logs, events, HPA/KEDA and restricted Docker state. Prove raw Secret/raw Docker env collection is absent.

### Task 4: Dependency snapshots

Extend collector with read-only PostgreSQL, RabbitMQ, Valkey, gateway and SeaweedFS checks. Add a regression forbidding destructive cache/queue/SQL operations.

### Task 5: Analysis and redaction

Create `analyze_report.py` and tests for evidence classification, HTTP endpoint extraction, collector failures and secret redaction.

### Task 6: Resilient reports

Refactor `report_builder.py` to tolerate partial/missing evidence and produce `REPORT.md`, `REPORT.json`, `issues.json`, `endpoint-results.tsv` and an in-run `REPORT_BUNDLE.zip`. Add bundle tests.

### Task 7: Integration

Wire analyzer/report builder into the long-lived runner, add bounded timeouts, default full vs quick target sets, static regression wiring, README/operator docs, exact base-image pin and comprehensive harness checks.

### Task 8: Verification and durable checkpoint

Run diagnostics unit/static gates, 139-route audit, affected release gates and current-release validator (split if execution window requires it). Commit source, update RC4.85 tracker/handoff, build/reopen/deterministically verify source ZIP, build all-refs recovery ZIP, upload to Library, materialize both back, and verify exact HEAD/source/stash.
