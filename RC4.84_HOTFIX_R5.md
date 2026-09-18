# RC4.84 Hotfix r5 — Deterministic Legacy Stateful Adoption

This package revision fixes hybrid validation/bootstrap when populated historical
`mreader-hybrid-stateful_*` Docker volumes already contain the real MReader state.

## Recovery-phase policy

For this upgrade/recovery phase, populated legacy volumes are authoritative by
default:

- PostgreSQL: `mreader-hybrid-stateful_pgdata`
- critical Valkey/Redis: `mreader-hybrid-stateful_redis_data`
- RabbitMQ: `mreader-hybrid-stateful_rabbitmq_data`
- Image Edge cache: `mreader-hybrid-stateful_image_cache`
- backup spool: `mreader-hybrid-stateful_backup_spool`

If the corresponding legacy volume is populated/valid, bootstrap pins it in `.env`.
A newly-created canonical `mreader_*` volume does not override historical data merely
because both exist.

Automatic adoption no longer depends on catalog inspection or an ambiguous-volume
operator error. `scripts/hybrid/inspect-postgres-volumes.sh` remains available only as
a manual diagnostic tool.

An operator can deliberately keep a configured canonical choice by setting:

```bash
MREADER_PREFER_LEGACY_STATEFUL_VOLUMES=false
```

## Data extraction before rewiring

After legacy PGDATA is adopted, `scripts/hybrid/stateful-up.sh` creates the verified
pre-upgrade PostgreSQL backup before executing schema migrations. This preserves the
historical catalog/page/decode metadata before the newer schema rewires it.

NAS SeaweedFS objects remain untouched by adoption or backup.
