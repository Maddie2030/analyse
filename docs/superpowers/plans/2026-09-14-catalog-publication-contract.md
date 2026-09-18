# Catalog Publication Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this bounded P06.2 task, with test-driven-development and verification-before-completion.

**Goal:** Define and exercise the publication request and evidence contract before moving production writers into Catalog.

**Architecture:** A versioned JSON command binds the target, actor, source revision, ingestion fence and Media fence to an immutable page manifest. Media completion evidence and Catalog commit receipts remain distinct. The shared Python module builds/validates the wire contract without database, network or filesystem side effects; Catalog's future Go command must independently enforce it against authenticated identity and durable records.

**Tech Stack:** Existing Python standard library, JSON Schema, Node for independent digest-vector verification. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-11-mreader-rc485-ownership-consolidation-design.md`, sections 5–7, 10–11. Master task: P06.2.

## Global constraints

- Preserve Docker Desktop Kubernetes + Compose + NAS SeaweedFS, KEDA/HPA and current resource limits.
- Catalog remains the target sole production writer; this task does not add a Python Catalog implementation or switch a partly wired publisher.
- Do not modify production tables, old migrations, live state, current published object identities or unrelated Android icons.
- Private `/internal/v1/catalog` routes are planned, not registered in this task. No caller-supplied receipt or actor field grants authority.
- Same-key/different-body commands conflict; changing a fence/revision/body requires a new command identity after deliberate reconciliation.
- Go/actual PostgreSQL verification is blocked in this workspace. Pure contract checks do not close PUB-01/PUB-02.

## Files and interfaces

| File | Responsibility |
| --- | --- |
| `contracts/catalog/v1/README.md` | Wire/auth/receipt semantics, canonical digest algorithm, bounds and integration checklist. |
| `contracts/catalog/v1/publication.schema.json` | Chapter publication command and manifest shape. |
| `contracts/catalog/v1/media-receipt.schema.json` | Media-owned completed output evidence. |
| `contracts/catalog/v1/catalog-receipt.schema.json` | Catalog-owned committed result, including publication event and revisions. |
| `contracts/catalog/v1/fixtures/` | Literal valid request/receipt/digest vectors and invalid contract cases. |
| `shared/shared/catalog_publication_contract.py` | Strict validation, immutable sealing, evidence matching and retained receipt replay. |
| `tests/regression/test_catalog_publication_contract.py` | Real Python contract behavior under accepted, malformed, stale and mismatched input. |

```python
class PublicationContractError(ValueError):
    code: str

def seal_command(unsigned: dict) -> dict: ...
def validate_command(command: dict) -> dict: ...
def manifest_digest(manifest: dict) -> str: ...
def validate_media_evidence(command: dict, receipt: dict, *, actor_id: str) -> dict: ...
def replay_receipt(command: dict, receipt: dict, *, actor_id: str) -> dict: ...
```

Returned commands/receipts are detached snapshots. Inputs are never mutated. `actor_id` must originate from authenticated/retained-admin validation, and receipts must be loaded by the owner from durable state, never accepted from a request body.

## Task 1 — freeze executable contract expectations

- [x] Write literal valid manifest/command/Media/Catalog receipt fixtures. Preserve the encoder's existing `series/chapter/_v4/<seed-derived-version>/[w<width>/]<page>.mrt` identity and metadata. Keep chapter number as a canonical two-decimal string matching PostgreSQL NUMERIC(8,2).
- [x] Record independent SHA-256 vectors using sorted-key compact JSON with ASCII escaping, integral numbers and no non-finite values. Include a Unicode title and special characters so cross-language escaping errors cannot silently break retries.
- [x] Write failing tests for valid sealing; mutation isolation; missing/unknown fields; invalid version/IDs/integer bounds; empty/oversized/unordered pages; path/seed/dimension/derivative mismatch; digest tampering; uncompleted/cross-operation Media evidence; mismatched actor; identical receipt replay and same-key/different-body rejection.
- [x] Run the test file and record the initial missing-contract failure before implementation.

```bash
python3 -m unittest discover -s tests/regression -p test_catalog_publication_contract.py -v
```

## Task 2 — implement the contract without introducing another writer

- [x] Implement exact object/type/field validation and detached command sealing. Bound the wire body to 4 MiB and the final page manifest to 4096 entries; reject excess rather than truncate. Primary/derivative dimensions and grid must satisfy the current v4 reader bounds.
- [x] Compare Media completion against command actor, operation, source revision, Media generation, page count and manifest digest. Keep ingestion and Media generations independent; transaction-time fence checks remain mandatory at integration.
- [x] Compare a durable Catalog receipt with the complete command digest, identity, actor and result shape. Return its recorded result on identical retry; conflict on changed content. Receipt lookup failure/absence is not implemented as a fake successful result.
- [x] Publish matching schemas and documentation, including the distinction between shape checks and real checksum/storage/authentication proof.
- [x] Run the real behavioral suite and independent digest-vector check; review every rejected case and schema parity.

## Task 3 — record a truthful integration handoff

- [x] Update the master tracker and qualification evidence with actual pass/failure counts and tool limitations.
- [x] Advance to P06.3: extend existing Media durable evidence, add Catalog revision/receipt transaction and permission-aware reads, implement the Go boundary, then execute real concurrency/response-loss tests.
- [x] Persist the source patch and tracker. This contract checkpoint alone is not the next full application milestone.

P06.3 must verify current actor authorization, workload credentials, operation/draft source revision, cancellation and ingestion fence in the commit protocol. It must validate Media-owned immutable evidence from a declared read interface, serialize idempotency, enforce the target revision, and atomically write chapter/pages/revisions/receipt/events/cleanup. No upload/network encoding under database locks. Other metadata/cover commands will use the same command architecture during P06.4; this chapter-specific contract does not pretend those commands already exist.

Final handoff: Tasks 1–3 are complete as a source-only P06.2 contract checkpoint. Commits `7bc7a7f` and `17c28ac65f27314af65cc555dcefc6d62c82913b` and the qualification record capture the implementation, schema-role correction, fresh verification, independent review, and blocked runtime gates. P06.3 is now current; this checkpoint does not close PUB-01/PUB-02 or qualify a Milestone 2 package.
