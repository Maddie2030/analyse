# MReader change-impact workflow

Use this as the default debugging/change workflow. The package-generated reference records the exact mapped source checkpoint; regenerate it after structural changes.

## Fast path

```bash
# from this reference bundle
python scripts/development-reference/mreader-impact.py --reference-dir development-reference "reader pages keep redownloading"

# issue-oriented graph first
G=graphify-out/development-graph.json
graphify query "reader pages keep redownloading" --graph "$G" --budget 2500
graphify explain "frontend/src/reader/protectedAssetCache.ts" --graph "$G"
graphify affected "frontend/src/reader/protectedAssetCache.ts" --depth 3 --graph "$G"
```

Then inspect the route/storage/event contract listed by `ISSUE-TO-CHANGE-INDEX.md` before modifying code.

## Decision order

1. **Classify the symptom** using `tools/mreader-impact.py`.
2. **Locate ownership** in `contracts/ownership/routes.v1.json` for API problems, `contracts/reading/` for reading state, `contracts/catalog/` for publication, or `contracts/events/` for async effects.
3. **Query the issue graph** (`development-graph.json`) to find the intended service/storage path.
4. **Explain the first candidate** with Graphify rather than opening dozens of adjacent files.
5. **Run affected** on that candidate. Treat the result as the inspection/test blast radius, not an edit list.
6. **Use the code graph** (`code-graph.json`) only when you need lower-level import/symbol adjacency.
7. **Patch the canonical owner**. Avoid bypasses across service boundaries.
8. **Run focused tests first**, then ownership/contracts/static checks for the changed boundary.
9. If routes, service boundaries, storage ownership, deployment topology, or significant imports changed, **regenerate this reference** before checkpointing.

## Change classes and mandatory gates

| Change class | Mandatory evidence before completion |
|---|---|
| Web reading/cache/journal | reading contract + Web repository tests + browser reading static/spec + Progress API if server semantics changed |
| Android reading | Android repository/codec/static parity + Reader/Progress API contract |
| API route | ownership manifest + route audit + access-plane/consumer-denial + gateway mapping when relevant |
| Catalog publication | catalog contracts + Scraper→Media + Media→Catalog + Catalog transaction/event tests |
| Media/storage/lifecycle | media evidence + SeaweedFS/storage env + lifecycle generation/reference tests |
| DB schema/role | migration + PostgreSQL role/grant gate + permitted writes + backup/restore compatibility |
| Event/outbox | event schema/registry + transaction/outbox production + consumer idempotency/canonical reread |
| Hybrid/deployment | twin-plane static + resource/secret scope + host-path regressions + diagnostics runtime snapshot |
| Backup/restore | catalog/snapshot verification + safety capture + fencing + PostgreSQL runtime drill |

## Staleness trigger

Regenerate the graphs/index when any of these changes occur:

- a route is added/removed/moved;
- service ownership changes;
- a new durable store or cache becomes authoritative;
- publication or deletion flow changes;
- event producer/consumer topology changes;
- gateway/user/admin-plane separation changes;
- major imports/modules are moved during refactoring;
- Docker Compose/Kubernetes responsibility changes.
