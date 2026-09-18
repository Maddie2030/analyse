#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
source "$ROOT/scripts/env/env-lib.sh"

PYTEST_MODULE=""
PYTEST_MARKER="not external"
EXTERNAL_ENV="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pytest-only) shift ;; # retained for stable top-level/internal callers
    --keep-test-data) shift ;; # pytest owns/cleans its fixture data independently
    --pytest-module) PYTEST_MODULE="${2:?module required}"; shift 2 ;;
    --external-only) PYTEST_MARKER="external"; EXTERNAL_ENV="true"; shift ;;
    -h|--help)
      cat <<'HELP'
Usage: ./scripts/run-hybrid-tests.sh [--pytest-only] [--pytest-module FILE] [--external-only]

Runs the pytest correctness/integration suite as an ordinary Docker container
against the CURRENT Docker Desktop twin-plane deployment.

Capacity/load testing is intentionally NOT mixed into this runner. Use:
  ./test-mreader.sh --capacity
  ./test-mreader.sh --capacity-deep
  ./test-mreader.sh --workload NAME
for isolated gradual k6 breakpoint discovery.
HELP
      exit 0 ;;
    *) echo "ERROR: unknown option $1" >&2; exit 2 ;;
  esac
done

for cmd in docker kubectl sed awk grep; do
  command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }
done
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
if [[ "$EXTERNAL_ENV" == "true" && -z "$(env_get .env SCRAPER_TEST_SERIES_URL)" && -z "$(env_get .env SCRAPER_TEST_CHAPTER_URL)" ]]; then
  echo "ERROR: --external-only requires SCRAPER_TEST_SERIES_URL and/or SCRAPER_TEST_CHAPTER_URL in .env" >&2
  exit 2
fi
[[ "$(kubectl config current-context 2>/dev/null || true)" == "docker-desktop" ]] || {
  echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2;
}

VERSION="$(cat VERSION)"
API_IMAGE="mreader/api-tests:${VERSION}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$ROOT/test-results/hybrid/$RUN_ID"
mkdir -p "$OUT"
test_set_status "starting" "mode=docker-pytest run_id=${RUN_ID} out=${OUT}"
finish_test_status(){ local rc=$?; test_set_status "finished" "mode=docker-pytest run_id=${RUN_ID} exit=${rc} out=${OUT}"; }
trap finish_test_status EXIT

say(){ test_section "$*"; }

USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
NAS_HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"
NAS_PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
DB_URL="$(env_get .env DATABASE_URL)"
if [[ -z "$DB_URL" ]]; then
  DB_URL="postgresql://$(env_get .env POSTGRES_USER):$(env_get .env POSTGRES_PASSWORD)@db:5432/$(env_get .env POSTGRES_DB)"
fi
[[ -n "$NAS_HOST" ]] || { echo "ERROR: NAS_SEAWEEDFS_HOST is required" >&2; exit 2; }
STATEFUL_NETWORK="$(test_stateful_network)"
USER_URL="http://host.docker.internal:${USER_PORT}"
ADMIN_URL="http://host.docker.internal:${ADMIN_PORT}"
FILER_URL="http://${NAS_HOST}:${NAS_PORT}"

DOCKER_TEST_ENV=(
  --network "$STATEFUL_NETWORK"
  --add-host host.docker.internal:host-gateway
  --env-file .env
  -e "TEST_USER_BASE_URL=${USER_URL}"
  -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}"
  -e "TEST_DATABASE_URL=${DB_URL}"
  -e "TEST_SEAWEEDFS_FILER_URL=${FILER_URL}"
  -e "RUN_EXTERNAL_SCRAPER_TESTS=${EXTERNAL_ENV}"
)

