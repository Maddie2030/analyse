#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
source "$ROOT/scripts/env/env-lib.sh"

for cmd in docker kubectl curl; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo 'ERROR: .env is required' >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == docker-desktop ]] || { echo 'ERROR: kubectl context must be docker-desktop' >&2; exit 2; }

VERSION="$(cat VERSION)"
IMAGE="mreader/browser-tests:${VERSION}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$ROOT/test-results/browser/$RUN_ID"
mkdir -p "$OUT"
test_set_status browser-start "run_id=${RUN_ID} out=${OUT}"
finish(){ local rc=$?; test_set_status finished "mode=browser run_id=${RUN_ID} exit=${rc} out=${OUT}"; }
trap finish EXIT

USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
DB_URL="$(env_get .env DATABASE_URL)"
if [[ -z "$DB_URL" ]]; then DB_URL="postgresql://$(env_get .env POSTGRES_USER):$(env_get .env POSTGRES_PASSWORD)@db:5432/$(env_get .env POSTGRES_DB)"; fi
case "$DB_URL" in
  postgresql+*://*) DB_URL="postgresql://${DB_URL#*://}" ;;
  postgres+*://*) DB_URL="postgres://${DB_URL#*://}" ;;
esac
STATEFUL_NETWORK="$(test_stateful_network)"
USER_URL="http://host.docker.internal:${USER_PORT}"
ADMIN_URL="http://host.docker.internal:${ADMIN_PORT}"

kubectl -n mreader-user rollout status deployment/user-gateway --timeout=120s
kubectl -n mreader-admin rollout status deployment/admin-gateway --timeout=120s
curl -fsS --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz" >/dev/null
curl -fsS --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null

test_section "Building Playwright image: $IMAGE"
docker build --progress=plain -t "$IMAGE" -f tests/browser/Dockerfile .

test_section 'Running browser end-to-end suite against user + admin twin planes'
set +e
run_docker_test mreader-browser-tests "$OUT/playwright.log" \
  --network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway --env-file .env \
  -e "MREADER_BROWSER_BASE_URL=${USER_URL}" \
  -e "MREADER_BROWSER_ADMIN_BASE_URL=${ADMIN_URL}" \
  -e "MREADER_BROWSER_DATABASE_URL=${DB_URL}" \
  -e MREADER_BROWSER_RESULTS_DIR=/results/browser \
  "$IMAGE" ./node_modules/.bin/playwright test --config=playwright.config.mjs
RC=$?
set -e
COPY=PASS
if ! test_copy_results mreader-browser-tests "$OUT"; then COPY=FAIL; [[ $RC -ne 0 ]] || RC=5; fi
if [[ $RC -eq 0 && ! -s "$OUT/browser/playwright-reader.json" ]]; then echo 'ERROR: missing Playwright JSON report' >&2; RC=5; fi
cat > "$OUT/SUMMARY.txt" <<EOF
MReader browser E2E run: $RUN_ID
Version: $VERSION
User plane: $USER_URL
Admin plane: $ADMIN_URL
Status: $([[ $RC -eq 0 ]] && echo PASS || echo FAIL)
Exit: $RC
Artifacts copied: $COPY
EOF
cat "$OUT/SUMMARY.txt"
echo "Browser artifacts: $OUT/browser/artifacts"
exit "$RC"
