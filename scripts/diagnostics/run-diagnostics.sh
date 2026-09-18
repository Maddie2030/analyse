#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
source "$ROOT/scripts/docker/msys-paths.sh"
source "$ROOT/scripts/env/env-lib.sh"

MODE=full
EXTERNAL=false
KEEP_DATA=false
BROWSER=true
SERIES_URL="${MREADER_DIAGNOSTICS_SERIES_URL:-}"
CHAPTER_URL="${MREADER_DIAGNOSTICS_CHAPTER_URL:-}"
CHAPTER_FILE="${MREADER_DIAGNOSTICS_CHAPTER_FILE_HOST:-}"
COVER_IMAGE="${MREADER_DIAGNOSTICS_COVER_IMAGE_HOST:-}"
while (($#)); do
  case "$1" in
    --quick) MODE=quick ;;
    --full) MODE=full ;;
    --external) EXTERNAL=true ;;
    --no-browser) BROWSER=false ;;
    --keep-test-data) KEEP_DATA=true ;;
    --scraper-series-url)
      shift; [[ $# -gt 0 ]] || { echo 'ERROR: --scraper-series-url requires a URL' >&2; exit 2; }
      SERIES_URL="$1"; EXTERNAL=true ;;
    --scraper-chapter-url)
      shift; [[ $# -gt 0 ]] || { echo 'ERROR: --scraper-chapter-url requires a URL' >&2; exit 2; }
      CHAPTER_URL="$1"; EXTERNAL=true ;;
    --chapter-file)
      shift; [[ $# -gt 0 ]] || { echo 'ERROR: --chapter-file requires a ZIP/CBZ/PDF path' >&2; exit 2; }
      CHAPTER_FILE="$1"; EXTERNAL=true ;;
    --cover-image)
      shift; [[ $# -gt 0 ]] || { echo 'ERROR: --cover-image requires an image path' >&2; exit 2; }
      COVER_IMAGE="$1"; EXTERNAL=true ;;
    -h|--help)
      cat <<'HELP'
Usage: ./diagnose-mreader.sh [--quick|--full] [--external] [--no-browser]
                             [--scraper-series-url URL]
                             [--scraper-chapter-url URL]
                             [--chapter-file PATH_TO_ZIP_CBZ_OR_PDF]
                             [--cover-image PATH_TO_IMAGE]
                             [--keep-test-data]

Launches the dedicated Dockerized MReader diagnostics module against the current
Docker Desktop twin-plane deployment and writes test-results/diagnostics/<run-id>/.

Default --full runs the complete API/functionality suite, real user/admin actor
journeys, and Playwright browser user/admin journeys. --quick keeps the all-route
audit and a bounded API/actor subset. --no-browser suppresses the Playwright stage.
External fixture flags automatically enable the external journeys. Missing optional
fixtures are reported as SKIPPED by their individual journey rather than failed.
HELP
      exit 0 ;;
    *) echo "ERROR: unsupported diagnostics option $1" >&2; exit 2 ;;
  esac
  shift
done

[[ -z "$CHAPTER_FILE" || -f "$CHAPTER_FILE" ]] || { echo "ERROR: chapter fixture not found: $CHAPTER_FILE" >&2; exit 2; }
[[ -z "$COVER_IMAGE" || -f "$COVER_IMAGE" ]] || { echo "ERROR: cover fixture not found: $COVER_IMAGE" >&2; exit 2; }

for cmd in docker kubectl sed awk grep curl; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo 'ERROR: .env is required' >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == docker-desktop ]] || { echo 'ERROR: kubectl context must be docker-desktop' >&2; exit 2; }

VERSION="$(tr -d '\r\n' < VERSION)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT="$ROOT/test-results/diagnostics/$RUN_ID"; LOG_DIR="$OUT/logs"; SNAPSHOT_DIR="$OUT/snapshot"
mkdir -p "$LOG_DIR" "$SNAPSHOT_DIR" "$OUT/pytest"
DIAGNOSTICS_IMAGE="mreader/diagnostics:${VERSION}"
DIAGNOSTICS_CONTAINER="mreader-diagnostics-${RUN_ID//[^A-Za-z0-9_.-]/-}"
printf 'run_id=%s\nmode=%s\nimage=%s\ncontainer=%s\nout=%s\n' "$RUN_ID" "$MODE" "$DIAGNOSTICS_IMAGE" "$DIAGNOSTICS_CONTAINER" "$OUT" > "$OUT/run.env"
test_set_status diagnostics-start "mode=${MODE} run_id=${RUN_ID} out=${OUT}"

echo "MReader diagnostics: $RUN_ID"
echo "Output: $OUT"
echo "Container image: $DIAGNOSTICS_IMAGE"
echo "Container: $DIAGNOSTICS_CONTAINER"

STATEFUL_NETWORK="$(test_stateful_network)"
USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
NAS_HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"; NAS_PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
DB_URL="$(env_get .env DATABASE_URL)"
if [[ -z "$DB_URL" ]]; then DB_URL="postgresql://$(env_get .env POSTGRES_USER):$(env_get .env POSTGRES_PASSWORD)@db:5432/$(env_get .env POSTGRES_DB)"; fi
[[ -n "$NAS_HOST" ]] || { echo 'ERROR: NAS_SEAWEEDFS_HOST is required' >&2; exit 2; }
USER_URL="http://host.docker.internal:${USER_PORT}"; ADMIN_URL="http://host.docker.internal:${ADMIN_PORT}"; FILER_URL="http://${NAS_HOST}:${NAS_PORT}"
API_IMAGE="mreader/api-tests:${VERSION}"

test_section 'Building diagnostics base/API image'
docker build --progress=plain -t "$API_IMAGE" -f tests/api/Dockerfile .
test_section 'Building dedicated diagnostics image'
docker build --progress=plain -t "$DIAGNOSTICS_IMAGE" -f tests/diagnostics/Dockerfile .

test_remove_container "$DIAGNOSTICS_CONTAINER"
HOST_OUT="$(mreader_docker_host_path "$OUT")"
DOCKER_ENV=(
  --network "$STATEFUL_NETWORK"
  --add-host host.docker.internal:host-gateway
  --env-file .env
  -e "TEST_USER_BASE_URL=${USER_URL}"
  -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}"
  -e "TEST_DATABASE_URL=${DB_URL}"
  -e "TEST_SEAWEEDFS_FILER_URL=${FILER_URL}"
  -e "MREADER_DIAGNOSTICS_MODE=${MODE}"
  -e "MREADER_DIAGNOSTICS_EXTERNAL=${EXTERNAL}"
  -e "MREADER_DIAGNOSTICS_RUN_ID=${RUN_ID}"
  -e 'MREADER_DIAGNOSTICS_RESULTS_DIR=/results'
  -e "MREADER_VERSION=${VERSION}"
)
for passthrough in \
  MREADER_TEST_ADMIN_USERNAME MREADER_TEST_ADMIN_EMAIL MREADER_TEST_ADMIN_PASSWORD \
  MREADER_TEST_USER_USERNAME MREADER_TEST_USER_EMAIL MREADER_TEST_USER_PASSWORD; do
  if [[ -n "${!passthrough:-}" ]]; then
    DOCKER_ENV+=(-e "${passthrough}=${!passthrough}")
  fi
