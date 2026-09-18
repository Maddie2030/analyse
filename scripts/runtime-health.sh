#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for cmd in docker kubectl curl; do command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
./scripts/hybrid/check-data-path.sh --host
user_port="${HYBRID_GATEWAY_PORT:-8080}"
admin_port="${HYBRID_ADMIN_GATEWAY_PORT:-8081}"
curl -fsS --max-time 10 "http://127.0.0.1:${user_port}/healthz" >/dev/null
curl -fsS --max-time 10 "http://127.0.0.1:${admin_port}/healthz" >/dev/null
echo "Runtime health PASSED: hybrid stateful + Kubernetes gateways"
