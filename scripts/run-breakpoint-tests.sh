#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/tests/test-runner-common.sh"
source "$ROOT/scripts/env/env-lib.sh"

MODE="standard"; WORKLOAD_FILTER=""; KEEP_DATA=0; SEED_DATA=1; DURATION=60; COOLDOWN=15
LEVELS=(1 2 5 10 15 20 30 40 60 80 100)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) MODE=quick; DURATION=20; COOLDOWN=8; LEVELS=(1 2 5 10 20); shift ;;
    --standard) MODE=standard; shift ;;
    --deep) MODE=deep; DURATION=90; COOLDOWN=20; LEVELS=(1 2 5 10 15 20 30 40 60 80 100 125 150 200 250 300); shift ;;
    --workload) WORKLOAD_FILTER="${2:?workload required}"; shift 2 ;;
    --keep-test-data) KEEP_DATA=1; shift ;;
    --seed-already) SEED_DATA=0; shift ;;
    --duration) DURATION="${2:?seconds required}"; shift 2 ;;
    --cooldown) COOLDOWN="${2:?seconds required}"; shift 2 ;;
    -h|--help)
      cat <<'HELP'
Usage: ./scripts/run-breakpoint-tests.sh [--quick|--standard|--deep] [--workload NAME] [--keep-test-data]

Runs gradual breakpoint tests as ordinary Docker containers. The application
remains in the current RC4.47 Docker Desktop Kubernetes twin-plane.
HELP
      exit 0 ;;
    *) echo "ERROR: unsupported option $1" >&2; exit 2 ;;
  esac
done

for cmd in docker kubectl sed awk grep; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; exit 2; }; done
[[ -f .env ]] || { echo "ERROR: .env is required" >&2; exit 2; }
[[ "$(kubectl config current-context 2>/dev/null || true)" == docker-desktop ]] || { echo "ERROR: kubectl context must be docker-desktop" >&2; exit 2; }
[[ -f tests/load/workloads.tsv ]] || { echo "ERROR: missing tests/load/workloads.tsv" >&2; exit 2; }

VERSION="$(cat VERSION)"; API_IMAGE="mreader/api-tests:${VERSION}"; K6_IMAGE="mreader/k6-tests:${VERSION}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"; OUT="$ROOT/test-results/capacity/$RUN_ID"
K6_RUN_TOKEN="$(printf '%s' "$RUN_ID" | tr -cd '[:alnum:]' | cut -c1-20)"
K6_LOGIN_USERNAME="mreader_k6_login_${K6_RUN_TOKEN}"
K6_LOGIN_EMAIL="mreader.k6.login.${K6_RUN_TOKEN}@gmail.com"
mkdir -p "$OUT/logs" "$OUT/snapshots"
test_set_status starting "mode=docker-capacity run_id=${RUN_ID} out=${OUT}"
finish_test_status(){ local rc=$?; test_set_status finished "mode=docker-capacity run_id=${RUN_ID} exit=${rc} out=${OUT}"; }; trap finish_test_status EXIT
RESULTS="$OUT/results.tsv"
printf 'workload\tservice\tlevel\tunit\trequests\tthroughput\tp50_ms\tp95_ms\tp99_ms\tfailure_rate\tdropped\tdropped_rate\tstatus_429\tstate\tp95_slo_ms\tp99_slo_ms\tattempt\n' > "$RESULTS"

USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
NAS_HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"; NAS_PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
DB_URL="$(env_get .env DATABASE_URL)"; [[ -n "$DB_URL" ]] || DB_URL="postgresql://$(env_get .env POSTGRES_USER):$(env_get .env POSTGRES_PASSWORD)@db:5432/$(env_get .env POSTGRES_DB)"
[[ -n "$NAS_HOST" ]] || { echo "ERROR: NAS_SEAWEEDFS_HOST is required" >&2; exit 2; }
STATEFUL_NETWORK="$(test_stateful_network)"
USER_URL="http://host.docker.internal:${USER_PORT}"; ADMIN_URL="http://host.docker.internal:${ADMIN_PORT}"; FILER_URL="http://${NAS_HOST}:${NAS_PORT}"
DOCKER_SEED_ENV=(--network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway --env-file .env -e "TEST_USER_BASE_URL=${USER_URL}" -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}" -e "TEST_DATABASE_URL=${DB_URL}" -e "TEST_SEAWEEDFS_FILER_URL=${FILER_URL}")

