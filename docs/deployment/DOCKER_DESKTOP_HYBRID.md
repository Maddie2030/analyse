> **RC4.36 twin-plane update:** the active Docker Desktop Kubernetes profile now uses `mreader-user` for public/read workloads and `mreader-admin` for scraper/publisher/admin workloads. Public tunnels target only `localhost:8080`; the admin gateway is `localhost:8081`. See `docs/architecture/TWIN_PLANE_ARCHITECTURE.md`.

# Docker Desktop Hybrid Kubernetes profile — RC4.36 twin plane

This is an **additional local/early-public-test deployment mode**. It does not replace the Azure-native/cloud production architecture.

## Placement

**Docker Compose (host-side services)**
- PostgreSQL — existing 1 GiB / 1.5 CPU cap
- Valkey/Redis — existing 640 MiB / 0.75 CPU cap
- RabbitMQ — existing 512 MiB / 0.75 CPU cap
- Nginx Image Edge — existing 256 MiB / 0.5 CPU cap, persistent Docker cache volume

**Docker Desktop Kubernetes — user plane (`mreader-user`)**
- User gateway + public frontend
- Auth, read-only Catalog, Reader, Progress, Social, Realtime
- Notification worker

**Docker Desktop Kubernetes — admin plane (`mreader-admin`)**
- Admin gateway + admin frontend
- Admin Auth + Catalog writer
- Scraper API, series/batch workers and optional browser renderer
- Image API, media/lifecycle/thumbnail workers and outbox relay

**Public connectivity adapters (host side, development/test only)**
- Tailscale Funnel — Windows Tailscale client → `http://127.0.0.1:8080`
- Cloudflare Quick Tunnel — tiny Docker connector → `http://host.docker.internal:8080`

Both public adapters terminate at the **user gateway only**. The admin gateway is available locally/private on `127.0.0.1:8081` and is never targeted by the public connector definitions. Neither public adapter connects directly to PostgreSQL, Valkey, RabbitMQ, Image Edge, NAS SeaweedFS, or an individual application pod.

**External**
- Existing NAS SeaweedFS filer. Set `NAS_SEAWEEDFS_HOST` and `NAS_SEAWEEDFS_PORT` in `.env`.

**Kubernetes persistent local disk**
- 20 GiB scraper staging PVC

The Image Edge cache is deliberately a Docker named volume, not a Kubernetes PVC.

With roughly 300 GB SSD space available, these reservations are conservative; also leave room for Docker images/build cache and Docker Desktop's virtual disk.

## Why this split

The 16 GB Windows host does not gain anything from running PostgreSQL, Valkey and RabbitMQ inside a single-node Kubernetes cluster. Keeping the stateful services and Image Edge in Compose preserves simple persistent volumes/cache ownership and avoids Kubernetes stateful overhead. Kubernetes is used where it helps: replica management, rolling restarts, HPA and queue-driven worker scale-to-zero.

No existing per-container CPU or memory maximum is increased. Hybrid-only database pool overrides are **lower** so extra API replicas do not multiply PostgreSQL connections uncontrollably. Social applies its reduced pool directly to Prisma through `SOCIAL_DB_CONNECTION_LIMIT`.

## Autoscaling safeguards for 16 GB

Core APIs use bounded CPU HPA:
- Catalog: 1–3
- Reader: 1–3
- Auth, Progress, Social, Realtime: 1–2
- Scale-up is limited to one pod/minute.
- Scale-down is stabilized for five minutes.

RabbitMQ workers use plane-local KEDA:
- user notification worker: 0–2
- admin media chapter worker: 0–1, 1536 MiB limit
- admin thumbnail worker: 0–1
- admin scraper batch: 0–2
- admin scraper series: 0–2, 768 MiB limit and bounded local concurrency
- Chromium browser renderer: manually 0/1 and absent from normal memory usage

Resource admission is split rather than global. The user namespace is capped at **3584 MiB** of declared memory limits / **3 GiB** requests; the admin namespace is capped at **6656 MiB** limits / **3 GiB** requests. The admin budget is deliberately sized so two series workers can run in parallel with the media pipeline (and the tested mixed-worker scenario still fits), while unbounded simultaneous scale-out remains impossible. Queue work stays durable if a less-important extra replica is refused.

This intentionally trades background-job speed for system stability. Queue jobs wait durably instead of making the Windows machine run out of memory.

## Docker Desktop requirements

Host Python is not required by the Docker Desktop hybrid bootstrap or its static validation suite. The host prerequisites are Docker Desktop/Docker Compose, `kubectl`, Git Bash/POSIX shell utilities (`awk`, `grep`, `sed`), and the selected public-edge CLI where applicable. Python services run Python only inside their pinned container images.

