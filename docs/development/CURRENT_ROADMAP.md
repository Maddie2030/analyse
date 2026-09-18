# MReader current architecture and priorities

**Current baseline:** v1.3.0-rc4.52 Docker Desktop hybrid.

## Active architecture

- Auth: FastAPI.
- Catalog: Go.
- Reader: Go.
- Progress: Go.
- Social API: TypeScript/Fastify.
- Realtime and notification workers: Go.
- Scraper: Python/FastAPI plus durable RabbitMQ workers; optional isolated browser renderer.
- Media: Python/FastAPI + libvips.
- PostgreSQL: canonical state, scraper workflow state and transactional outbox.
- Valkey/Redis: cache and short-lived coordination/state.
- RabbitMQ: durable scraper/media/notification dispatch and events.
- Kubernetes PVC: unpublished scraper staging in the Docker Desktop hybrid profile.
- SeaweedFS on NAS: final media and PostgreSQL backup objects.
- Caddy gateway + Docker Image Edge: application routing and protected v4 image delivery.
- Kubernetes HPA/KEDA: bounded stateless/service and queue-worker scaling.
- Public development edges: Tailscale Funnel and Cloudflare Quick Tunnel, both terminating at the localhost gateway.

## Current priorities

1. Preserve idempotent, crash-safe scraper/media publication under concurrent administrators.
2. Allow unrelated series to stage/publish in parallel while serializing same-series commits.
3. Keep KEDA scaling bounded for the 16-GB Docker Desktop host.
4. Keep PostgreSQL backups continuously verifiable and recoverable from NAS.
5. Keep browser rendering optional and scale-to-zero.
6. Keep final media on NAS and temporary staging local to the hybrid cluster.
7. Remove compatibility code only when it has no active runtime consumer.
