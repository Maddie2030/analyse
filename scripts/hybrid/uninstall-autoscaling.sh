#!/usr/bin/env bash
# Best-effort removal of the cluster-level add-ons installed by install-autoscaling.sh.
set -uo pipefail
readonly METRICS_SERVER_VERSION="v0.9.0"
readonly KEDA_VERSION="2.20.1"
FAIL=0

if [[ "$(kubectl config current-context 2>/dev/null || true)" != "docker-desktop" ]]; then
  echo "ERROR: refusing to uninstall autoscaling add-ons outside docker-desktop context." >&2
  exit 2
fi

# Prefer deleting the exact pinned manifests so all cluster-scoped RBAC/webhooks/
# APIService/CRDs are removed. Fall back to known resource discovery if network
# access to GitHub is unavailable during teardown.
if ! kubectl delete --ignore-not-found=true --wait=true \
  -f "https://github.com/kedacore/keda/releases/download/v${KEDA_VERSION}/keda-${KEDA_VERSION}.yaml"; then
  echo "WARNING: remote KEDA manifest deletion failed; using local best-effort cleanup." >&2
  kubectl delete namespace keda --ignore-not-found=true --wait=true || FAIL=1
  mapfile -t keda_crds < <(kubectl get crd -o name 2>/dev/null | grep 'keda\.sh$' || true)
  ((${#keda_crds[@]} == 0)) || kubectl delete "${keda_crds[@]}" --ignore-not-found=true || FAIL=1
  kubectl delete apiservice v1beta1.external.metrics.k8s.io --ignore-not-found=true || true
  kubectl delete validatingwebhookconfiguration keda-admission --ignore-not-found=true || true
  kubectl delete clusterrole keda-external-metrics-reader keda-operator --ignore-not-found=true || true
  kubectl delete clusterrolebinding keda-hpa-controller-external-metrics keda-operator keda-system-auth-delegator --ignore-not-found=true || true
fi

if ! kubectl delete --ignore-not-found=true --wait=true \
  -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml"; then
  echo "WARNING: remote Metrics Server manifest deletion failed; using local best-effort cleanup." >&2
  kubectl -n kube-system delete deployment metrics-server --ignore-not-found=true || FAIL=1
  kubectl -n kube-system delete service metrics-server --ignore-not-found=true || true
  kubectl -n kube-system delete serviceaccount metrics-server --ignore-not-found=true || true
  kubectl -n kube-system delete rolebinding metrics-server-auth-reader --ignore-not-found=true || true
  kubectl delete apiservice v1beta1.metrics.k8s.io --ignore-not-found=true || true
  kubectl delete clusterrole system:aggregated-metrics-reader system:metrics-server --ignore-not-found=true || true
  kubectl delete clusterrolebinding metrics-server:system:auth-delegator system:metrics-server --ignore-not-found=true || true
fi

exit "$FAIL"