Use Docker Desktop Linux containers and the built-in **single-node `kubeadm` cluster** with the `docker-desktop` kubectl context. Docker Desktop documents kubeadm as its single-node provisioning mode and supports local Kubernetes development/testing. `host.docker.internal` is used by Kubernetes to reach Docker-published PostgreSQL/Valkey/RabbitMQ and the host-side Image Edge. The Image Edge reaches the Kubernetes Reader authorization service through its Docker Desktop LoadBalancer port.

The deploy script verifies this connectivity before starting MReader pods.

## Deploy

1. Enable Docker Desktop Kubernetes (single-node / kubeadm).
2. Ensure Docker Desktop has enough memory to coexist with Windows. Do not allocate all 16 GB to Docker Desktop; leave headroom for Windows/browser.
3. Create/fill `.env`. NAS settings are required:

```bash
NAS_SEAWEEDFS_HOST=192.168.x.x
NAS_SEAWEEDFS_PORT=8888
```

4. Public-edge selection is configured in `.env`. This dual-edge package defaults to both:

```bash
HYBRID_PUBLIC_EDGES=both          # both | tailscale | cloudflare | none
HYBRID_PUBLIC_REQUIRED=false      # keep local deployment usable if edges fail
```

For Tailscale, install/sign in to the Windows client and enable Funnel/HTTPS in the tailnet. Cloudflare Quick Tunnel needs no account, token, or domain.

5. From Git Bash, run the single idempotent bootstrap command:

```bash
./hybrid-up.sh
```

It validates Docker/Kubernetes, safely validates/repairs `.env`, switches to the `docker-desktop` context when available, and uses the canonical database-workload resume order below before public-edge reconciliation:

```text
quiesce -> pre-upgrade backup -> migrate -> P09.3 grant reconcile -> P09.4 readiness -> generation-stamped rollout -> rollout proof -> HPA/KEDA
```

P09.4 readiness fails closed if the latest migration, effective P09.3 grants, workload-specific DSNs/scopes, or P08.8 host/database restore-generation mirror are inconsistent. Database workload pod templates receive a deterministic non-secret `MREADER_DEPLOYMENT_GENERATION`; this includes workers whose checked-in replica count is zero, so later KEDA activation cannot revive a stale pre-restore template. HPA/KEDA are restored only after current-generation rollout proof. PostgreSQL restore follows `P08.8 restore/generation commit -> canonical hybrid deploy sequence`; there is no separate restore-only application/autoscaler apply path.

The supported live P09.4 qualification is intentionally explicit because it quiesces the current hybrid installation for a controlled read-only mismatch probe before resuming through the canonical deploy path:

```bash
MREADER_P09_4_RUNTIME_CONFIRM=current-hybrid \
MREADER_P09_4_EXPECT_PREVIOUS_GENERATION=<generation-before-the-real-P08.8-restore> \
./scripts/test/p09-4-runtime-gate.sh
```

A fully executed gate exits 0 only after proving the current generation is the expected P08.8 N+1, the mismatch is rejected while autoscalers remain absent, current templates carry the generation token (including replica-zero DB workers), canonical deploy succeeds, and HPA/KEDA return afterward. Exit 1 is a contract failure. Exit 2 is **BLOCKED** because authorization/runtime prerequisites or real N→N+1 evidence are unavailable; BLOCKED is never PASS. The gate never edits the P08.8 host restore control or `database_restore_state` to manufacture a generation transition. Ordinary `scripts/hybrid/validate.sh` runs only dependency-light P09.4 source tests, not this runtime probe.

6. Check:

```bash
./scripts/hybrid/status.sh
./scripts/hybrid/public-status.sh
curl http://localhost:8080/healthz
```

The user gateway LoadBalancer exposes port 8080 on Docker Desktop and the admin gateway exposes 8081 locally. Tailscale Funnel targets `127.0.0.1:8080`; the Cloudflare connector reaches the same user LoadBalancer as `host.docker.internal:8080`. Neither connector targets 8081.

## Dual public edge and CORS synchronization

A Quick Tunnel hostname is generated at runtime, while the Tailscale hostname is stable. The public-edge reconciler validates both URLs and writes only strict HTTPS origins into `.env`:

```env
TAILSCALE_PUBLIC_URL=https://overlord.example-tailnet.ts.net
CLOUDFLARE_QUICK_PUBLIC_URL=https://random-words.trycloudflare.com
PUBLIC_ALLOWED_ORIGINS=https://overlord.example-tailnet.ts.net,https://random-words.trycloudflare.com
PUBLIC_BASE_URLS=https://overlord.example-tailnet.ts.net,https://random-words.trycloudflare.com
ALLOWED_ORIGIN=http://localhost,http://localhost:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,https://overlord.example-tailnet.ts.net,https://random-words.trycloudflare.com
COOKIE_SECURE=true
```

