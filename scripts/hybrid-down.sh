#!/usr/bin/env bash
# Complete teardown entry point for the Docker Desktop hybrid profile.
#
# Default: remove all running MReader hybrid resources while preserving durable
# Docker volumes and shared cluster add-ons.
# --all: additionally remove local Docker volumes, MReader images, KEDA and
# Metrics Server. External/NAS SeaweedFS is NEVER deleted by this script.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Keep teardown pointed at the same durable volumes selected by hybrid-up.sh.

PURGE_DATA=false
PURGE_IMAGES=false
PURGE_ADDONS=false
ASSUME_YES=false
KEEP_NAMESPACE=false
FAILURES=0

usage() {
  cat <<'USAGE'
Usage: ./hybrid-down.sh [options]

Default teardown:
  Stops Tailscale Funnel / Cloudflare Quick Tunnel, deletes the MReader user/admin
  Kubernetes namespaces and all workloads/HPA/KEDA objects/PVC staging data,
  and stops/removes the hybrid Docker Compose containers/networks.
  PostgreSQL, Valkey, RabbitMQ and image-cache Docker volumes are preserved.
  KEDA, Metrics Server and locally built MReader images are preserved.

Options:
  --all             Full local purge: --purge-data --purge-images --purge-addons
  --purge-data      Also delete hybrid Docker volumes (PostgreSQL/Valkey/
                    RabbitMQ/image cache/backup spool). DOES NOT delete external NAS SeaweedFS.
  --purge-images    Also delete local Docker images whose repository starts mreader/
  --purge-addons    Also uninstall KEDA and Metrics Server from Docker Desktop K8s
  --keep-namespace  Delete MReader resources but keep namespace/PVC staging data
                    (best-effort manifest deletion instead of namespace deletion)
  -y, --yes         Skip destructive confirmation for --purge-data/--all
  -h, --help        Show this help

Examples:
  ./hybrid-down.sh
  ./hybrid-down.sh --all --yes
  ./hybrid-down.sh --purge-data --yes
USAGE
}

while (($#)); do
  case "$1" in
    --all)
      PURGE_DATA=true; PURGE_IMAGES=true; PURGE_ADDONS=true ;;
    --purge-data)
      PURGE_DATA=true ;;
    --purge-images)
      PURGE_IMAGES=true ;;
    --purge-addons)
      PURGE_ADDONS=true ;;
    --keep-namespace)
      KEEP_NAMESPACE=true ;;
    -y|--yes)
      ASSUME_YES=true ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2 ;;
  esac
  shift
done

banner() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
record_failure() { warn "$*"; FAILURES=$((FAILURES + 1)); }

compose() {
  local file="$1"; shift
  if [[ -f .env ]]; then
    docker compose --env-file .env -f "$file" "$@"
  else
    docker compose -f "$file" "$@"
  fi
}

confirm_destructive() {
  $PURGE_DATA || return 0
  $ASSUME_YES && return 0
  cat <<'EOF_CONFIRM'

DANGER: local persistent hybrid data will be deleted:
  - PostgreSQL Docker volume
  - Valkey/Redis Docker volume
  - RabbitMQ Docker volume
  - Image Edge cache volume
  - PostgreSQL backup spool volume (NAS backups remain untouched)
  - Kubernetes scraper-staging PVC (unless --keep-namespace is used)

External/NAS SeaweedFS is NOT touched.
EOF_CONFIRM
  printf 'Type DELETE-LOCAL-DATA to continue: '
  local answer=""
  read -r answer || true
  [[ "$answer" == "DELETE-LOCAL-DATA" ]] || {
    echo "Teardown cancelled; no destructive actions were started."
    exit 3
  }
}

confirm_destructive

banner "MReader Docker Desktop hybrid teardown"

# Never operate against a non-Docker-Desktop Kubernetes cluster.
KUBE_AVAILABLE=false
if command -v kubectl >/dev/null 2>&1; then
  if kubectl config get-contexts -o name 2>/dev/null | grep -Fxq docker-desktop; then
    ctx="$(kubectl config current-context 2>/dev/null || true)"
    if [[ "$ctx" != "docker-desktop" ]]; then
      echo "Switching kubectl context from '${ctx:-<none>}' to docker-desktop"
      if ! kubectl config use-context docker-desktop >/dev/null; then
        record_failure "could not switch kubectl to docker-desktop"
      fi
    fi
    if [[ "$(kubectl config current-context 2>/dev/null || true)" == "docker-desktop" ]]; then
      KUBE_AVAILABLE=true
    fi
  else
    warn "docker-desktop kubectl context is unavailable; Kubernetes teardown will be skipped."
  fi
else
  warn "kubectl is unavailable; Kubernetes teardown will be skipped."
fi

banner "Stopping public development edges"
if [[ -x "$ROOT/scripts/hybrid/public-down.sh" && -f .env ]]; then
  "$ROOT/scripts/hybrid/public-down.sh" --stop-only || record_failure "public-down helper reported an error"
