# Docker Desktop hybrid public edges

This profile exposes **only the Docker Desktop Kubernetes gateway**. The rest of the hybrid placement stays unchanged.

```text
Internet
  ├─ Tailscale Funnel (Windows host)
  │      └─ http://127.0.0.1:8080
  │
  └─ Cloudflare Quick Tunnel (small Docker connector)
         └─ http://host.docker.internal:8080
                         │
                         ▼
              Docker Desktop Kubernetes
                    gateway Service
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          frontend      APIs      /images
                                      │
                                      ▼
                           Docker-host Image Edge
                                      │
                                      ▼
                              external NAS SeaweedFS
```

PostgreSQL, Valkey, RabbitMQ, Image Edge admin/internal ports, NAS SeaweedFS, and application pod ports are not public tunnel targets.

## One-command deployment

Set the desired policy in `.env`:

```env
HYBRID_PUBLIC_EDGES=both
HYBRID_PUBLIC_REQUIRED=false
```

Then run from Git Bash:

```bash
./hybrid-up.sh
```

`both` is the default for this package. Alternatives are `tailscale`, `cloudflare`, and `none`.

## Tailscale

The helper finds the Windows executable even when Git Bash does not have `tailscale` on PATH. Tailscale must already be signed in and the tailnet must have HTTPS/Funnel enabled.

```bash
./scripts/hybrid/public-up.sh tailscale
```

The stable `*.ts.net` hostname is added to `.env` and Reader's allow-list only after the CLI returns a valid HTTPS hostname and Funnel starts.

## Cloudflare Quick Tunnel

No Cloudflare account, domain, or token is needed. The connector runs in a separate lightweight Compose file and points at the host-side Docker Desktop Kubernetes LoadBalancer.

```bash
./scripts/hybrid/public-up.sh cloudflare
```

The default connector limits are:

```env
CLOUDFLARED_MEMORY_LIMIT=128m
CLOUDFLARED_CPU_LIMIT=0.25
CLOUDFLARED_PROTOCOL=http2
```

HTTP/2 is used by default so the connector does not depend on a clean UDP/QUIC path through Docker Desktop. A generated `*.trycloudflare.com` URL is kept in CORS as long as the connector is still running, even when its first external health probe is slow.

## CORS and cookies

The public reconciler writes exact validated HTTPS origins only. A normal dual-edge result looks like:

```env
TAILSCALE_PUBLIC_URL=https://overlord.example.ts.net
CLOUDFLARE_QUICK_PUBLIC_URL=https://random.trycloudflare.com
PUBLIC_ALLOWED_ORIGINS=https://overlord.example.ts.net,https://random.trycloudflare.com
PUBLIC_BASE_URLS=https://overlord.example.ts.net,https://random.trycloudflare.com
ALLOWED_ORIGIN=http://localhost,http://localhost:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,https://overlord.example.ts.net,https://random.trycloudflare.com
COOKIE_SECURE=true
```

A dedicated Kubernetes Secret, `mreader-public-edge`, carries `ALLOWED_ORIGIN` and `COOKIE_SECURE`. It is intentionally separate from the main `mreader-env` Secret so a dynamic Quick Tunnel URL update cannot remove NAS or database values.

Only `reader-go` and `auth-service` are restarted after origin changes.

## Status and diagnostics

```bash
./scripts/hybrid/public-status.sh
./scripts/hybrid/cloudflare-diagnose.sh
./scripts/hybrid/status.sh
```

Cloudflare diagnostics are also saved to:

```text
.runtime/cloudflare-hybrid.log
```

## Stop public exposure

```bash
./scripts/hybrid/public-down.sh
```

This stops Funnel/Quick Tunnel, removes public URLs from CORS, restores `COOKIE_SECURE=false` for local HTTP development, and leaves the hybrid application and persistent data running.

The full hybrid teardown also stops public connectors before removing the Kubernetes namespace.