Dynamic values are copied to a dedicated Kubernetes Secret named `mreader-public-edge`. Reader receives `ALLOWED_ORIGIN`; Auth receives `COOKIE_SECURE`. This is intentionally separate from `mreader-env`, so changing a Quick Tunnel URL cannot erase the NAS/SeaweedFS patch or database settings. Only Reader and Auth are restarted when the public origin set changes.

If Cloudflare is slow during its first external probe but the connector is still running, the generated URL stays in CORS so it can recover without another rollout. If Tailscale fails but Cloudflare succeeds (or the reverse), the successful edge remains available.

Useful commands:

```bash
./scripts/hybrid/public-up.sh both
./scripts/hybrid/public-up.sh tailscale
./scripts/hybrid/public-up.sh cloudflare
./scripts/hybrid/public-status.sh
./scripts/hybrid/cloudflare-diagnose.sh
./scripts/hybrid/public-down.sh
```

Stopping public edges does not stop the Kubernetes application or delete data. It clears the public URLs from `.env`, restores local-only CORS, and returns `COOKIE_SECURE=false` for ordinary local HTTP development.

## Chromium fallback

Chromium remains completely absent from normal worker memory use:

```bash
./scripts/hybrid/browser.sh enable
./scripts/hybrid/browser.sh status
./scripts/hybrid/browser.sh disable
```

## Removing the profile

Preserve PostgreSQL/Valkey/RabbitMQ volumes:

```bash
./scripts/hybrid/destroy.sh
```

Delete those Docker volumes too only when intentionally wiping local data:

```bash
DELETE_DATA=true ./scripts/hybrid/destroy.sh
```

## Capacity expectations

This profile is for development, load testing and early public traffic. A single physical Windows machine is still one failure domain: HPA provides more processes/concurrency, **not machine-level high availability**. Do not promise 1,000 concurrent users until a workload-specific load test proves it. The image/browser caching design means 1,000 registered or intermittently active users is much easier than 1,000 users simultaneously generating uncached API/media work.

Watch `kubectl top`, PostgreSQL active connections, Redis memory, RabbitMQ queue depth, image-edge cache hit ratio, p95/p99 response latency and Windows/Docker Desktop memory pressure during tests.

## Logging efficiency

The hybrid Caddy gateway writes sampled JSON access logs to stdout instead of a rotating file inside the container. `/images/*` and `/healthz` are excluded from gateway access logs, and Nginx image-edge suppresses per-image access logs while retaining error logs and `X-MReader-Image-Cache` response headers. This prevents high-reader traffic from turning Docker Desktop log storage into a separate SSD/CPU bottleneck.

## One-command teardown (RC4.21+)

Normal teardown, preserving durable Docker volumes and shared cluster add-ons:

```bash
./hybrid-down.sh
```

Complete local purge (PostgreSQL/Valkey/RabbitMQ/cache volumes, MReader images,
KEDA and Metrics Server included):

```bash
./hybrid-down.sh --all --yes
```

External/NAS SeaweedFS is deliberately never destroyed by this command.
Use `./hybrid-down.sh --help` for selective teardown modes.

## Durable local state

RC4.83 uses one fixed set of Docker volume names for the hybrid stateful tier: `mreader_pgdata`, `mreader_redis_data`, `mreader_rabbitmq_data`, `mreader_image_cache`, and `mreader_backup_spool`. Startup does not probe or prefer older volume-name generations. Normal `hybrid-up.sh` never copies or deletes those volumes; destructive local reset requires the explicit `hybrid-down.sh --purge-data --yes` path. External NAS SeaweedFS remains outside this volume lifecycle.

Verify the complete metadata/media path with:

```bash
./scripts/hybrid/check-data-path.sh --all
```

An empty webpage catalog indicates an empty/wrong PostgreSQL metadata volume; SeaweedFS/NAS stores media objects and by itself does not populate the catalog.


## PostgreSQL protection (RC4.36)

The host-side stateful tier now includes a small `backup_agent`. It allows at most one automatic logical-backup attempt per local calendar day inside the default 20:00–22:00 maintenance window, treats a verified manual/admin dump as satisfying that day, and creates physical base backups every two elapsed days with one automatic attempt on an eligible date inside the same window. `hybrid-up.sh` still creates a separate verified pre-upgrade dump before migrations. Admins can trigger manual dumps from the Admin Dashboard. Use `./db-backup.sh status` and see `docs/operations/POSTGRES_BACKUP_AND_RESTORE.md`.