say(){ test_section "$*"; }
say "Checking current twin-plane deployment"
kubectl -n mreader-user rollout status deployment/user-gateway --timeout=120s
kubectl -n mreader-admin rollout status deployment/admin-gateway --timeout=120s
curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz" >/dev/null
curl -fsS --connect-timeout 3 --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null

test_set_status building-image "image=${API_IMAGE}"
say "Building deterministic seed Docker image: $API_IMAGE"
docker build --progress=plain -t "$API_IMAGE" -f tests/api/Dockerfile .
test_set_status building-image "image=${K6_IMAGE}"
say "Building k6 breakpoint Docker image: $K6_IMAGE"
docker build --progress=plain -t "$K6_IMAGE" -f tests/load/Dockerfile .

seed_container(){
  local action="$1" log="$2"
  run_docker_test mreader-load-seed "$log" "${DOCKER_SEED_ENV[@]}" \
    -e K6_TEST_SERIES_SLUG=mreader-k6-load-series -e K6_TEST_USERNAME=mreader_k6_user -e K6_TEST_EMAIL=mreader.k6.user@gmail.com -e K6_TEST_PASSWORD=MReaderK6Test123! \
    -e K6_TEST_ADMIN_USERNAME=mreader_k6_admin -e K6_TEST_ADMIN_EMAIL=mreader.k6.admin@gmail.com -e K6_TEST_ADMIN_PASSWORD=MReaderK6Admin123! \
    -e "K6_TEST_LOGIN_USERNAME=${K6_LOGIN_USERNAME}" -e "K6_TEST_LOGIN_EMAIL=${K6_LOGIN_EMAIL}" -e K6_TEST_LOGIN_PASSWORD=MReaderK6Login123! \
    "$API_IMAGE" python -u /load/seed.py "$action"
}

# Validate all Docker-side routes before seeding or load generation.
say "Running Docker-container connectivity preflight"
test_remove_container mreader-test-preflight
set +e
test_docker_run --name mreader-test-preflight "${DOCKER_SEED_ENV[@]}" "$API_IMAGE" python -u -c '
import os,socket,sys,requests,psycopg
ok=[]
for n,u in [("user",os.environ["TEST_USER_BASE_URL"]+"/healthz"),("admin",os.environ["TEST_ADMIN_BASE_URL"]+"/healthz")]:
  try:r=requests.get(u,timeout=5);print("OK",n,u,r.status_code,flush=True);ok.append(True)
  except Exception as e:print("FAIL",n,repr(e),flush=True);ok.append(False)
try:
 u=os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://","postgresql://",1); c=psycopg.connect(u,connect_timeout=5); c.close(); print("OK postgres",flush=True);ok.append(True)
except Exception as e:print("FAIL postgres",repr(e),flush=True);ok.append(False)
try:
 f=os.environ["TEST_SEAWEEDFS_FILER_URL"]; h=f.split("://",1)[-1].split(":",1)[0]; p=int(f.rsplit(":",1)[-1]); s=socket.create_connection((h,p),5);s.close();print("OK seaweedfs",h,p,flush=True);ok.append(True)
except Exception as e:print("FAIL seaweedfs",repr(e),flush=True);ok.append(False)
sys.exit(0 if all(ok) else 20)'
PREFLIGHT_RC=$?; set -e
[[ $PREFLIGHT_RC -eq 0 ]] || { echo "ERROR: Docker test connectivity preflight failed" >&2; exit "$PREFLIGHT_RC"; }