done
[[ "$KEEP_DATA" == true ]] && DOCKER_ENV+=(-e KEEP_TEST_DATA=1)
[[ -n "$SERIES_URL" ]] && DOCKER_ENV+=(-e "MREADER_DIAGNOSTICS_SERIES_URL=${SERIES_URL}" -e "SCRAPER_TEST_SERIES_URL=${SERIES_URL}")
[[ -n "$CHAPTER_URL" ]] && DOCKER_ENV+=(-e "MREADER_DIAGNOSTICS_CHAPTER_URL=${CHAPTER_URL}" -e "SCRAPER_TEST_CHAPTER_URL=${CHAPTER_URL}")
if [[ -n "$CHAPTER_FILE" ]]; then
  CHAPTER_HOST="$(mreader_docker_host_path "$CHAPTER_FILE")"
  CHAPTER_FILENAME="$(basename "$CHAPTER_FILE")"
  DOCKER_ENV+=(-v "${CHAPTER_HOST}:/fixtures/chapter-file:ro" -e MREADER_DIAGNOSTICS_CHAPTER_FILE=/fixtures/chapter-file -e "MREADER_DIAGNOSTICS_CHAPTER_FILENAME=${CHAPTER_FILENAME}")
fi
if [[ -n "$COVER_IMAGE" ]]; then
  COVER_HOST="$(mreader_docker_host_path "$COVER_IMAGE")"
  COVER_FILENAME="$(basename "$COVER_IMAGE")"
  DOCKER_ENV+=(-v "${COVER_HOST}:/fixtures/cover-image:ro" -e MREADER_DIAGNOSTICS_COVER_IMAGE=/fixtures/cover-image -e "MREADER_DIAGNOSTICS_COVER_FILENAME=${COVER_FILENAME}")
fi

test_section 'Capturing pre-test runtime evidence'
"$ROOT/scripts/diagnostics/collect-runtime-evidence.sh" before "$OUT" || true

test_section 'Launching diagnostics container'
MSYS_NO_PATHCONV=1 docker run -d --name "$DIAGNOSTICS_CONTAINER" "${DOCKER_ENV[@]}" -v "${HOST_OUT}:/results" "$DIAGNOSTICS_IMAGE" >/dev/null
test_set_status diagnostics-running "container=${DIAGNOSTICS_CONTAINER} out=${OUT}"
while [[ ! -f "$OUT/.container-tests-done" ]]; do
  state="$(docker inspect -f '{{.State.Running}}' "$DIAGNOSTICS_CONTAINER" 2>/dev/null || true)"
  [[ "$state" == true ]] || break
  sleep 1
