#!/usr/bin/env bash
# Stop old stateless mutation workloads before an in-place schema upgrade.
# Current-version deploy.sh is the only normal path that resumes workloads.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

[[ -f .env ]] || { echo "ERROR: .env is required for migration quiescence." >&2; exit 2; }
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl is required to quiesce mutation workloads before migration." >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required to inspect the legacy Progress stream before migration." >&2; exit 2; }

namespaces=(mreader-user mreader-admin)
existing_namespaces=()
for ns in "${namespaces[@]}"; do
  if kubectl get namespace "$ns" >/dev/null 2>&1; then
    existing_namespaces+=("$ns")
  fi
done

if ((${#existing_namespaces[@]} == 0)); then
  echo "No existing MReader Kubernetes workloads require quiescence."
  exit 0
fi

# Autoscalers must lose authority before replica counts are changed. Otherwise
# HPA/KEDA may recreate an old writer while preservation or migration is active.
for ns in "${existing_namespaces[@]}"; do
  kubectl -n "$ns" delete hpa --all --ignore-not-found=true --wait=true >/dev/null
  if kubectl api-resources --api-group=keda.sh -o name 2>/dev/null | grep -Fxq 'scaledobjects.keda.sh'; then
    kubectl -n "$ns" delete scaledobject --all --ignore-not-found=true --wait=true >/dev/null
  fi
done

scale_non_progress_workloads(){
  local ns deployment
  for ns in "${existing_namespaces[@]}"; do
    while IFS= read -r deployment; do
      [[ -n "$deployment" ]] || continue
      if [[ "$ns" == "mreader-user" && "$deployment" == "progress-go" ]]; then
        continue
      fi
      kubectl -n "$ns" scale deployment "$deployment" --replicas=0 >/dev/null
    done < <(kubectl -n "$ns" get deployment -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  done
}

wait_deployment_zero(){
  local ns="$1" deployment="$2" i replicas
  for ((i=0; i<120; i++)); do
    replicas="$(kubectl -n "$ns" get "$deployment" -o jsonpath='{.status.replicas}' 2>/dev/null || true)"
    replicas="${replicas:-0}"
    [[ "$replicas" == "0" ]] && return 0
    sleep 1
  done
  echo "ERROR: $ns/$deployment did not quiesce to zero replicas." >&2
  return 1
}

wait_non_progress_stopped(){
  local ns deployment
  for ns in "${existing_namespaces[@]}"; do
    while IFS= read -r deployment; do
      [[ -n "$deployment" ]] || continue
      if [[ "$ns" == "mreader-user" && "$deployment" == "progress-go" ]]; then
        continue
      fi
      wait_deployment_zero "$ns" "deployment/$deployment"
    done < <(kubectl -n "$ns" get deployment -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  done
}

redis_scalar(){
  # Usage: redis_scalar COMMAND...
  docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml \
    exec -T redis valkey-cli --raw "$@" 2>/dev/null | tr -d '\r'
}

stream_group_lag(){
  local stream="$1" group="$2"
  redis_scalar XINFO GROUPS "$stream" | awk -v want="$group" '
    $0=="name" { getline n; active=(n==want); next }
    active && $0=="lag" { getline v; print v; exit }
  '
}

drain_legacy_progress(){
  local ns=mreader-user stream group exists pending lag stable=0 i
  kubectl get namespace "$ns" >/dev/null 2>&1 || return 0
  kubectl -n "$ns" get deployment progress-go >/dev/null 2>&1 || return 0

  stream="$(env_get .env PROGRESS_GO_STREAM)"; stream="${stream:-progress:updates}"
  group="$(env_get .env PROGRESS_GO_CONSUMER_GROUP)"; group="${group:-progress-db-writers}"
  exists="$(redis_scalar EXISTS "$stream" | head -n 1)"
  if [[ "$exists" == "0" ]]; then
    echo "Legacy Progress stream is absent; no drain is required."
    return 0
  fi

  # A populated stream without the historical consumer group is ambiguous. Do
  # not guess that its entries are safe to discard before destructive migration.
  lag="$(stream_group_lag "$stream" "$group")"
  if [[ -z "$lag" ]]; then
    echo "ERROR: legacy Progress stream '$stream' exists but consumer group '$group' is missing or has unknown lag." >&2
    return 1
  fi

  kubectl -n "$ns" scale deployment progress-go --replicas=1 >/dev/null
  kubectl -n "$ns" set env deployment/progress-go PROGRESS_GO_DRAIN_LEGACY_STREAM=1 >/dev/null
  kubectl -n "$ns" rollout status deployment/progress-go --timeout=180s >/dev/null

  # Require two consecutive empty observations so a final in-flight delivery is
  # not mistaken for a completed drain.
  for ((i=0; i<180; i++)); do
    pending="$(redis_scalar XPENDING "$stream" "$group" | head -n 1)"
    lag="$(stream_group_lag "$stream" "$group")"
    if [[ "$pending" =~ ^[0-9]+$ && "$lag" =~ ^[0-9]+$ && "$pending" == 0 && "$lag" == 0 ]]; then
      stable=$((stable + 1))
      (( stable >= 2 )) && return 0
    else
      stable=0
    fi
    sleep 1
  done
  echo "ERROR: legacy Progress stream did not drain to pending=0 and lag=0." >&2
  return 1
}

verify_all_deployments_stopped(){
  local ns deployment replicas
  for ns in "${existing_namespaces[@]}"; do
    while IFS= read -r deployment; do
      [[ -n "$deployment" ]] || continue
      replicas="$(kubectl -n "$ns" get "deployment/$deployment" -o jsonpath='{.status.replicas}' 2>/dev/null || true)"
      replicas="${replicas:-0}"
      if [[ "$replicas" != "0" ]]; then
        echo "ERROR: migration quiescence failed: $ns/deployment/$deployment still has status.replicas=$replicas." >&2
        return 1
      fi
    done < <(kubectl -n "$ns" get deployment -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  done
}

scale_non_progress_workloads
wait_non_progress_stopped
drain_legacy_progress
if kubectl get namespace mreader-user >/dev/null 2>&1 && kubectl -n mreader-user get deployment progress-go >/dev/null 2>&1; then
  kubectl -n mreader-user scale deployment progress-go --replicas=0 >/dev/null
  wait_deployment_zero mreader-user deployment/progress-go
fi
verify_all_deployments_stopped

echo "MReader Kubernetes workloads are quiesced for migration. Current-version deploy.sh must resume them after migration."
