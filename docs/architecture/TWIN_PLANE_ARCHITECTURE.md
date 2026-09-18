# MReader Twin-Plane Hybrid Architecture — RC4.46

RC4.36 separates the Docker Desktop Kubernetes profile into two complementary planes while retaining one shared stateful backbone.

## User plane — `mreader-user`

Public/read-oriented workloads:

- `user-gateway` — LoadBalancer `localhost:8080`
- `frontend` — runtime `adminPlane=false`
- `auth-service`
- `catalog-go` — explicitly `CATALOG_GO_ENABLE_WRITES=false`
- `reader-go`
- `progress-go`
- `social-ts`
- `realtime-go`
- `notification-worker` — KEDA scale-to-zero from RabbitMQ management metrics (ready + in-flight deliveries)

The user gateway rejects `/admin*`, `/api/scraper*`, `/api/upload*`, Catalog admin routes, and all write methods to `/api/catalog*` before application routing. Cloudflare Quick Tunnel and Tailscale Funnel target only this gateway.

## Admin/ingestion plane — `mreader-admin`

Write/CPU-heavy workloads:

- `admin-gateway` — LoadBalancer `localhost:8081`
- `admin-frontend` — same frontend image with runtime `adminPlane=true`
- `auth-admin` — local admin-session endpoint; `COOKIE_SECURE=false` for localhost development
- `catalog-admin` — same Catalog Go image with writes explicitly enabled
- `scraper-service`
- `scraper-series-worker`
- `scraper-batch-worker`
- `scraper-browser` — 0 replicas by default
- `image-service`
- `media-worker`
- `media-thumbnail-worker`
- `outbox-relay` — KEDA scale-to-zero from due PostgreSQL outbox rows
- `lifecycle-worker` — KEDA scale-to-zero from due/processing PostgreSQL cleanup rows

Scraper workers publish through `catalog-admin` and use the User Reader through Kubernetes FQDN. Different series can stage/publish concurrently; same-series operations remain protected by PostgreSQL locks/idempotency.

## Shared stateful backbone

Docker Compose remains responsible for:

- PostgreSQL
- Valkey/Redis
- RabbitMQ
- PostgreSQL backup agent
- Image Edge cache

SeaweedFS remains external on the NAS.

Both Kubernetes namespaces receive namespace-local `db`, `redis`, and `rabbitmq` ExternalName services pointing to `host.docker.internal`. KEDA uses namespace-qualified RabbitMQ management FQDNs so the operator can see both ready and unacknowledged deliveries from the `keda` namespace. Admin recovery scalers also query PostgreSQL durable workflow state, allowing stale/undispatched work to wake a worker even when RabbitMQ itself is empty.

## Network paths

```text
Cloudflare Quick Tunnel ----\
                             +--> user gateway :8080 --> user APIs/frontend
Tailscale Funnel -----------/
localhost:8080 -------------/

localhost:8081 ------------------> admin gateway --> scraper/publisher/admin APIs

scraper worker --> normal Docker/Windows egress --> source website
scraper/image service --> LAN --> SeaweedFS NAS
both planes --> Docker host --> PostgreSQL / Valkey / RabbitMQ
```

The public-edge scripts never point a tunnel at port 8081.

## Security and failure isolation

The split adds several independent controls:

1. Public ingress has no route to scraper/upload/admin endpoints.
2. User Catalog is read-only at the application configuration level.
3. Admin Catalog writer is not exposed by the public gateway.
4. User and admin resource quotas are independent, so ingestion pressure cannot consume the entire user-plane budget.
5. Admin UI routes are disabled in the runtime configuration of the public frontend, in addition to being blocked at Caddy.
6. KEDA queue workers remain bounded and scale only in the plane that owns them. Long-running consumers use RabbitMQ HTTP queue metrics including unacknowledged deliveries, so claiming the last message cannot make a busy worker look idle.
7. Durable background workers (`outbox-relay`, `lifecycle-worker`) stay at zero when idle and are awakened directly by PostgreSQL work state; scaler failures fall back to one replica for safety.

## Resource budgets

For the 16 GiB Docker Desktop host:

- User plane: 3584 MiB aggregate memory-limit quota, 3 GiB request quota, 20 pods.
- Admin plane: 6656 MiB aggregate memory-limit quota, 3 GiB request quota, 20 pods.

Per-pod limits are retained. The quotas are intentionally conservative blast-radius controls rather than throughput targets.

## Upgrade from RC4.32 single plane

`hybrid-up.sh` detects the old `mreader` namespace and:

- deletes its HPA/KEDA objects,
- scales its Deployments to zero,
- removes the old `gateway` and `reader-go-edge-auth` LoadBalancer services,
- leaves the namespace and `scraper-staging` PVC in place for manual recovery.

RC4.36 then creates the two active namespaces. The old namespace can be removed later once no staging recovery is required. `hybrid-down.sh` without `--keep-namespace` removes all three namespaces.
