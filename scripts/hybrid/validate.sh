#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source ./scripts/env/env-lib.sh
env_ensure_healthy .env .env.example
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" .env)"
export MREADER_DB_PROTECTION_ROOT
./scripts/run-ownership-route-audit.sh
./scripts/run-postgres-role-audit.sh
"$ROOT/scripts/hybrid/python-runtime.sh" -m unittest tests.regression.test_p09_4_readiness_generation -v
for cmd in docker kubectl awk grep; do command -v "$cmd" >/dev/null 2>&1 || { echo "FAIL: $cmd is required" >&2; exit 2; }; done

docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml config -q
docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-build.yml config -q
docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml config -q
echo "compose yaml/schema ok"

for p in \
  deploy/docker-desktop-hybrid/namespaces.yaml \
  deploy/docker-desktop-hybrid/resource-guardrails-user.yaml \
  deploy/docker-desktop-hybrid/resource-guardrails-admin.yaml \
  deploy/docker-desktop-hybrid/external-stateful-user.yaml \
  deploy/docker-desktop-hybrid/external-stateful-admin.yaml \
  deploy/docker-desktop-hybrid/storage-admin.yaml \
  deploy/docker-desktop-hybrid/user-apps.yaml \
  deploy/docker-desktop-hybrid/admin-apps.yaml \
  deploy/docker-desktop-hybrid/user-hpa.yaml \
  deploy/docker-desktop-hybrid/user-keda.yaml \
  deploy/docker-desktop-hybrid/admin-keda.yaml; do
  kubectl apply --dry-run=client -f "$p" >/dev/null
  echo "k8s manifest ok: $p"
done

# Twin-plane invariants.
grep -q 'name: mreader-user' deploy/docker-desktop-hybrid/namespaces.yaml
grep -q 'name: mreader-admin' deploy/docker-desktop-hybrid/namespaces.yaml
grep -q 'namespace: mreader-user' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'namespace: mreader-admin' deploy/docker-desktop-hybrid/admin-apps.yaml
! grep -q 'namespace: mreader$' deploy/docker-desktop-hybrid/user-apps.yaml
! grep -q 'namespace: mreader$' deploy/docker-desktop-hybrid/admin-apps.yaml

grep -q 'name: user-gateway' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'port: 8080' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'name: admin-gateway' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'port: 8081' deploy/docker-desktop-hybrid/admin-apps.yaml

grep -q 'respond "not found" 404' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q '/api/scraper' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q '/api/upload' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q 'method POST PUT PATCH DELETE' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q 'catalog-admin:8080' deploy/docker-desktop-hybrid/Caddyfile.admin
grep -q 'catalog-go.mreader-user.svc.cluster.local:8080' deploy/docker-desktop-hybrid/Caddyfile.admin

grep -q 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/user-apps.yaml
grep -A1 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/user-apps.yaml | grep -q "value: 'false'"
grep -q 'name: catalog-admin' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -A1 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/admin-apps.yaml | grep -q "value: 'true'"
grep -q 'http://catalog-admin:8080' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'http://reader-go.mreader-user.svc.cluster.local:8080' deploy/docker-desktop-hybrid/admin-apps.yaml

grep -q 'MREADER_ADMIN_PLANE' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'MREADER_ADMIN_PLANE' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'runtimeConfig.adminPlane' frontend/src/App.tsx
grep -q 'runtimeConfig.adminPlane' frontend/src/components/Navbar.tsx

# Public edge remains user-only. Validate the *rendered* Compose command, not raw
# source text/comments. RC4.33 incorrectly grepped the raw YAML and failed on a
# safety comment that merely mentioned the admin port.
public_rendered="$(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml config)"
user_port="$(env_get .env HYBRID_GATEWAY_PORT)"; user_port="${user_port:-8080}"
admin_port="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; admin_port="${admin_port:-8081}"
[[ "$user_port" =~ ^[0-9]+$ && "$admin_port" =~ ^[0-9]+$ ]] || { echo 'FAIL: gateway ports must be numeric' >&2; exit 1; }
[[ "$user_port" != "$admin_port" ]] || { echo 'FAIL: user and admin gateway ports must differ' >&2; exit 1; }
[[ "$user_port" == "8080" ]] || { echo "FAIL: HYBRID_GATEWAY_PORT must be 8080 for the static user Service (got $user_port)" >&2; exit 1; }
[[ "$admin_port" == "8081" ]] || { echo "FAIL: HYBRID_ADMIN_GATEWAY_PORT must be 8081 for the static admin Service (got $admin_port)" >&2; exit 1; }
grep -Fq "http://host.docker.internal:${user_port}" <<<"$public_rendered" || { echo 'FAIL: public connector does not target configured user gateway' >&2; exit 1; }
! grep -Fq "http://host.docker.internal:${admin_port}" <<<"$public_rendered" || { echo 'FAIL: public connector targets admin gateway' >&2; exit 1; }
grep -q 'mreader-user' scripts/hybrid/public-up.sh
! grep -q 'mreader-admin.*cloudflare\|mreader-admin.*funnel' scripts/hybrid/public-up.sh || { echo 'FAIL: admin plane exposed by public-up' >&2; exit 1; }

# KEDA is plane-local while shared RabbitMQ is referenced by FQDN.
grep -q 'namespace: mreader-user' deploy/docker-desktop-hybrid/user-keda.yaml
grep -q 'namespace: mreader-admin' deploy/docker-desktop-hybrid/admin-keda.yaml
grep -q 'rabbitmq.mreader-user.svc.cluster.local' scripts/hybrid/deploy.sh
grep -q 'rabbitmq.mreader-admin.svc.cluster.local' scripts/hybrid/deploy.sh

# Preserve critical backup and concurrency regressions from RC4.32.
grep -q 'backup_agent:' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'POSTGRES_BACKUP_DAILY_RETENTION_DAYS:-4' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS:-2' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'scraper-stage-series:{target_series_id}' services/scraper_service/app/series_drafts.py
grep -q 'scraper-publish:series:{published_series_id}' services/scraper_service/app/series_drafts.py
./tests/regression/hybrid-volume-ownership.sh
./tests/regression/hybrid-volume-adoption-runtime.sh
./tests/regression/hybrid-legacy-volume-priority.sh
./tests/regression/hybrid-legacy-volume-authority.sh
./tests/regression/hybrid-preupgrade-backup-order.sh
./tests/regression/hybrid-restore-generation-initialization.sh
./tests/regression/hybrid-pg-volume-inspection-static.sh
./tests/regression/bootstrap-fresh-env.sh
./tests/regression/rc484-upgrade-recovery-static.sh
./tests/regression/twin-plane-resource-budget.sh
./tests/regression/dependency-pins.sh
./tests/regression/dockerfile-static.sh
./tests/regression/hybrid-no-host-python.sh
./tests/regression/workload-aware-scale-to-zero.sh

echo "twin-plane hybrid static validation passed"
