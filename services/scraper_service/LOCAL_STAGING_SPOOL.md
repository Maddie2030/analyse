# Scraper staging ownership — Current MReader

Unpublished scraper bytes have one owner: the `scraper-staging` persistent volume mounted by the admin-plane scraper API/workers.

PostgreSQL draft/storage-attempt rows may reference staged files only when those files exist on this current PVC. Current MReader does not search previous host spools, reconstruct missing staged files from source URLs, or auto-adopt another spool.

Operational consequences:

- A missing PostgreSQL-referenced staged file is a staging-integrity failure.
- Publication/preflight must fail visibly rather than silently changing storage ownership.
- Power interruption is recovered from the same durable PVC plus PostgreSQL workflow state.
- If the PVC is intentionally destroyed during testing, affected unpublished work must be re-scraped/re-uploaded.
- Published pages/covers are separate and live on external NAS SeaweedFS.

Use:

```bash
./scripts/diagnose-scraper-staging.sh
./scripts/hybrid/status.sh
```

to inspect the current staging deployment.
