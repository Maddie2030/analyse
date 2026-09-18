# MReader operator scripts — RC4.84

RC4.84 supports one runtime model: Docker Desktop Kubernetes + hybrid stateful Docker Compose + external NAS SeaweedFS + KEDA/HPA.

## Canonical entry points

- `../hybrid-up.sh` — adopt/reconcile stateful ownership, validate, migrate, build and deploy the hybrid runtime.
- `../hybrid-down.sh` — stop/remove local runtime; preserves durable volumes unless explicitly purged and never deletes NAS data.
- `bootstrap.sh` — create/repair `.env`, generate local token secret, perform one-time stateful-volume adoption and preflight.
- `hybrid/status.sh`, `hybrid/logs.sh` — combined runtime status/logs.
- `migrate.sh`, `migration-status.sh` — current DB migrations.
- `recovery/catalog-restore.sh` — read-only-first catalog-only restore from an opaque verified recovery ID; imports exactly the seven catalog/taxonomy tables after NAS media validation.
- `runtime-health.sh`, `diagnose-scraper-staging.sh` — running hybrid diagnostics.
- `scraper-browser.sh` — optional Chromium scraper worker.
- `hybrid/public-up.sh`, `hybrid/public-down.sh`, `hybrid/public-status.sh` — user-plane dev edges.
- `validate-current-release.sh` — RC4.84 source/release gate.

Historical schema/storage compatibility belongs in `hybrid/adopt-existing-stateful-volumes.sh` and `recovery/`; normal services remain current-only.
