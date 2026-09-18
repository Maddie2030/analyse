# RC4.85 P06 Catalog publication source review

**Sequential checkpoint:** P06.2 promoted; P06.3 source boundary hardened through `8a1a1d0`; runtime qualification still blocked.

## P06.2 reference promotion

The independently reviewed `17c28ac` publication contract was preserved first as a reference branch and then promoted without overwriting existing Milestone-1 paths. The active source contains the v1 publication command, Media evidence and Catalog receipt schemas/fixtures plus the strict Python contract implementation. Its focused suite remains 28/28 green in this sequential tree.

## P06.3 source changes

Migration `054_catalog_publication_boundary.sql` extends the existing `media_operations` ledger rather than creating another Media queue/table. It adds a processing generation, publication-evidence fields and `media_completion_evidence_v1`; adds `catalog_revision` to `series` and `chapters`; and creates the design-authorized `catalog_mutation_receipts` table. Catalog receipts deliberately do not cascade with later series/chapter deletion, so a retained idempotency outcome is not erased merely because the published entity is subsequently deleted.

Migration `055_ingestion_operation_authority.sql` pulls forward only the canonical ingestion authority header required by the publication transaction. Catalog locks that row for a new commit and verifies retained actor identity, current active-admin authorization, exact source revision, exact lease generation, cancellation state and `running` status. Receipt replay remains ahead of these checks so a response-loss retry can recover an already committed result after later operation-state changes.

Migration `056_media_completion_evidence_immutability.sql` seals completed Media evidence at the database boundary. Once `completion_evidence` exists, PostgreSQL rejects rebinding of operation/actor/source revision/manifest/page count/media generation or invalidation of the completed status, while unrelated Media diagnostics/result fields remain updateable. This is forward-only rather than editing migration 054 after it has become part of the sequential history.

Media increments `media_generation` whenever a worker successfully acquires/reclaims processing and can attach one generation-bound completion-evidence object only after the Media operation is completed. Identical evidence replays without a second write; a different operation/actor/source revision/generation/manifest binding conflicts. The migration-056 trigger makes the same evidence write-once at PostgreSQL level.

Catalog has Go publication models plus an independent Go v1 contract validator. The Go canonical JSON implementation reproduces the Python digest vectors, including the Unicode/special-character command fixture, and independently validates v4 immutable object identities, page ordering/bounds, dimensions, checksums, seed/grid metadata, target revision shape and payload digest.

`Store.CommitPublication` is the short Catalog-owned transaction boundary. It serializes an idempotency key with a transaction advisory lock, replays an identical retained receipt, conflicts on changed content, locks/verifies the ingestion authority row and current admin actor, locks/validates durable Media evidence, locks the series and chapter target, enforces replacement revision, creates/replaces pages, advances Catalog revisions, records exact old-page cleanup intent for replacement, appends `series.updated` and `chapter.published` outbox effects, records the Catalog receipt, and commits once. Conversion/upload remains outside this transaction.

The real PostgreSQL suite in `services/catalog_go/internal/store/publication_postgres_test.go` now covers response-loss receipt replay, same-key/different-body conflict, concurrent stale replacement, cancellation/source-revision/generation fences, inactive/non-admin actor rejection, concurrent create with one authoritative winner, and database-level Media evidence immutability. It requires the migrated disposable database and Catalog Go module toolchain.

## Verification executed in this workspace

- `test_catalog_publication_contract.py`: **28/28 passed**.
- `test_catalog_publication_boundary_source.py`: **5/5 passed**.
- `test_media_publication_evidence.py`: **5/5 passed**.
- `test_media_publication_evidence_immutability.py`: **2/2 passed**.
- `test_p06_3_ingestion_authority.py`: **6/6 passed**.
- `test_p06_3_postgres_gate_script.py`: **4/4 passed**.
- Catalog model Go contract tests: **3/3 passed** under the locally installed Go 1.23.2 in `GO111MODULE=off` mode because that package uses only the standard library. The Go digest outputs match the P06.2 Python vectors.
- Migration runner regression: **6/6 passed** and discovers the forward migration set through 056.
- Python compilation, Bash syntax, Go formatting and `git diff --check`: passed.

## Blocked evidence and remaining P06 work

The full Catalog module requires Go **1.25.0**, while this workspace currently has Go **1.23.2**. No PostgreSQL server/client, Docker-compatible runtime or disposable `MREADER_TEST_POSTGRES_DSN` is available. The guarded `scripts/test/p06-3-postgres-gate.sh` selects all `TestCommitPublication*` cases plus `TestMediaCompletionEvidenceIsDatabaseImmutable` and reaches the Go automatic-toolchain path, but this container blocks outbound DNS/network access and the Go 1.25 download fails at `proxy.golang.org`. Direct HTTPS provisioning attempts are blocked at the container network layer as well. Therefore the real PostgreSQL suite is written but **not run**, and P06.3 is not runtime-confirmed complete.

No production caller is switched by P06.3. Scraper and Media still contain their historical production Catalog-table writers. The private `/internal/v1/catalog` interface and workload/admin transport authentication are not registered yet. P06.4 must convert manual upload, existing-series scrape, batch and new-series/taxonomy/cover workflows to Catalog commands. P06.5 must make public admin write routes use the same domain implementation and add the private authenticated interface; P09.1 owns narrow credential distribution. P06.6 must version publication events/notification uniqueness before superseded writers are removed. Migration 055 establishes only the authority row and Catalog-side fence checks needed by P06.3; P07 still owns ingestion entry-point wiring, leases/transitions, terminal reconciliation, acknowledgement and cleanup semantics.
