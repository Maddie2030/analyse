#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
usage(){ cat <<'EOF'
Usage: ./scripts/logs.sh [all|stateful|user|admin] [workload]

  all       Show recent stateful Compose and both Kubernetes planes (default)
  stateful  Follow Docker Compose logs; optional service name
  user      Follow one user-plane deployment, or show recent logs for all
  admin     Follow one admin-plane deployment, or show recent logs for all
EOF
}
plane_logs(){
  local ns="$1" workload="${2:-}"
  if [[ -n "$workload" ]]; then
    kubectl -n "$ns" logs "deployment/$workload" --all-containers=true --tail=200 -f
    return
  fi
  while IFS= read -r deploy; do
    [[ -n "$deploy" ]] || continue
    echo "===== $ns/$deploy ====="
    kubectl -n "$ns" logs "$deploy" --all-containers=true --tail=100 --prefix=true 2>&1 || true
  done < <(kubectl -n "$ns" get deployment -o name 2>/dev/null || true)
}
scope="${1:-all}"; [[ $# -gt 0 ]] && shift || true
case "$scope" in
  all)
    docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml logs --tail=100 || true
    plane_logs mreader-user
    plane_logs mreader-admin
    ;;
  stateful) docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml logs -f --tail=200 "$@" ;;
  user) plane_logs mreader-user "${1:-}" ;;
  admin) plane_logs mreader-admin "${1:-}" ;;
  -h|--help) usage ;;
  *) echo "ERROR: unknown log scope: $scope" >&2; usage >&2; exit 2 ;;
esac
