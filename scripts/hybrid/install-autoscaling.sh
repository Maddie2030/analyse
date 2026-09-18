#!/usr/bin/env bash
set -euo pipefail
# Pinned versions verified for current Docker Desktop-era Kubernetes releases.
readonly METRICS_SERVER_VERSION="v0.9.0"
readonly KEDA_VERSION="2.20.1"
kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml"
# Docker Desktop kubelets use certificates that commonly are not trusted by metrics-server.
kubectl -n kube-system patch deployment metrics-server --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' 2>/dev/null || true
kubectl rollout status -n kube-system deployment/metrics-server --timeout=180s
kubectl apply --server-side -f "https://github.com/kedacore/keda/releases/download/v${KEDA_VERSION}/keda-${KEDA_VERSION}.yaml"
kubectl rollout status -n keda deployment/keda-operator --timeout=240s
kubectl rollout status -n keda deployment/keda-metrics-apiserver --timeout=240s
kubectl rollout status -n keda deployment/keda-admission --timeout=240s
