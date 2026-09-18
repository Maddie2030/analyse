#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "workload-aware scale-to-zero regression FAILED: $*" >&2; exit 1; }

for f in deploy/docker-desktop-hybrid/admin-keda.yaml deploy/docker-desktop-hybrid/user-keda.yaml; do
  ! grep -q 'protocol: amqp' "$f" || fail "$f still uses AMQP queue-length scaling"
  grep -q 'protocol: http' "$f" || fail "$f missing RabbitMQ management scaling"
  grep -q "excludeUnacknowledged: 'false'" "$f" || fail "$f does not preserve in-flight deliveries"
done

grep -q 'type: postgresql' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'PostgreSQL recovery scaler missing'
grep -q 'name: outbox-relay' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'outbox relay scaler missing'
grep -q 'name: lifecycle-worker' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'lifecycle scaler missing'
grep -q 'event_outbox' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'outbox workload query missing'
grep -q 'lifecycle_cleanup_jobs' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'lifecycle workload query missing'
grep -q 'scraper_storage_attempts' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'scraper recovery query missing storage ledger'
grep -q 'media_operations' deploy/docker-desktop-hybrid/admin-keda.yaml || fail 'media recovery query missing durable operation ledger'

for name in outbox-relay lifecycle-worker; do
  awk -v target="$name" '
    /^---/ {in_dep=0; hit=0}
    /^kind: Deployment/ {in_dep=1}
    in_dep && $1=="name:" && $2==target {hit=1}
    hit && $1=="replicas:" {if($2==0) ok=1; exit}
    END {exit(ok?0:1)}
  ' deploy/docker-desktop-hybrid/admin-apps.yaml || fail "$name is not zero at idle"
done

grep -q 'KEDA_RABBITMQ_HTTP_URL' scripts/hybrid/deploy.sh || fail 'hybrid secret does not derive RabbitMQ management URL'
grep -q 'KEDA_POSTGRES_URL' scripts/hybrid/deploy.sh || fail 'hybrid secret does not derive PostgreSQL KEDA URL'
grep -q 'mreader-keda-metric-check' scripts/hybrid/deploy.sh || fail 'KEDA metric-backend connectivity gate missing'

for name in outbox-relay lifecycle-worker; do
  awk -v target="$name" '
    /^kind: ScaledObject/ {in_so=1; hit=0; fallback=0}
    in_so && $1=="name:" && $2==target {hit=1}
    hit && $1=="fallback:" {fallback=1}
    /^---/ {if(hit){exit(fallback?0:1)}; in_so=0}
    END {if(hit) exit(fallback?0:1)}
  ' deploy/docker-desktop-hybrid/admin-keda.yaml || fail "$name lacks fail-safe KEDA fallback"
done

grep -q 'dedicated KEDA PostgreSQL DSN is missing or invalid' scripts/hybrid/deploy.sh || fail 'dedicated KEDA PostgreSQL URL is not required explicitly'

echo 'workload-aware scale-to-zero regression PASSED'