else
  # Best-effort fallback when .env is missing/corrupt.
  TS_BIN=""
  if command -v tailscale >/dev/null 2>&1; then TS_BIN="$(command -v tailscale)"
  elif [[ -x "/c/Program Files/Tailscale/tailscale.exe" ]]; then TS_BIN="/c/Program Files/Tailscale/tailscale.exe"; fi
  [[ -z "$TS_BIN" ]] || "$TS_BIN" funnel --https=443 off >/dev/null 2>&1 || true
fi
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  compose deploy/compose/docker-compose.hybrid-public-edge.yml down --remove-orphans >/dev/null 2>&1 || \
    record_failure "could not fully remove the Cloudflare hybrid public-edge Compose project"
else
  warn "Docker Engine is unavailable; Docker teardown will be skipped."
fi

if $KUBE_AVAILABLE; then
  if $KEEP_NAMESPACE; then
    banner "Removing twin-plane Kubernetes workloads while preserving namespaces/PVCs"
    for manifest in \
      deploy/docker-desktop-hybrid/user-keda.yaml \
      deploy/docker-desktop-hybrid/admin-keda.yaml \
      deploy/docker-desktop-hybrid/user-hpa.yaml \
      deploy/docker-desktop-hybrid/user-apps.yaml \
      deploy/docker-desktop-hybrid/admin-apps.yaml \
      deploy/docker-desktop-hybrid/external-stateful-user.yaml \
      deploy/docker-desktop-hybrid/external-stateful-admin.yaml \
      deploy/docker-desktop-hybrid/resource-guardrails-user.yaml \
      deploy/docker-desktop-hybrid/resource-guardrails-admin.yaml; do
      [[ -f "$manifest" ]] || continue
      kubectl delete -f "$manifest" --ignore-not-found=true --wait=true || record_failure "failed deleting resources from $manifest"
    done
    kubectl -n mreader-user delete configmap user-gateway-config --ignore-not-found=true >/dev/null 2>&1 || true
    kubectl -n mreader-admin delete configmap admin-gateway-config --ignore-not-found=true >/dev/null 2>&1 || true
    kubectl -n mreader-user delete secret mreader-env mreader-public-edge --ignore-not-found=true >/dev/null 2>&1 || true
    kubectl -n mreader-admin delete secret mreader-env --ignore-not-found=true >/dev/null 2>&1 || true
  else
    banner "Deleting MReader twin-plane Kubernetes namespaces"
    for ns in mreader-user mreader-admin; do
      if kubectl get namespace "$ns" >/dev/null 2>&1; then
        kubectl delete namespace "$ns" --ignore-not-found=true --wait=true --timeout=240s || record_failure "$ns namespace did not delete cleanly"
      else
        echo "Namespace $ns is already absent."
      fi
    done
  fi
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  banner "Stopping Docker Compose stateful services"
    if $PURGE_DATA; then
    compose deploy/compose/docker-compose.hybrid-stateful.yml down -v --remove-orphans || \
      record_failure "stateful Compose project/volumes did not fully remove"
    for v in mreader_pgdata mreader_redis_data mreader_rabbitmq_data mreader_image_cache mreader_backup_spool; do
      docker volume rm -f "$v" >/dev/null 2>&1 || true
    done
  else
    compose deploy/compose/docker-compose.hybrid-stateful.yml down --remove-orphans || \
      record_failure "stateful Compose project did not fully remove"
  fi

  if $PURGE_IMAGES; then
    banner "Removing locally built MReader Docker images"
    mapfile -t images < <(docker image ls --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | awk '$0 ~ /^mreader\// && $0 !~ /:<none>$/ {print}' | sort -u)
    if ((${#images[@]})); then
      docker image rm -f "${images[@]}" || record_failure "one or more MReader images could not be removed"
    else
      echo "No tagged mreader/* images found."
    fi
  fi
fi

if $PURGE_ADDONS && $KUBE_AVAILABLE; then
  banner "Removing hybrid autoscaling add-ons (KEDA + Metrics Server)"
  "$ROOT/scripts/hybrid/uninstall-autoscaling.sh" || record_failure "autoscaling add-on cleanup was incomplete"
fi

banner "Cleaning hybrid runtime files"
rm -f .runtime/hybrid-public-edge.env .runtime/cloudflare-quick.log .runtime/cloudflare-quick.pid 2>/dev/null || true
rmdir .runtime 2>/dev/null || true

banner "Final teardown status"
if $KUBE_AVAILABLE; then
  for ns in mreader-user mreader-admin; do
    if kubectl get namespace "$ns" >/dev/null 2>&1; then
      if $KEEP_NAMESPACE; then
        echo "Kubernetes: namespace $ns retained by request."
      else
        record_failure "namespace $ns still exists"
      fi
    else
      echo "Kubernetes: $ns namespace removed."
    fi
  done
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Docker stateful containers:"
  compose deploy/compose/docker-compose.hybrid-stateful.yml ps -a 2>/dev/null || true
fi

echo
echo "External/NAS SeaweedFS was not modified."
echo "Local durable Docker volumes purged: $PURGE_DATA"
echo "Local mreader/* images purged: $PURGE_IMAGES"
echo "KEDA/Metrics Server purged: $PURGE_ADDONS"

if ((FAILURES)); then
  echo "Hybrid teardown completed with $FAILURES warning/error(s). Review the messages above." >&2
  exit 1
fi

echo "Hybrid teardown completed successfully."
