#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
[[ "$(cat VERSION)" == "1.3.0-rc4.84" ]]
for f in namespaces.yaml user-apps.yaml admin-apps.yaml user-hpa.yaml user-keda.yaml admin-keda.yaml resource-guardrails-user.yaml resource-guardrails-admin.yaml external-stateful-user.yaml external-stateful-admin.yaml storage-admin.yaml; do
  [[ -f "deploy/docker-desktop-hybrid/$f" ]]
done
[[ -f deploy/docker-desktop-hybrid/Caddyfile.user && -f deploy/docker-desktop-hybrid/Caddyfile.admin ]]
! [[ -e deploy/docker-desktop-hybrid/apps.yaml ]]
! [[ -e deploy/docker-desktop-hybrid/keda-workers.yaml ]]
grep -q 'name: mreader-user' deploy/docker-desktop-hybrid/namespaces.yaml
grep -q 'name: mreader-admin' deploy/docker-desktop-hybrid/namespaces.yaml
grep -q 'name: user-gateway' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'name: admin-gateway' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'port: 8080' deploy/docker-desktop-hybrid/user-apps.yaml
grep -q 'port: 8081' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/user-apps.yaml
grep -A2 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/user-apps.yaml | grep -q "value: 'false'"
grep -q 'name: catalog-admin' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -A2 'CATALOG_GO_ENABLE_WRITES' deploy/docker-desktop-hybrid/admin-apps.yaml | grep -q "value: 'true'"
grep -q 'http://catalog-admin:8080' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'http://reader-go.mreader-user.svc.cluster.local:8080' deploy/docker-desktop-hybrid/admin-apps.yaml
grep -q 'respond "not found" 404' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q '/api/scraper' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q '/api/upload' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q 'method POST PUT PATCH DELETE' deploy/docker-desktop-hybrid/Caddyfile.user
grep -q 'runtimeConfig.adminPlane' frontend/src/App.tsx
grep -q 'runtimeConfig.adminPlane' frontend/src/components/Navbar.tsx
grep -q 'MREADER_ADMIN_PLANE' frontend/docker-entrypoint.d/40-mreader-runtime-config.sh
grep -q 'mreader-user' scripts/hybrid/public-up.sh
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && [[ -f .env ]]; then
  rendered_public="$(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-public-edge.yml config)"
  grep -Fq 'http://host.docker.internal:8080' <<<"$rendered_public"
  ! grep -Fq 'http://host.docker.internal:8081' <<<"$rendered_public"
else
  # Source-only fallback checks the actual --url target, never comments.
  grep -Eq 'host\.docker\.internal:\$\{HYBRID_GATEWAY_PORT:-8080\}' deploy/compose/docker-compose.hybrid-public-edge.yml
  ! grep -Eq 'host\.docker\.internal:(8081|\$\{HYBRID_ADMIN_GATEWAY_PORT)' deploy/compose/docker-compose.hybrid-public-edge.yml
fi
grep -q 'rabbitmq.mreader-user.svc.cluster.local' scripts/hybrid/deploy.sh
grep -q 'rabbitmq.mreader-admin.svc.cluster.local' scripts/hybrid/deploy.sh
tmp="${TMPDIR:-/tmp}/mreader-twin-plane-refs.$$"
trap 'rm -f "${tmp}".*' EXIT

# Parse only the stable Kubernetes document fields needed for reference checks.
# This intentionally uses POSIX awk so Windows/Git-Bash does not need host Python/PyYAML.
for f in user-apps.yaml admin-apps.yaml; do
  awk '
  function flush(){
    if(kind=="Deployment" && name!="") print ns "/" name >> dfile
    if(kind=="Service" && selapp!="") print ns "/" selapp >> sfile
    kind=name=ns=selapp=""; inmeta=insel=0
  }
  /^---[[:space:]]*$/ {flush(); next}
  /^kind:[[:space:]]*/ {kind=$2; next}
  /^metadata:[[:space:]]*$/ {inmeta=1; next}
  inmeta && /^  name:[[:space:]]*/ {name=$2; next}
  inmeta && /^  namespace:[[:space:]]*/ {ns=$2; inmeta=0; next}
  kind=="Service" && /^  selector:[[:space:]]*$/ {insel=1; next}
  insel && /^    app:[[:space:]]*/ {selapp=$2; insel=0; next}
  END{flush()}
  ' dfile="$tmp.deploy" sfile="$tmp.service" "deploy/docker-desktop-hybrid/$f"
done
sort -u "$tmp.deploy" -o "$tmp.deploy"
sort -u "$tmp.service" -o "$tmp.service"
while IFS= read -r target; do
  grep -Fxq "$target" "$tmp.deploy" || { echo "Service selector targets missing Deployment: $target" >&2; exit 1; }
done < "$tmp.service"

# HPA and KEDA scaleTargetRef names must resolve to a Deployment in the same namespace.
for f in user-hpa.yaml user-keda.yaml admin-keda.yaml; do
  awk '
  function flush(){if((kind=="HorizontalPodAutoscaler"||kind=="ScaledObject")&&ns!=""&&target!="")print ns "/" target;kind=ns=target="";inmeta=0;inscale=0}
  /^---[[:space:]]*$/ {flush();next}
  /^kind:[[:space:]]*/{kind=$2;next}
  /^metadata:[[:space:]]*$/{inmeta=1;next}
  inmeta&&/^  namespace:[[:space:]]*/{ns=$2;inmeta=0;next}
  /^  scaleTargetRef:[[:space:]]*$/{inscale=1;next}
  inscale&&/^    name:[[:space:]]*/{target=$2;inscale=0;next}
  END{flush()}
  ' "deploy/docker-desktop-hybrid/$f" >> "$tmp.targets"
done
sort -u "$tmp.targets" -o "$tmp.targets"
while IFS= read -r target; do
  grep -Fxq "$target" "$tmp.deploy" || { echo "Autoscaler targets missing Deployment: $target" >&2; exit 1; }
done < "$tmp.targets"

echo 'twin-plane object reference regression PASSED'
./tests/regression/twin-plane-resource-budget.sh
echo 'twin-plane static regression PASSED' 