done

record_host_stage(){
  local name="$1" rc="$2" seconds="$3" log="$4" status=PASS
  [[ "$rc" -eq 0 ]] || status=FAIL
  if [[ ! -f "$OUT/stages.tsv" ]]; then printf 'name\tstatus\texit_code\tduration_seconds\tlog\n' > "$OUT/stages.tsv"; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$status" "$rc" "$seconds" "$log" >> "$OUT/stages.tsv"
}

if [[ "$MODE" == full && "$BROWSER" == true ]]; then
  test_section 'Running Playwright user/admin actor journeys'
  BROWSER_IMAGE="mreader/browser-tests:${VERSION}"
  BROWSER_CONTAINER="mreader-diagnostics-browser-${RUN_ID//[^A-Za-z0-9_.-]/-}"
  BROWSER_DB_URL="$DB_URL"
  case "$BROWSER_DB_URL" in
    postgresql+*://*) BROWSER_DB_URL="postgresql://${BROWSER_DB_URL#*://}" ;;
    postgres+*://*) BROWSER_DB_URL="postgres://${BROWSER_DB_URL#*://}" ;;
  esac
  docker build --progress=plain -t "$BROWSER_IMAGE" -f tests/browser/Dockerfile .
  test_remove_container "$BROWSER_CONTAINER"
  browser_env=(
    -e "MREADER_BROWSER_BASE_URL=${USER_URL}"
    -e "MREADER_BROWSER_ADMIN_BASE_URL=${ADMIN_URL}"
    -e "MREADER_BROWSER_DATABASE_URL=${BROWSER_DB_URL}"
    -e MREADER_BROWSER_RESULTS_DIR=/results/browser
  )
  [[ -n "${MREADER_TEST_ADMIN_USERNAME:-}" ]] && browser_env+=(-e "MREADER_BROWSER_ADMIN_USERNAME=${MREADER_TEST_ADMIN_USERNAME}")
  [[ -n "${MREADER_TEST_ADMIN_EMAIL:-}" ]] && browser_env+=(-e "MREADER_BROWSER_ADMIN_EMAIL=${MREADER_TEST_ADMIN_EMAIL}")
  [[ -n "${MREADER_TEST_ADMIN_PASSWORD:-}" ]] && browser_env+=(-e "MREADER_BROWSER_ADMIN_PASSWORD=${MREADER_TEST_ADMIN_PASSWORD}")
  [[ -n "$SERIES_URL" ]] && browser_env+=(-e "MREADER_BROWSER_SCRAPER_SERIES_URL=${SERIES_URL}")
  browser_started="$(date +%s)"
  set +e
  MSYS_NO_PATHCONV=1 docker run --name "$BROWSER_CONTAINER" \
    --network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway --env-file .env \
    "${browser_env[@]}" \
    -v "${HOST_OUT}:/results" \
    "$BROWSER_IMAGE" ./node_modules/.bin/playwright test --config=playwright.config.mjs \
    2>&1 | tee "$LOG_DIR/browser-ui.log"
  browser_pipe=("${PIPESTATUS[@]}")
  set -e
  browser_rc="${browser_pipe[0]:-125}"
  [[ "${browser_pipe[1]:-0}" -eq 0 ]] || browser_rc="${browser_pipe[1]}"
  browser_elapsed="$(( $(date +%s) - browser_started ))"
  record_host_stage browser-ui "$browser_rc" "$browser_elapsed" logs/browser-ui.log
fi

test_section 'Capturing post-test runtime evidence'
"$ROOT/scripts/diagnostics/collect-runtime-evidence.sh" after "$OUT" || true
touch "$OUT/.host-post-capture-done"
set +e
docker logs -f "$DIAGNOSTICS_CONTAINER" 2>&1 | tee "$LOG_DIR/container.log"
log_pipe=("${PIPESTATUS[@]}")
set -e
container_rc="$(docker inspect -f '{{.State.ExitCode}}' "$DIAGNOSTICS_CONTAINER" 2>/dev/null || echo 125)"
[[ ${log_pipe[1]:-0} -eq 0 ]] || container_rc=${log_pipe[1]}
echo "Diagnostics container exit: $container_rc"
echo "Results: $OUT"
echo "Human report: $OUT/REPORT.md"
echo "Machine report: $OUT/REPORT.json"
echo "Report bundle: $OUT/REPORT_BUNDLE.zip"
test_set_status diagnostics-finished "container=${DIAGNOSTICS_CONTAINER} exit=${container_rc} out=${OUT}"
exit "$container_rc"
