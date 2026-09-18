# MReader deployment model — RC4.83

RC4.83 intentionally supports one application runtime model:

**Docker Desktop Kubernetes + Docker Compose stateful services + external NAS SeaweedFS + KEDA/HPA.**

Start and stop it with:

```bash
kubectl config use-context docker-desktop
./hybrid-up.sh
./scripts/hybrid/status.sh
./hybrid-down.sh
```

The three retained Compose files have narrow responsibilities:

- `docker-compose.hybrid-stateful.yml` — PostgreSQL, two Valkey roles, RabbitMQ, Image Edge and database-protection tooling.
- `docker-compose.hybrid-build.yml` — image builds only.
- `docker-compose.hybrid-public-edge.yml` — optional Cloudflare Quick Tunnel connector only.

Stateless user/admin services and workers run in the `mreader-user` and `mreader-admin` Kubernetes namespaces. KEDA/HPA are part of this model. Published media remains on the external NAS SeaweedFS installation.

Full-stack Compose, Helm, generic gateway and platform/multicloud deployment modes were removed from the active repository because they duplicated the working architecture and drifted from current service contracts.
