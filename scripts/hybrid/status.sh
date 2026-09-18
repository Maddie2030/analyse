#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source ./scripts/env/env-lib.sh
env_ensure_healthy .env .env.example
USER_GATEWAY_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_GATEWAY_PORT="${USER_GATEWAY_PORT:-8080}"
ADMIN_GATEWAY_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_GATEWAY_PORT="${ADMIN_GATEWAY_PORT:-8081}"
echo '=== Docker stateful ==='
docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml ps
echo
echo '=== PostgreSQL backup protection ==='
if docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml ps --status running backup_agent 2>/dev/null | grep -q backup_agent; then
  docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml exec -T backup_agent mreader-backup-agent health && echo 'Backup scheduler health: OK' || echo 'Backup scheduler health: STALE/FAILED'
  docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml exec -T backup_agent mreader-backup-agent status || true
else
  echo 'Backup scheduler: not running'
fi
for ns in mreader-user mreader-admin; do
  echo
  echo "=== Kubernetes $ns ==="
  kubectl -n "$ns" get pods,svc,hpa,scaledobject,pvc -o wide 2>/dev/null || true
  echo "--- resource use: $ns ---"
  kubectl top pods -n "$ns" 2>/dev/null || true
done
echo
echo '=== Node resource use ==='
kubectl top nodes 2>/dev/null || true
echo
echo '=== Data path ==='
"$ROOT/scripts/hybrid/check-data-path.sh" --host || true
echo
"$ROOT/scripts/hybrid/public-status.sh" || true
echo
echo "User gateway:  http://127.0.0.1:${USER_GATEWAY_PORT}"
echo "Admin gateway: http://127.0.0.1:${ADMIN_GATEWAY_PORT} (not exposed by public-up.sh)"
