# Graphify playbook for MReader RC4.85

Run commands from the repository root. In this reference bundle, replace the graph path with the corresponding file under `graphify-out/`.

## Default graph

Use the issue-oriented graph first:

```bash
G=graphify-out/development-graph.json
```

For deeper file/symbol exploration:

```bash
G=graphify-out/code-graph.json
```

## First response to any issue

```bash
graphify query "<symptom domain words>" --graph "$G" --budget 2500
graphify explain "<exact service/file/route label>" --graph "$G"
graphify affected "<exact file path>" --depth 3 --graph "$G"
```

Use `--depth 4` for shared gateway/API/storage/contract changes. Do not interpret a large affected set as permission to edit every file; it is the blast radius to inspect/test.

## Useful current queries

```bash
graphify query "reader protected cache indexeddb progress" --graph "$G" --budget 2500
graphify query "reading history library journal progress" --graph "$G" --budget 2500
graphify query "scraper staging retry publication media catalog" --graph "$G" --budget 3000
graphify query "seaweedfs media lifecycle image edge" --graph "$G" --budget 2500
graphify query "auth session cookie valkey" --graph "$G" --budget 2200
graphify query "notification outbox rabbitmq realtime" --graph "$G" --budget 2500
graphify query "database protection backup restore drill" --graph "$G" --budget 2500
graphify query "diagnostics kubernetes compose postgres valkey rabbitmq" --graph "$G" --budget 2500
```

## Exact path checks

These are useful sanity checks on the architectural graph:

```bash
graphify path "User Web" "service:reader_go" --graph "$G"
graphify path "User Web" "service:progress_go" --graph "$G"
graphify path "Admin Web" "service:scraper_service" --graph "$G"
graphify path "service:scraper_service" "service:catalog_go" --graph "$G"
graphify path "service:catalog_go" "service:realtime_go" --graph "$G"
```

Current verified examples:

- User Web → Reader: `User Web -> GET /api/reader/{seriesSlug}/{chapterSlug} -> service:reader_go`.
- User Web → Progress: `User Web -> GET /api/progress/history -> service:progress_go`.
- Admin Web → Scraper: two hops through a canonical `/api/scraper/...` route.
- Scraper → Catalog: through Media/Image.
- Catalog → Realtime: through Outbox Relay / RabbitMQ / notification path.

## High-value explain targets

```bash
graphify explain "frontend/src/reading/indexedDB.ts" --graph "$G"
graphify explain "frontend/src/reader/protectedAssetCache.ts" --graph "$G"
graphify explain "service:reader_go" --graph "$G"
graphify explain "service:progress_go" --graph "$G"
graphify explain "service:scraper_service" --graph "$G"
graphify explain "service:image_service" --graph "$G"
graphify explain "service:catalog_go" --graph "$G"
graphify explain "Database Protection capability" --graph "$G"
```

## High-value blast-radius targets

```bash
graphify affected "frontend/src/reading/indexedDB.ts" --depth 3 --graph "$G"
graphify affected "frontend/src/reader/protectedAssetCache.ts" --depth 3 --graph "$G"
graphify affected "frontend/src/api/client.ts" --depth 3 --graph "$G"
graphify affected "services/progress_go/internal/httpapi/api.go" --depth 3 --graph "$G"
graphify affected "services/scraper_service/app/publication_bridge.py" --depth 3 --graph "$G"
graphify affected "services/image_service/app/catalog_publication.py" --depth 3 --graph "$G"
graphify affected "services/catalog_go/internal/store/publication.go" --depth 4 --graph "$G"
graphify affected "scripts/diagnostics/report_builder.py" --depth 3 --graph "$G"
```

## Route-first debugging

For an API failure, search the canonical route first:

```bash
graphify query "<route fragment>" --graph "$G" --budget 1600
```

Then open `contracts/ownership/routes.v1.json` and verify:

- owner
- access plane
- handler
- consumers
- dependencies
- permitted writes
- event effects
- acceptance tests/evidence

This prevents accidental ownership regressions such as fixing a UI 404 by exposing an admin-only route on the user gateway.

## Graph staleness rule

The generated package reference records its exact source checkpoint. If a later commit changes service boundaries, routes, imports, storage ownership, publication flow, diagnostics topology, or deployment topology, regenerate the reference. A graph is navigation evidence, not authority over newer source.
