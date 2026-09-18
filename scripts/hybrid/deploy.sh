#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source ./scripts/env/env-lib.sh
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"
[[ -f .env ]] || { echo "ERROR: .env is required." >&2; exit 2; }
env_ensure_healthy .env .env.example
for cmd in docker kubectl awk sed curl; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found" >&2; exit 2; }; done
ctx="$(kubectl config current-context 2>/dev/null || true)"
[[ "$ctx" == "docker-desktop" ]] || { echo "ERROR: kubectl context is '$ctx'; switch to docker-desktop" >&2; exit 2; }
kubectl get node docker-desktop >/dev/null 2>&1 || { echo "ERROR: Docker Desktop Kubernetes is not ready." >&2; exit 2; }

dotenv_get(){ env_get .env "$1"; }
NAS_SEAWEEDFS_HOST="$(dotenv_get NAS_SEAWEEDFS_HOST)"
NAS_SEAWEEDFS_PORT="$(dotenv_get NAS_SEAWEEDFS_PORT)"; NAS_SEAWEEDFS_PORT="${NAS_SEAWEEDFS_PORT:-8888}"
RECOVERY_BRIDGE_PORT="$(dotenv_get HYBRID_RECOVERY_BRIDGE_PORT)"; RECOVERY_BRIDGE_PORT="${RECOVERY_BRIDGE_PORT:-18084}"
: "${NAS_SEAWEEDFS_HOST:?ERROR: set NAS_SEAWEEDFS_HOST in .env}"

"$ROOT/scripts/hybrid/stateful-up.sh" core
"$ROOT/scripts/hybrid/check-data-path.sh" --host
DEPLOYMENT_GENERATION="$("$ROOT/scripts/hybrid/p09-4-readiness.sh" .env --print-token)"
[[ "$DEPLOYMENT_GENERATION" == p094-* ]] || {
  echo "ERROR: P09.4 readiness did not return a deployment generation." >&2
  exit 2
}
"$ROOT/scripts/hybrid/init-rabbitmq-topology.sh"
"$ROOT/scripts/hybrid/build-images.sh"

kubectl apply -f deploy/docker-desktop-hybrid/namespaces.yaml