snapshot(){
  local label="$1"
  local dst="$OUT/snapshots/${label}.txt"
  {
    echo '### time'; date -u +%FT%TZ
    echo; echo '### user pods'; kubectl -n mreader-user get pods -o wide || true
    echo; echo '### admin pods'; kubectl -n mreader-admin get pods -o wide || true
    echo; echo '### user top'; kubectl top pods -n mreader-user 2>/dev/null || true
    echo; echo '### admin top'; kubectl top pods -n mreader-admin 2>/dev/null || true
    echo; echo '### user HPA'; kubectl -n mreader-user get hpa 2>/dev/null || true
    echo; echo '### admin HPA'; kubectl -n mreader-admin get hpa 2>/dev/null || true
    echo; echo '### user KEDA'; kubectl -n mreader-user get scaledobjects 2>/dev/null || true
    echo; echo '### admin KEDA'; kubectl -n mreader-admin get scaledobjects 2>/dev/null || true
    echo; echo '### deployments'; kubectl get deploy -n mreader-user; kubectl get deploy -n mreader-admin
    echo; echo '### stateful/test docker stats'; docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}' 2>/dev/null || true
    echo; echo '### recent warnings'; kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -80 || true
  } > "$dst" 2>&1
}

if [[ $SEED_DATA -eq 1 ]]; then say "Creating deterministic capacity-test data"; seed_container create "$OUT/seed.log" || { echo "ERROR: capacity seed failed" >&2; exit 1; }; fi

workload_exists(){ awk -F'|' -v target="$1" '$1==target{found=1} END{exit !found}' tests/load/workloads.tsv; }
if [[ -n "$WORKLOAD_FILTER" ]] && ! workload_exists "$WORKLOAD_FILTER"; then echo "ERROR: unknown workload: $WORKLOAD_FILTER" >&2; exit 2; fi

run_step(){
  local workload="$1" service="$2" level="$3" kind="$4" p95="$5" p99="$6" attempt="$7"
  local unit="$kind"
  [[ "$unit" == "arrival" ]] && unit="rps"
  local max_vus=$(( level * 6 )); (( max_vus < 100 )) && max_vus=100; (( max_vus > 1500 )) && max_vus=1500
  local log="$OUT/logs/${workload}-${level}-a${attempt}.log"
  record_runtime_failure(){
    local why="$1"
    echo "${workload}|${level}|${unit}|0|0|0|0|0|0|0|0|0|FAIL" > "$OUT/.last-result"
    printf '%s	%s	%s	%s	0	0	0	0	0	0	0	0	0	FAIL	%s	%s	%s
' \
      "$workload" "$service" "$level" "$unit" "$p95" "$p99" "$attempt" >> "$RESULTS"
    printf '%s
' "$why" > "$OUT/logs/${workload}-${level}-a${attempt}.failure.txt"
  }
  test_set_status capacity-step "workload=${workload} service=${service} target=${level} unit=${kind} duration=${DURATION}s attempt=${attempt} container=mreader-k6-breakpoint out=${OUT}"
  test_log "STEP workload=${workload} service=${service} target=${level} ${kind} duration=${DURATION}s attempt=${attempt}"
  if ! run_docker_test mreader-k6-breakpoint "$log" \
      --network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway \
      -e "TEST_USER_BASE_URL=${USER_URL}" -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}" \
      -e K6_TEST_SERIES_SLUG=mreader-k6-load-series -e K6_TEST_USERNAME=mreader_k6_user -e K6_TEST_PASSWORD=MReaderK6Test123! \
      -e K6_TEST_ADMIN_USERNAME=mreader_k6_admin -e K6_TEST_ADMIN_PASSWORD=MReaderK6Admin123! \
      -e "K6_TEST_LOGIN_USERNAME=${K6_LOGIN_USERNAME}" -e K6_TEST_LOGIN_PASSWORD=MReaderK6Login123! \
      -e "K6_BREAKPOINT_WORKLOAD=${workload}" -e "K6_BREAKPOINT_LEVEL=${level}" -e "K6_BREAKPOINT_DURATION_SECONDS=${DURATION}" \
      -e "K6_BREAKPOINT_MAX_VUS=${max_vus}" -e "K6_BREAKPOINT_P95_MS=${p95}" -e "K6_BREAKPOINT_P99_MS=${p99}" \
      "$K6_IMAGE" run /tests/load/breakpoint.js; then
    record_runtime_failure "k6 container exited non-zero before producing a valid breakpoint result"
    snapshot "${workload}-${level}-a${attempt}-jobfail"; return 0
  fi
  local marker; marker="$(grep 'MREADER_BREAKPOINT_RESULT=' "$log" | tail -1 | sed 's/^.*MREADER_BREAKPOINT_RESULT=//' || true)"
  if [[ -z "$marker" ]]; then
    record_runtime_failure "k6 container completed without MREADER_BREAKPOINT_RESULT marker"
    snapshot "${workload}-${level}-a${attempt}-nomarker"; return 0
  fi
  echo "$marker" > "$OUT/.last-result"
  IFS='|' read -r rw rl ru rr rt rp50 rp95 rp99 rf rd rdr r429 rs <<< "$marker"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$rw" "$service" "$rl" "$ru" "$rr" "$rt" "$rp50" "$rp95" "$rp99" "$rf" "$rd" "$rdr" "$r429" "$rs" "$p95" "$p99" "$attempt" >> "$RESULTS"
  snapshot "${workload}-${level}-a${attempt}"
}

