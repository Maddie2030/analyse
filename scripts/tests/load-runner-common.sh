#!/usr/bin/env bash
# shellcheck shell=bash
# Caller must define ROOT, RUN_ID and OUT, and source test-runner-common/env-lib first.
load_prepare(){
  for cmd in docker kubectl curl awk sed grep; do command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is required" >&2; return 2; }; done
  [[ -f .env ]] || { echo 'ERROR: .env is required' >&2; return 2; }
  [[ "$(kubectl config current-context 2>/dev/null || true)" == docker-desktop ]] || { echo 'ERROR: kubectl context must be docker-desktop' >&2; return 2; }
  VERSION="$(cat VERSION)"; API_IMAGE="mreader/api-tests:${VERSION}"; K6_IMAGE="mreader/k6-tests:${VERSION}"
  USER_PORT="$(env_get .env HYBRID_GATEWAY_PORT)"; USER_PORT="${USER_PORT:-8080}"
  ADMIN_PORT="$(env_get .env HYBRID_ADMIN_GATEWAY_PORT)"; ADMIN_PORT="${ADMIN_PORT:-8081}"
  NAS_HOST="$(env_get .env NAS_SEAWEEDFS_HOST)"; NAS_PORT="$(env_get .env NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
  DB_URL="$(env_get .env DATABASE_URL)"; [[ -n "$DB_URL" ]] || DB_URL="postgresql://$(env_get .env POSTGRES_USER):$(env_get .env POSTGRES_PASSWORD)@db:5432/$(env_get .env POSTGRES_DB)"
  [[ -n "$NAS_HOST" ]] || { echo 'ERROR: NAS_SEAWEEDFS_HOST is required' >&2; return 2; }
  STATEFUL_NETWORK="$(test_stateful_network)"
  USER_URL="http://host.docker.internal:${USER_PORT}"; ADMIN_URL="http://host.docker.internal:${ADMIN_PORT}"; FILER_URL="http://${NAS_HOST}:${NAS_PORT}"
  LOAD_RUN_TOKEN="$(printf '%s' "$RUN_ID" | tr -cd '[:alnum:]' | cut -c1-20)"
  K6_LOGIN_USERNAME="mreader_k6_login_${LOAD_RUN_TOKEN}"; K6_LOGIN_EMAIL="mreader.k6.login.${LOAD_RUN_TOKEN}@gmail.com"
  DOCKER_SEED_ENV=(--network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway --env-file .env -e "TEST_USER_BASE_URL=${USER_URL}" -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}" -e "TEST_DATABASE_URL=${DB_URL}" -e "TEST_SEAWEEDFS_FILER_URL=${FILER_URL}")
  kubectl -n mreader-user rollout status deployment/user-gateway --timeout=120s
  kubectl -n mreader-admin rollout status deployment/admin-gateway --timeout=120s
  curl -fsS --max-time 8 "http://127.0.0.1:${USER_PORT}/healthz" >/dev/null
  curl -fsS --max-time 8 "http://127.0.0.1:${ADMIN_PORT}/healthz" >/dev/null
}
load_build_images(){
  test_section "Building load seed image: $API_IMAGE"; docker build --progress=plain -t "$API_IMAGE" -f tests/api/Dockerfile .
  test_section "Building k6 image: $K6_IMAGE"; docker build --progress=plain -t "$K6_IMAGE" -f tests/load/Dockerfile .
}
load_seed(){
  local action="$1" log="$2"
  run_docker_test mreader-load-seed "$log" "${DOCKER_SEED_ENV[@]}" \
    -e K6_TEST_SERIES_SLUG=mreader-k6-load-series -e K6_TEST_USERNAME=mreader_k6_user -e K6_TEST_EMAIL=mreader.k6.user@gmail.com -e K6_TEST_PASSWORD=MReaderK6Test123! \
    -e K6_TEST_ADMIN_USERNAME=mreader_k6_admin -e K6_TEST_ADMIN_EMAIL=mreader.k6.admin@gmail.com -e K6_TEST_ADMIN_PASSWORD=MReaderK6Admin123! \
    -e "K6_TEST_LOGIN_USERNAME=${K6_LOGIN_USERNAME}" -e "K6_TEST_LOGIN_EMAIL=${K6_LOGIN_EMAIL}" -e K6_TEST_LOGIN_PASSWORD=MReaderK6Login123! \
    "$API_IMAGE" python -u /load/seed.py "$action"
}
load_k6_env(){
  printf '%s\n' \
    --network "$STATEFUL_NETWORK" --add-host host.docker.internal:host-gateway \
    -e "TEST_USER_BASE_URL=${USER_URL}" -e "TEST_ADMIN_BASE_URL=${ADMIN_URL}" \
    -e K6_TEST_SERIES_SLUG=mreader-k6-load-series -e K6_TEST_USERNAME=mreader_k6_user -e K6_TEST_PASSWORD=MReaderK6Test123! \
    -e K6_TEST_ADMIN_USERNAME=mreader_k6_admin -e K6_TEST_ADMIN_PASSWORD=MReaderK6Admin123! \
    -e "K6_TEST_LOGIN_USERNAME=${K6_LOGIN_USERNAME}" -e K6_TEST_LOGIN_PASSWORD=MReaderK6Login123!
}
load_snapshot(){
  local dst="$1"
  {
    echo '### time'; date -u +%FT%TZ
    echo; echo '### user pods'; kubectl -n mreader-user get pods -o wide || true
    echo; echo '### admin pods'; kubectl -n mreader-admin get pods -o wide || true
    echo; echo '### user top'; kubectl top pods -n mreader-user 2>/dev/null || true
    echo; echo '### admin top'; kubectl top pods -n mreader-admin 2>/dev/null || true
    echo; echo '### HPA/KEDA'; kubectl -n mreader-user get hpa,scaledobjects 2>/dev/null || true; kubectl -n mreader-admin get hpa,scaledobjects 2>/dev/null || true
    echo; echo '### Docker stateful stats'; docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}' 2>/dev/null || true
    echo; echo '### warnings'; kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -80 || true
  } > "$dst" 2>&1
}
