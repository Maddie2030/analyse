#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
CATALOG_DIR="$ROOT/services/catalog_go"
NOTIFICATION_DIR="$ROOT/services/notification_worker"
MODE="${MREADER_TEST_POSTGRES_MODE:-dsn}"
DOCKER_CONTAINER=""
DOCKER_NETWORK=""
MIGRATION_SCRIPT=""

cleanup() {
  if [[ -n "$DOCKER_CONTAINER" ]] && command -v docker >/dev/null 2>&1; then
    docker rm -f "$DOCKER_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ -n "$DOCKER_NETWORK" ]] && command -v docker >/dev/null 2>&1; then
    docker network rm "$DOCKER_NETWORK" >/dev/null 2>&1 || true
  fi
  if [[ -n "$MIGRATION_SCRIPT" ]]; then
    rm -f "$MIGRATION_SCRIPT"
  fi
}
trap cleanup EXIT HUP INT TERM

check_host_go() {
  if ! command -v go >/dev/null 2>&1; then
    echo "ERROR: Go 1.25 or newer is required for DSN-mode Catalog P06.3 transaction tests." >&2
    return 2
  fi

  local version toolchain version_ok
  version="$(go env GOVERSION 2>/dev/null || true)"
  toolchain="$(go env GOTOOLCHAIN 2>/dev/null || true)"
  version_ok=false
  case "$version" in
    go1.2[5-9]*|go1.[3-9][0-9]*|go[2-9].*) version_ok=true ;;
  esac
  if [[ "$version_ok" != true ]]; then
    case "$toolchain" in
      auto|*+auto|go1.2[5-9]*|go1.[3-9][0-9]*|go[2-9].*) ;;
      *)
        echo "ERROR: Catalog P06.3 gate requires Go >= 1.25 or an auto toolchain launcher; found ${version:-unknown} with GOTOOLCHAIN=${toolchain:-unknown}." >&2
        return 2
        ;;
    esac
  fi
}

run_tests_with_host_go() {
  (
    cd "$CATALOG_DIR"
    go test ./internal/store -run '^(TestCommitPublication.*|TestMediaCompletionEvidenceIsDatabaseImmutable)$' -count=1 -v
  )
  (
    cd "$NOTIFICATION_DIR"
    go test ./internal/events ./internal/store -count=1 -v
  )
}

case "$MODE" in
  dsn)
    if [[ -z "${MREADER_TEST_POSTGRES_DSN:-}" ]]; then
      echo "ERROR: MREADER_TEST_POSTGRES_DSN must point to a disposable PostgreSQL test database." >&2
      echo "       Or set MREADER_TEST_POSTGRES_MODE=docker to create a fully ephemeral Docker test runtime." >&2
      exit 2
    fi
    if [[ "${MREADER_TEST_POSTGRES_CONFIRM:-}" != "disposable" ]]; then
      echo "ERROR: set MREADER_TEST_POSTGRES_CONFIRM=disposable to confirm this is an isolated test database." >&2
      exit 2
    fi
    check_host_go
    run_tests_with_host_go
    ;;
  docker)
    if [[ -n "${MREADER_TEST_POSTGRES_DSN:-}" ]]; then
      echo "ERROR: MREADER_TEST_POSTGRES_DSN must be unset in docker mode to avoid an ambiguous test target." >&2
      exit 2
    fi
    if ! command -v docker >/dev/null 2>&1; then
      echo "ERROR: Docker is required for MREADER_TEST_POSTGRES_MODE=docker." >&2
      exit 2
    fi

    POSTGRES_IMAGE="${MREADER_P06_3_POSTGRES_IMAGE:-postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297}"
    GO_IMAGE="${MREADER_P06_3_GO_IMAGE:-golang:1.25.0-alpine3.22@sha256:f18a072054848d87a8077455f0ac8a25886f2397f88bfdd222d6fafbb5bba440}"
    POSTGRES_USER="mreader_p06_3"
    POSTGRES_DB="mreader_p06_3"
    POSTGRES_PASSWORD="mreader_p06_3_${RANDOM}_$$"
    DOCKER_CONTAINER="mreader-p06-3-${RANDOM}-$$"
    DOCKER_NETWORK="mreader-p06-3-net-${RANDOM}-$$"

    docker network create "$DOCKER_NETWORK" >/dev/null
    docker run -d --rm \
      --name "$DOCKER_CONTAINER" \
      --network "$DOCKER_NETWORK" \
      --tmpfs /var/lib/postgresql/data:rw \
      -e "POSTGRES_USER=$POSTGRES_USER" \
      -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
      -e "POSTGRES_DB=$POSTGRES_DB" \
      "$POSTGRES_IMAGE" >/dev/null

    ready=false
    for _ in $(seq 1 60); do
      if docker exec "$DOCKER_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        ready=true
        break
      fi
      sleep 1
    done
    if [[ "$ready" != true ]]; then
      echo "ERROR: disposable PostgreSQL container did not become ready." >&2
      exit 1
    fi

    MIGRATION_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/mreader-p06-3-migrations.XXXXXXXX")"
    sh "$ROOT/ops/migrate/render.sh" \
      "$ROOT/db/migrations" \
      "$ROOT/db/upgrade/preserve-reading-evidence.sql" >"$MIGRATION_SCRIPT"
    docker exec -i \
      -e "PGPASSWORD=$POSTGRES_PASSWORD" \
      "$DOCKER_CONTAINER" \
      psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <"$MIGRATION_SCRIPT"

    docker_root="$ROOT"
    case "$(uname -s 2>/dev/null || true)" in
      MINGW*|MSYS*|CYGWIN*)
        if command -v cygpath >/dev/null 2>&1; then
          docker_root="$(cygpath -w "$ROOT")"
        fi
        ;;
    esac
    test_dsn="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DOCKER_CONTAINER}:5432/${POSTGRES_DB}?sslmode=disable"
    MSYS_NO_PATHCONV=1 docker run --rm \
      --network "$DOCKER_NETWORK" \
      -e "MREADER_TEST_POSTGRES_DSN=$test_dsn" \
      -e "GOTOOLCHAIN=local" \
      --mount "type=bind,src=$docker_root,dst=/workspace,readonly" \
      "$GO_IMAGE" \
      sh -lc "cp -a /workspace/services/catalog_go /tmp/catalog_go && cd /tmp/catalog_go && go mod tidy && go mod verify && go test ./internal/store -run '^(TestCommitPublication.*|TestMediaCompletionEvidenceIsDatabaseImmutable)$' -count=1 -v && cp -a /workspace/services/notification_worker /tmp/notification_worker && cd /tmp/notification_worker && go mod download && go mod verify && go test ./internal/events ./internal/store -count=1 -v"
    ;;
  *)
    echo "ERROR: unsupported MREADER_TEST_POSTGRES_MODE=$MODE (expected dsn or docker)." >&2
    exit 2
    ;;
esac
