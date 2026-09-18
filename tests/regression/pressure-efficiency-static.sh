#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

# 1) Social batch metrics must remain set-based instead of per-series Promise fanout.
grep -q 'metricsForSeriesBatch' services/social_ts/src/routes.ts
grep -q 'WITH requested AS' services/social_ts/src/routes.ts
grep -q 'JOIN requested r ON r.id = b.series_id' services/social_ts/src/routes.ts
! grep -A20 'metrics-batch' services/social_ts/src/routes.ts | grep -q 'Promise.all'

# 2) Reader image/session validation has bounded short-lived local caches and O(1) chapter path lookup.
grep -q 'defaultGrantCacheTTL = 5 \* time.Second' services/reader_go/internal/imagetoken/token.go
grep -q 'defaultGrantCacheMax = 1024' services/reader_go/internal/imagetoken/token.go
grep -q 'pathSet.*map\[string\]struct{}' services/reader_go/internal/imagetoken/token.go
grep -q 'defaultSessionCacheTTL = 5 \* time.Second' services/reader_go/internal/session/session.go

# 3) Catalog hot responses are local-cacheable but strictly byte-bounded.
grep -q 'defaultLocalMaxBytes.*16 \* 1024 \* 1024' services/catalog_go/internal/cache/cache.go
grep -q 'catalogHotReadCacheTTL.*10 \* time.Second' services/catalog_go/internal/httpapi/api.go

# 4) Progress persistence coalesces stream records and batches DB + XACK work.
grep -q 'UpsertBatch(ctx context.Context' services/progress_go/internal/store/store.go
grep -q 'coalesced_updates' services/progress_go/internal/progress/service.go
grep -q 'XAck(ctx, s.stream, s.group, ackIDs\.\.\.)' services/progress_go/internal/progress/service.go

# 5/6) Autoscaling is quota-aware; critical and expendable Valkey state are split without raising total limits.
grep -q 'averageValue: 350m' deploy/docker-desktop-hybrid/user-hpa.yaml
grep -q 'averageValue: 500m' deploy/docker-desktop-hybrid/user-hpa.yaml
grep -A12 'name: notification-worker' deploy/docker-desktop-hybrid/user-keda.yaml | grep -q 'maxReplicaCount: 1'
grep -q '^  redis_cache:' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'REDIS_CRITICAL_MEMORY_LIMIT:-384m' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'REDIS_CACHE_MEMORY_LIMIT:-256m' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'maxmemory-policy' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'READER_GO_CACHE_REDIS_ADDR' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'PROGRESS_GO_CACHE_REDIS_ADDR' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'cacheRedis.*\*redis.Client' services/progress_go/internal/progress/service.go

# 7) Argon2 never blocks the ASGI event loop under login/register bursts.
grep -q 'ThreadPoolExecutor(max_workers=2' services/auth_service/app/infrastructure/passwords.py
grep -q 'await self.passwords.hash_async' services/auth_service/app/application/auth_service.py
grep -q 'await self.passwords.verify_async' services/auth_service/app/application/auth_service.py

# 8) Realtime avoids synchronized validation and correlated unread-count queries.
grep -q 'EnableCompression: false' services/realtime_go/cmd/realtime/main.go
grep -q 'sessionRecheckDelay' services/realtime_go/cmd/realtime/main.go
grep -q 'unread_counts AS' services/realtime_go/internal/sources/rabbit.go
grep -q '0.85 + Math.random() \* 0.3' frontend/src/realtime/client.ts

# 9) Pressure-path DB indexes are migration-backed.
[[ -f db/migrations/038_pressure_path_indexes.sql ]]
grep -q 'idx_bookmarks_series_id' db/migrations/038_pressure_path_indexes.sql
grep -q 'idx_notifications_user_unread_created' db/migrations/038_pressure_path_indexes.sql

# 10) NAS writes are bounded and latency-paced while reads remain independent.
grep -q 'SEAWEEDFS_WRITE_CONCURRENCY: int = 2' shared/shared/config.py
grep -q '_write_with_backpressure' shared/shared/seaweedfs.py
grep -q 'scraper_storage_write_concurrency: int = 2' services/scraper_service/app/config.py

# Repository organization: root is for human entrypoints/metadata, deployment files live under deploy/.
! find . -maxdepth 1 -type f -name 'docker-compose*.yml' | grep -q .
[[ -d deploy/compose && -d deploy/docker-desktop-hybrid ]]
[[ ! -d deploy/helm && ! -d deploy/platform && ! -d deploy/gateway ]]
[[ -d docs/architecture && -d docs/deployment && -d docs/operations && -d docs/development ]]

echo 'pressure-efficiency + repository-layout static regression PASSED'
