# Tailscale Funnel public development — hybrid runtime

Tailscale Funnel is an optional **user-plane edge** for the current Docker Desktop hybrid runtime. It is not a separate MReader deployment mode.

First start MReader:

```bash
./hybrid-up.sh
```

Then select Tailscale only, Cloudflare only, both, or neither:

```bash
./scripts/hybrid/public-up.sh tailscale
./scripts/hybrid/public-up.sh both
./scripts/hybrid/public-status.sh
./scripts/hybrid/public-down.sh
```

The helper discovers the connected Tailscale machine DNS name from the host CLI, exposes only the local user gateway at `127.0.0.1:8080`, updates the current CORS/session settings, and rolls only services that need the changed public origin. The admin gateway at `127.0.0.1:8081`, PostgreSQL, Valkey, RabbitMQ and NAS SeaweedFS remain private.

Tailscale must be installed and signed in on the Windows host. The hybrid public-edge helper checks both PATH and the standard Windows Tailscale installation path.
