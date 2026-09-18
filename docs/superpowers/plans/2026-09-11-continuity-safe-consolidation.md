# MReader Continuity-Safe Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use Superpowers TDD/systematic debugging and verification-before-completion for each task.

**Goal:** Produce a current-only MReader runtime that can safely adopt historical local PostgreSQL volumes and recover catalog/page/NAS metadata from supported backups.

**Architecture:** Runtime services remain on current contracts. Upgrade compatibility is isolated to one-time volume adoption and an on-demand catalog recovery tool. NAS is validation-only during recovery.

**Tech Stack:** Bash, Docker Compose, Docker Desktop Kubernetes, PostgreSQL 16, Go, FastAPI, React, Kotlin/Android, SeaweedFS, RabbitMQ, Valkey/KEDA.

**Spec:** `docs/superpowers/specs/2026-09-11-continuity-safe-consolidation-design.md`

## Global constraints

- Preserve existing NAS object paths and v4 encoding seeds exactly.
- Recovery may import only seven catalog/taxonomy tables.
- Recovery target catalog must be empty.
- Ambiguous dual PostgreSQL volumes must fail closed.
- Current runtime must not regain old token/session/codec/job-status fallbacks.

### Task 1: Stateful volume adoption

- Add selectable Compose volume names.
- Add `scripts/hybrid/adopt-existing-stateful-volumes.sh`.
- Run adoption from bootstrap and hybrid-up before deployment.
- Add mocked-Docker regression for legacy-only, ambiguous, and explicit-choice cases.

### Task 2: Catalog recovery subsystem

- Add `scripts/recovery/catalog-restore.sh`.
- Add transactional `catalog-import.sql`.
- Support logical dump and physical snapshot donors.
- Validate donor schema/FKs/v4 encoding metadata.
- Validate NAS primary objects read-only.
- Create pre-import full PostgreSQL safety dump.
- Import only the seven approved tables into an empty catalog.

### Task 3: Canonical API alias cleanup

- Remove Catalog `/dashboard`.
- Remove Progress PUT mutation and use `/commit` in load tooling.
- Remove scraper `publish-status` alias.
- Remove Realtime `/ws` alias.
- Update route coverage/tests.

### Task 4: Backup future-proofing

- Extend backup manifest with PostgreSQL major, schema migration version, recovery contract, and protected encoding version.

### Task 5: Release hardening

- Bump release to RC4.84 / Android build 484.
- Update operator/recovery documentation.
- Run all regression scripts and current-release validator.
- Record environment-blocked full builds separately from passing source/static gates.
- Package exact verified source with checksum manifest and ZIP SHA-256.