# Build one explicit environment Secret per workload. Scope files are exact
# allowlists: adding a value to .env does not make it visible to any pod until
# that workload opts in. This is the prerequisite boundary for future private
# Catalog-command and recovery-bridge credentials.
mkdir -p .runtime
GENERATION_MANIFEST_DIR=".runtime/p09-4-manifests.$$"
runtime_env_files=()
cleanup_env_files(){
  if (( ${#runtime_env_files[@]} )); then rm -f "${runtime_env_files[@]}"; fi
  runtime_env_files=()
}
cleanup_runtime(){
  cleanup_env_files
  rm -rf -- "$GENERATION_MANIFEST_DIR"
}
trap cleanup_runtime EXIT

scope_has_key(){
  local scope="$1" key="$2"
  grep -Fxq "$key" "$scope"
}
set_if_scoped(){
  local file="$1" scope="$2" key="$3" value="$4"
  scope_has_key "$scope" "$key" || return 0
  env_set "$file" "$key" "$value"
}

# KEDA runs outside the application namespaces. RabbitMQ URLs exposed by a
# scaled target therefore use namespace-qualified service names.
RABBITMQ_URL="$(dotenv_get RABBITMQ_URL)"
user_rmq="$RABBITMQ_URL"
admin_rmq="$RABBITMQ_URL"
if [[ -n "$RABBITMQ_URL" ]]; then
  user_rmq="$(printf '%s' "$RABBITMQ_URL" | sed -E 's/@rabbitmq([^:/]*)?(:[0-9]+)?\//@rabbitmq.mreader-user.svc.cluster.local\2\//')"
  admin_rmq="$(printf '%s' "$RABBITMQ_URL" | sed -E 's/@rabbitmq([^:/]*)?(:[0-9]+)?\//@rabbitmq.mreader-admin.svc.cluster.local\2\//')"
fi

RABBITMQ_VHOST="$(dotenv_get RABBITMQ_VHOST)"; RABBITMQ_VHOST="${RABBITMQ_VHOST:-mreader}"
case "$RABBITMQ_VHOST" in
  *[!A-Za-z0-9._~-]*) echo "ERROR: hybrid KEDA currently requires a URL-safe RABBITMQ_VHOST (got '$RABBITMQ_VHOST')." >&2; exit 2 ;;
esac
RABBITMQ_MGMT_PORT="$(dotenv_get HYBRID_RABBITMQ_MANAGEMENT_PORT)"; RABBITMQ_MGMT_PORT="${RABBITMQ_MGMT_PORT:-15672}"
user_keda_rmq="http://rabbitmq.mreader-user.svc.cluster.local:${RABBITMQ_MGMT_PORT}/${RABBITMQ_VHOST}"
admin_keda_rmq="http://rabbitmq.mreader-admin.svc.cluster.local:${RABBITMQ_MGMT_PORT}/${RABBITMQ_VHOST}"

POSTGRES_ROLE_CONTRACT="$ROOT/contracts/ownership/postgres-roles.v1.json"
KEDA_ROLE_DSN_KEY="MREADER_DB_DSN_MREADER_KEDA_METRICS"
keda_pg="$(dotenv_get "$KEDA_ROLE_DSN_KEY")"
[[ "$keda_pg" == postgresql://* ]] || { echo "ERROR: dedicated KEDA PostgreSQL DSN is missing or invalid; run stateful role reconciliation first." >&2; exit 2; }

postgres_contract_row(){
  local workload="$1"
  "$PYTHON_RUNTIME" - "$POSTGRES_ROLE_CONTRACT" "$workload" <<'PYROW'
import json, sys
contract=json.load(open(sys.argv[1], encoding='utf-8'))
workload=sys.argv[2]
for row in contract['workloads']:
    if row['workload'] == workload:
        print(f"{row['role']}\t{row['dsn_env']}")
        break
PYROW
}

create_workload_secret(){
  local ns="$1" workload="$2" scope file rmq keda_rmq db_row db_role dsn_env role_upper dsn_key workload_db_dsn
  scope="deploy/docker-desktop-hybrid/env-scopes/${workload}.keys"
  [[ -f "$scope" ]] || { echo "ERROR: missing workload env scope: $scope" >&2; exit 2; }
  file=".runtime/mreader-env-${ns}-${workload}.$$"
  "$ROOT/scripts/hybrid/render-workload-env.sh" .env "$scope" "$file"
  runtime_env_files+=("$file")

  db_row="$(postgres_contract_row "$workload")"
  if [[ -n "$db_row" ]]; then
    IFS=$'\t' read -r db_role dsn_env <<<"$db_row"
    role_upper="$(printf '%s' "$db_role" | tr '[:lower:]' '[:upper:]')"
    dsn_key="MREADER_DB_DSN_${role_upper}"
    workload_db_dsn="$(dotenv_get "$dsn_key")"
    [[ "$workload_db_dsn" == postgresql://* ]] || { echo "ERROR: missing dedicated PostgreSQL DSN for $workload ($dsn_key); run stateful role reconciliation first." >&2; exit 2; }
    set_if_scoped "$file" "$scope" "$dsn_env" "$workload_db_dsn"
  fi

  if [[ "$ns" == "mreader-user" ]]; then
    rmq="$user_rmq"; keda_rmq="$user_keda_rmq"
  else
    rmq="$admin_rmq"; keda_rmq="$admin_keda_rmq"
  fi
  [[ -n "$rmq" ]] && set_if_scoped "$file" "$scope" RABBITMQ_URL "$rmq"
  set_if_scoped "$file" "$scope" KEDA_RABBITMQ_HTTP_URL "$keda_rmq"
  set_if_scoped "$file" "$scope" KEDA_POSTGRES_URL "$keda_pg"
  set_if_scoped "$file" "$scope" NAS_SEAWEEDFS_HOST "$NAS_SEAWEEDFS_HOST"
  set_if_scoped "$file" "$scope" NAS_SEAWEEDFS_PORT "$NAS_SEAWEEDFS_PORT"
  set_if_scoped "$file" "$scope" SEAWEEDFS_FILER_URL "http://${NAS_SEAWEEDFS_HOST}:${NAS_SEAWEEDFS_PORT}"
  set_if_scoped "$file" "$scope" RECOVERY_BRIDGE_INTERNAL_URL "http://host.docker.internal:${RECOVERY_BRIDGE_PORT}"

  kubectl -n "$ns" create secret generic "mreader-env-${workload}" \
    --from-env-file="$file" --dry-run=client -o yaml | kubectl apply -f -
}

user_workloads=(auth-service catalog-go reader-go progress-go social-ts frontend notification-worker realtime-go)
admin_workloads=(scraper-service image-service outbox-relay scraper-batch-worker scraper-series-worker media-worker media-thumbnail-worker lifecycle-worker scraper-browser admin-frontend auth-admin catalog-admin)
for workload in "${user_workloads[@]}"; do create_workload_secret mreader-user "$workload"; done
for workload in "${admin_workloads[@]}"; do create_workload_secret mreader-admin "$workload"; done
cleanup_env_files

"$ROOT/scripts/hybrid/sync-public-edge-secret.sh" --no-rollout
kubectl -n mreader-user create configmap user-gateway-config --from-file=Caddyfile=deploy/docker-desktop-hybrid/Caddyfile.user --dry-run=client -o yaml | kubectl apply -f -
kubectl -n mreader-admin create configmap admin-gateway-config --from-file=Caddyfile=deploy/docker-desktop-hybrid/Caddyfile.admin --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f deploy/docker-desktop-hybrid/external-stateful-user.yaml
kubectl apply -f deploy/docker-desktop-hybrid/external-stateful-admin.yaml

connectivity_check(){
  local ns="$1"; shift
  local ports="$*"
  kubectl -n "$ns" delete pod hybrid-connectivity-check --ignore-not-found --wait=true --timeout=30s >/dev/null 2>&1 || true
  cat <<POD | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata: {name: hybrid-connectivity-check, namespace: $ns}
spec:
  restartPolicy: Never
  enableServiceLinks: false
  containers:
  - name: check
    image: busybox:1.37.0
    command: ["sh","-c","for p in $ports; do nc -z -w 3 host.docker.internal \"\$p\" || exit 10; done"]
    resources:
      requests: {cpu: 5m, memory: 8Mi}
      limits: {cpu: 50m, memory: 32Mi}
POD
  kubectl -n "$ns" wait --for=jsonpath='{.status.phase}'=Succeeded pod/hybrid-connectivity-check --timeout=60s >/dev/null || { kubectl -n "$ns" logs hybrid-connectivity-check || true; echo "ERROR: $ns cannot reach required host services" >&2; exit 3; }
  kubectl -n "$ns" delete pod hybrid-connectivity-check --wait=false >/dev/null 2>&1 || true
}
connectivity_check mreader-user 5432 6379 5672
connectivity_check mreader-admin 5432 6379 5672 "$RECOVERY_BRIDGE_PORT"

keda_metric_connectivity_check(){
  kubectl -n keda delete pod mreader-keda-metric-check --ignore-not-found --wait=true --timeout=30s >/dev/null 2>&1 || true
  cat <<'POD' | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata: {name: mreader-keda-metric-check, namespace: keda}
spec:
  restartPolicy: Never
  enableServiceLinks: false
  containers:
  - name: check
    image: busybox:1.37.0
    command: ["sh","-c","nc -z -w 3 host.docker.internal 5432 && nc -z -w 3 host.docker.internal 15672"]
    resources:
      requests: {cpu: 5m, memory: 8Mi}
      limits: {cpu: 50m, memory: 32Mi}
POD
  kubectl -n keda wait --for=jsonpath='{.status.phase}'=Succeeded pod/mreader-keda-metric-check --timeout=60s >/dev/null || { kubectl -n keda logs mreader-keda-metric-check || true; echo "ERROR: KEDA cannot reach PostgreSQL/RabbitMQ management endpoints" >&2; return 3; }
  kubectl -n keda delete pod mreader-keda-metric-check --wait=false >/dev/null 2>&1 || true
}
"$ROOT/scripts/hybrid/check-data-path.sh" --kubernetes

mkdir -p "$GENERATION_MANIFEST_DIR"
"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-generation-manifests.py" \
  --contract "$POSTGRES_ROLE_CONTRACT" \
  --generation "$DEPLOYMENT_GENERATION" \
  --input "$ROOT/deploy/docker-desktop-hybrid/user-apps.yaml" \
  --input "$ROOT/deploy/docker-desktop-hybrid/admin-apps.yaml" \
  --output-dir "$GENERATION_MANIFEST_DIR"

DB_DEPLOYMENT_INDEX="$GENERATION_MANIFEST_DIR/database-workloads.tsv"
echo "==> Indexing P09.4 database workload manifests"
"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-db-deployment-index.py" \
  --contract "$POSTGRES_ROLE_CONTRACT" \
  --manifest "$GENERATION_MANIFEST_DIR/user-apps.yaml" \
  --manifest "$GENERATION_MANIFEST_DIR/admin-apps.yaml" >"$DB_DEPLOYMENT_INDEX"
echo "==> P09.4 database workload index ready"

kubectl apply -f deploy/docker-desktop-hybrid/resource-guardrails-user.yaml
kubectl apply -f deploy/docker-desktop-hybrid/resource-guardrails-admin.yaml
kubectl apply -f deploy/docker-desktop-hybrid/storage-admin.yaml
kubectl apply -f "$GENERATION_MANIFEST_DIR/user-apps.yaml"
kubectl apply -f "$GENERATION_MANIFEST_DIR/admin-apps.yaml"

rollout(){ local ns="$1" d="$2"; if ! kubectl -n "$ns" rollout status "deployment/$d" --timeout=240s; then kubectl -n "$ns" get pods -l app="$d" -o wide >&2 || true; kubectl -n "$ns" logs deployment/"$d" --all-containers --tail=120 >&2 || true; kubectl -n "$ns" get events --sort-by=.lastTimestamp | tail -n 60 >&2 || true; exit 4; fi; }
for d in auth-service catalog-go reader-go progress-go social-ts frontend realtime-go user-gateway; do rollout mreader-user "$d"; done
for d in auth-admin catalog-admin scraper-service image-service admin-frontend admin-gateway; do rollout mreader-admin "$d"; done

verify_all_db_workload_generations(){
  local ns workload live_generation
  while IFS=$'\t' read -r ns workload; do
    [[ -n "$ns" && -n "$workload" ]] || continue
    live_generation="$(kubectl -n "$ns" get deployment "$workload" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MREADER_DEPLOYMENT_GENERATION")].value}')"
    [[ "$live_generation" == "$DEPLOYMENT_GENERATION" ]] || {
      echo "ERROR: rollout-failed: $ns/$workload missing current deployment generation" >&2
      return 4
    }
  done < "$DB_DEPLOYMENT_INDEX"
}
verify_all_db_workload_generations || exit $?

autoscaling_fail(){ echo "ERROR: autoscaling-not-restored: $*" >&2; exit 5; }
"$ROOT/scripts/hybrid/install-autoscaling.sh" || autoscaling_fail "KEDA installation failed"
kubectl apply -f deploy/docker-desktop-hybrid/user-hpa.yaml || autoscaling_fail "user HPA apply failed"
kubectl apply -f deploy/docker-desktop-hybrid/user-keda.yaml || autoscaling_fail "user KEDA apply failed"
kubectl apply -f deploy/docker-desktop-hybrid/admin-keda.yaml || autoscaling_fail "admin KEDA apply failed"
keda_metric_connectivity_check || autoscaling_fail "KEDA metric connectivity failed"

for ns in mreader-user mreader-admin; do
  if kubectl -n "$ns" get scaledobject >/dev/null 2>&1 && [[ -n "$(kubectl -n "$ns" get scaledobject -o name 2>/dev/null)" ]]; then
    kubectl -n "$ns" wait --for=condition=Ready scaledobject --all --timeout=120s || { kubectl -n "$ns" describe scaledobject >&2 || true; autoscaling_fail "$ns ScaledObject readiness failed"; }
  fi
done

# Retire the legacy namespace-wide Secret only after workloads/ScaledObjects have
# accepted their scoped replacements. Existing processes already hold their env;
# future starts can no longer resolve the broad credential bundle.
kubectl -n mreader-user delete secret mreader-env --ignore-not-found >/dev/null
kubectl -n mreader-admin delete secret mreader-env --ignore-not-found >/dev/null

kubectl -n mreader-user get service reader-go-edge-auth >/dev/null
"$ROOT/scripts/hybrid/stateful-up.sh" edge
curl -fsS --max-time 10 "http://127.0.0.1:${HYBRID_IMAGE_EDGE_PORT:-18081}/ready" >/dev/null || { echo "ERROR: Image Edge not ready" >&2; exit 6; }

echo
echo "MReader twin-plane hybrid profile is deployed."
USER_GATEWAY_PORT="$(dotenv_get HYBRID_GATEWAY_PORT)"; USER_GATEWAY_PORT="${USER_GATEWAY_PORT:-8080}"
ADMIN_GATEWAY_PORT="$(dotenv_get HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_GATEWAY_PORT="${ADMIN_GATEWAY_PORT:-8081}"
echo "User gateway:  http://localhost:${USER_GATEWAY_PORT}"
echo "Admin gateway: http://localhost:${ADMIN_GATEWAY_PORT} (local/private only; not sent through public tunnels)"
echo "Shared stateful: PostgreSQL + Valkey + RabbitMQ + NAS SeaweedFS"