say "Checking current twin-plane deployment"
test_set_status "preflight" "checking host gateways and stateful services"
kubectl -n mreader-user rollout status deployment/user-gateway --timeout=120s
kubectl -n mreader-admin rollout status deployment/admin-gateway --timeout=120s
curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz" >/dev/null || { echo "ERROR: user gateway unavailable at localhost:${USER_PORT}" >&2; exit 2; }
curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null || { echo "ERROR: admin gateway unavailable at localhost:${ADMIN_PORT}" >&2; exit 2; }
test_log "Docker stateful network: $STATEFUL_NETWORK"
test_log "Docker test route -> user gateway: $USER_URL"
test_log "Docker test route -> admin gateway: $ADMIN_URL"
test_log "Docker test route -> NAS filer: $FILER_URL"

test_set_status "building-image" "image=${API_IMAGE}"
say "Building pytest/seed Docker image: $API_IMAGE"
docker build --progress=plain -t "$API_IMAGE" -f tests/api/Dockerfile .

say "Auditing every source API route against the endpoint coverage manifest"
run_docker_test mreader-api-route-audit "$OUT/api-route-audit.log" \
  "$API_IMAGE" python -u /repo/scripts/tests/api-route-audit.py || {
    echo "ERROR: API route coverage audit failed. See $OUT/api-route-audit.log" >&2
    exit 4
  }

say "Collecting pytest suite before deployment-dependent execution"
test_set_status "pytest-collect" "image=${API_IMAGE}"
test_remove_container mreader-api-test-collect
collect_target=()
if [[ -n "$PYTEST_MODULE" ]]; then
  PYTEST_MODULE="$(basename "$PYTEST_MODULE")"
  [[ -f "tests/api/$PYTEST_MODULE" ]] || { echo "ERROR: unknown pytest module $PYTEST_MODULE" >&2; exit 2; }
  collect_target+=("/tests/$PYTEST_MODULE")
fi
run_docker_test mreader-api-test-collect "$OUT/pytest-collect.log" \
  -e PYTEST_RESULTS_DIR=/tmp/mreader-pytest-collect-results \
  "$API_IMAGE" python -u -m pytest --collect-only -q -m "$PYTEST_MARKER" "${collect_target[@]}" || {
    echo "ERROR: pytest collection failed before application execution. See $OUT/pytest-collect.log" >&2
    exit 4
  }

# Fail fast on Docker-container routing instead of cascading one bad dependency
# into dozens of unrelated pytest failures.
say "Running Docker-container connectivity preflight"
test_remove_container mreader-test-preflight
set +e
test_docker_run --name mreader-test-preflight "${DOCKER_TEST_ENV[@]}" "$API_IMAGE" python -u -c '
import os, socket, sys
import psycopg, requests
checks=[]
def http(name,url):
    try:
        r=requests.get(url,timeout=5)
        ok = r.status_code == 200
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {url} -> HTTP {r.status_code}", flush=True)
        return ok
    except Exception as e:
        print(f"FAIL {name}: {url} -> {e!r}", flush=True); return False
checks.append(http("user-gateway", os.environ["TEST_USER_BASE_URL"]+"/healthz"))
checks.append(http("admin-gateway", os.environ["TEST_ADMIN_BASE_URL"]+"/healthz"))
try:
    u=os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://","postgresql://",1)
    with psycopg.connect(u, connect_timeout=5) as c:
        with c.cursor() as q: q.execute("SELECT 1"); print("OK   postgres: SELECT 1", flush=True)
    checks.append(True)
except Exception as e:
    print(f"FAIL postgres: {e!r}", flush=True); checks.append(False)
try:
    filer=os.environ["TEST_SEAWEEDFS_FILER_URL"]
    host=filer.split("://",1)[-1].split(":",1)[0]
    port=int(filer.rsplit(":",1)[-1])
    with socket.create_connection((host,port),5): pass
    print(f"OK   seaweedfs: TCP {host}:{port}", flush=True); checks.append(True)
except Exception as e:
    print(f"FAIL seaweedfs: {e!r}", flush=True); checks.append(False)
sys.exit(0 if all(checks) else 20)
'
PREFLIGHT_RC=$?
set -e
[[ $PREFLIGHT_RC -eq 0 ]] || { echo "ERROR: Docker test connectivity preflight failed. Fix the failing route above before running tests." >&2; exit "$PREFLIGHT_RC"; }

