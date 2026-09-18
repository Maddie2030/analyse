#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "diagnostics evidence static regression FAILED: $*" >&2; exit 1; }
F=scripts/diagnostics/collect-runtime-evidence.sh
grep -Fq 'set +e' "$F" || fail 'collector must disable errexit after sourcing shared env helpers'
[[ -x "$F" ]] || fail 'collector missing or not executable'
grep -Fq 'mreader-user mreader-admin' "$F" || fail 'collector does not cover both MReader namespaces'
grep -Fq 'get pods' "$F" || fail 'pod inventory missing'
grep -Fq 'describe pod' "$F" || fail 'pod describe capture missing'
grep -Fq -- '--previous' "$F" || fail 'previous pod logs are not attempted'
grep -Fq 'get events' "$F" || fail 'Kubernetes event capture missing'
grep -Fq 'get hpa' "$F" || fail 'HPA capture missing'
grep -Fq 'get scaledobjects' "$F" || fail 'KEDA ScaledObject capture missing'
grep -Fq 'docker stats --no-stream' "$F" || fail 'Docker stats capture missing'
! grep -Fq 'docker inspect "$cid"' "$F" || fail 'raw docker inspect may expose container environment secrets'
grep -Fq '{{json .State}}' "$F" || fail 'restricted docker state inspect missing'
grep -Fq 'docker compose' "$F" || fail 'Docker Compose capture missing'
! grep -Eq 'kubectl[^\n]*get[[:space:]]+secrets?([^[:alnum:]_-]|$).*(-o|--output)[=[:space:]]*(yaml|json)' "$F" || fail 'collector must never dump raw Kubernetes Secret objects'
grep -Fq 'collector-errors.tsv' "$F" || fail 'collector error ledger missing'
grep -Fq 'collect-runtime-evidence.sh' scripts/diagnostics/run-diagnostics.sh || fail 'host runner does not invoke runtime collector'
grep -Fq '.host-post-capture-done' scripts/diagnostics/run-diagnostics.sh || fail 'host post-capture sentinel missing'
echo 'diagnostics evidence static regression PASS'
