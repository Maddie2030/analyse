# 17c28ac reference import assessment

Source checkpoint: `17c28ac65f27314af65cc555dcefc6d62c82913b` (`17c28ac`).
Recovered source: saved `mreader-rc485-WIP-source-changes.patch` from the prior RC4.85 workstream.

## Import policy

This import is intentionally stored under `reference/imports/17c28ac/` and does not overwrite the Milestone-1 source tree. The cumulative WIP patch contains changes from multiple earlier RC4.85 tasks that are already present in Milestone 1, so the full patch must not be applied to this baseline.

Only the 13 P06.2 files that are absent from Milestone 1 were reconstructed into `tree/`. Each reconstructed file is a `new file` in the recovered patch and its Git blob SHA-1 was checked against the patch `index` line. `IMPORTED-FILES.tsv` records those hashes.

## Why it is useful

The imported P06.2 checkpoint is valuable as the later P06 contract reference because it defines:

- the private Catalog publication command/receipt contract expected under `/internal/v1/catalog`;
- canonical command and manifest digest semantics;
- strict bounded immutable v4 page/object-path evidence;
- Media completion evidence binding;
- Catalog idempotency receipt replay/conflict behavior;
- explicit actor, source revision, ingestion generation and media generation fences;
- 28 focused pure-Python regressions and literal digest/schema fixtures;
- qualification notes separating source-only contract completion from P06.3+ runtime/database/caller cutover work.

It is not evidence that Catalog is already the sole publisher, that Media evidence is durable in the live database, or that PUB-01/PUB-02 are closed.

## Verification in the sequential-review workspace

A disposable copy of the Milestone-1 source was overlaid with these 13 files. The live sequential baseline itself was not modified.

- `python3 -m py_compile shared/shared/catalog_publication_contract.py tests/regression/test_catalog_publication_contract.py` — PASS.
- `python3 -m unittest discover -s tests/regression -p test_catalog_publication_contract.py -v` — 28/28 PASS.
- Four contract schemas plus four fixtures parsed as JSON — PASS.
- All 13 reconstructed files match the Git blob IDs recorded by the recovered patch — PASS.

## Sequential use

Do not copy these files into their production paths while P01–P05 are being reviewed. When sequential work reaches P06.2, compare the then-current source against this checkpoint, rerun the contract suite red/green as appropriate, and port only the pieces that still satisfy the integrated ownership and migration state.