say "Running pytest API/integration/regression suite in Docker"
test_log "Live pytest output is shown here. From another terminal: ./test-mreader.sh --follow"
pytest_target=("${collect_target[@]}")
PYTEST_STATUS="PASS"
PYTEST_RC=0
set +e
run_docker_test mreader-api-tests "$OUT/pytest.log" \
    "${DOCKER_TEST_ENV[@]}" \
    -e "PYTEST_RESULTS_DIR=/results" \
    -e "PYTEST_RUN_ID=${RUN_ID}" \
    "$API_IMAGE" python -u -m pytest -vv -ra --disable-warnings --maxfail=0 -m "$PYTEST_MARKER" "${pytest_target[@]}"
PYTEST_RC=$?
set -e
[[ $PYTEST_RC -eq 0 ]] || PYTEST_STATUS="FAIL"
RESULT_COPY_STATUS="PASS"
if ! test_copy_results mreader-api-tests "$OUT/pytest-results"; then
  RESULT_COPY_STATUS="FAIL"
  PYTEST_STATUS="FAIL"
  [[ $PYTEST_RC -ne 0 ]] || PYTEST_RC=5
fi
if [[ $PYTEST_RC -eq 0 && ! -s "$OUT/pytest-results/summary.json" ]]; then
  test_log "ERROR: pytest exited 0 but /results/summary.json is missing or empty"
  RESULT_COPY_STATUS="FAIL"
  PYTEST_STATUS="FAIL"
  PYTEST_RC=5
fi

test_set_status "reporting" "out=${OUT}"
say "Capturing post-test application state"
{
  echo '### pods'; kubectl get pods -A -o wide
  echo; echo '### user HPA'; kubectl -n mreader-user get hpa 2>/dev/null || true
  echo; echo '### admin HPA'; kubectl -n mreader-admin get hpa 2>/dev/null || true
  echo; echo '### user scaledobjects'; kubectl -n mreader-user get scaledobjects 2>/dev/null || true
  echo; echo '### admin scaledobjects'; kubectl -n mreader-admin get scaledobjects 2>/dev/null || true
  echo; echo '### admin deployments'; kubectl -n mreader-admin get deployments
  echo; echo '### user deployments'; kubectl -n mreader-user get deployments
  echo; echo '### test containers'; docker ps -a --filter 'name=mreader-api-tests'
  echo; echo '### docker stats'; docker stats --no-stream 2>/dev/null || true
  echo; echo '### recent warning events'; kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -100 || true
} > "$OUT/cluster-after.txt"

python_summary='not-run'
[[ -f "$OUT/pytest.log" ]] && python_summary="$(grep 'MREADER_PYTEST_SUMMARY_JSON=' "$OUT/pytest.log" | tail -1 | sed 's/^.*MREADER_PYTEST_SUMMARY_JSON=//' || true)"
cat > "$OUT/SUMMARY.txt" <<SUMMARY
MReader test run: $RUN_ID
Version: $VERSION
Topology: Docker pytest container -> host-exposed CURRENT Kubernetes twin-plane
pytest status: $PYTEST_STATUS
pytest exit: $PYTEST_RC
pytest summary: $python_summary
result artifact copy: $RESULT_COPY_STATUS
capacity status: NOT_RUN_BY_PYTEST_RUNNER
capacity note: use ./test-mreader.sh --full for pytest then gradual k6, or --capacity/--capacity-deep directly
SUMMARY

cat "$OUT/SUMMARY.txt"
./scripts/tests/build-hybrid-report.sh "$OUT" >/dev/null || true
echo "Detailed pytest results: $OUT"
echo "Report: $OUT/REPORT.md"
echo "Stopped Docker pytest container is retained for inspection and replaced on the next run."

[[ $PYTEST_RC -eq 0 ]] || exit "$PYTEST_RC"