say "Running gradual Docker breakpoint ladders ($MODE; ${DURATION}s/step; ${COOLDOWN}s cooldown)"
while IFS='|' read -r workload service kind p95 p99 max_level notes; do
  [[ -z "$workload" || "$workload" == \#* ]] && continue
  [[ -n "$WORKLOAD_FILTER" && "$workload" != "$WORKLOAD_FILTER" ]] && continue
  say "Workload $workload ($service): ${kind}; SLO p95<=${p95}ms p99<=${p99}ms"
  confirmed_break=0
  for level in "${LEVELS[@]}"; do
    (( level > max_level )) && break
    run_step "$workload" "$service" "$level" "$kind" "$p95" "$p99" 1
    IFS='|' read -r _ _ _ _ _ _ _ _ _ _ _ _ state < "$OUT/.last-result"
    if [[ "$state" == FAIL ]]; then
      test_log "First failure at ${level} ${kind}; cooling down ${COOLDOWN}s and confirming once"; sleep "$COOLDOWN"
      run_step "$workload" "$service" "$level" "$kind" "$p95" "$p99" 2
      IFS='|' read -r _ _ _ _ _ _ _ _ _ _ _ _ state2 < "$OUT/.last-result"
      if [[ "$state2" == FAIL ]]; then test_log "Confirmed breaking point at ${level} ${kind}"; confirmed_break=1; break; fi
      test_log "Confirmation passed; first failure treated as transient"
    fi
    sleep "$COOLDOWN"
  done
  [[ $confirmed_break -eq 0 ]] && test_log "No confirmed break within configured ladder for ${workload}"
done < tests/load/workloads.tsv

if [[ $KEEP_DATA -eq 0 && $SEED_DATA -eq 1 ]]; then say "Cleaning deterministic capacity-test series"; seed_container cleanup "$OUT/cleanup.log" || true; fi

test_set_status reporting "out=${OUT}"
say "Building capacity report"
./scripts/tests/build-breakpoint-report.sh "$OUT" >/dev/null
cat "$OUT/CAPACITY_SUMMARY.tsv"
echo "Detailed capacity report: $OUT/CAPACITY_REPORT.md"
echo "Raw step results: $RESULTS"
echo "The latest stopped Docker test container remains inspectable until the next step/run replaces it."
