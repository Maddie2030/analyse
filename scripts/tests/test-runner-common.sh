#!/usr/bin/env bash
# Shared observability/helpers for the Dockerized MReader test harness.
# shellcheck shell=bash

_TEST_RUNNER_SCRIPTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/docker/msys-paths.sh
source "$_TEST_RUNNER_SCRIPTS_ROOT/docker/msys-paths.sh"

TEST_RUNNER_STATUS_FILE="${TEST_RUNNER_STATUS_FILE:-${ROOT:-.}/test-results/.runner-status}"

# State recorded here is intentionally host-side so --status works even while
# Docker is still building an image and no test container exists yet.
test_set_status(){
  local phase="$1" detail="${2:-}" dir tmp
  dir="$(dirname "$TEST_RUNNER_STATUS_FILE")"
  mkdir -p "$dir"
  tmp="${TEST_RUNNER_STATUS_FILE}.tmp.$$"
  {
    printf 'updated_at=%s\n' "$(date -u +%FT%TZ)"
    printf 'pid=%s\n' "$$"
    printf 'phase=%s\n' "$phase"
    printf 'detail=%s\n' "$detail"
  } > "$tmp"
  mv "$tmp" "$TEST_RUNNER_STATUS_FILE"
}

test_now(){ date '+%Y-%m-%d %H:%M:%S'; }
test_log(){ printf '[%s] %s\n' "$(test_now)" "$*"; }
test_section(){ printf '\n[%s] ==> %s\n' "$(test_now)" "$*"; }

# Resolve the existing Docker Compose network that owns PostgreSQL/Valkey/RabbitMQ.
# Tests join this network for direct DB access while entering Kubernetes only via
# the host-exposed user/admin gateways.
test_stateful_network(){
  local cid network
  cid="$(docker compose --env-file .env -f deploy/compose/docker-compose.hybrid-stateful.yml ps -q db 2>/dev/null || true)"
  [[ -n "$cid" ]] || { echo "ERROR: hybrid PostgreSQL container is not running" >&2; return 1; }
  network="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$cid" 2>/dev/null | head -n1 | tr -d '\r')"
  [[ -n "$network" ]] || { echo "ERROR: could not determine hybrid stateful Docker network" >&2; return 1; }
  printf '%s\n' "$network"
}

test_remove_container(){
  docker rm -f "$1" >/dev/null 2>&1 || true
}

# Git for Windows/MSYS2 rewrites POSIX-looking command arguments before invoking
# native Windows binaries. That is useful for host bind paths, but corrupts
# container-internal paths such as /load/seed.py -> C:/Program Files/Git/load/seed.py.
# Exclude only known container path prefixes so ordinary host paths keep their
# normal MSYS conversion behaviour.
test_docker_run(){
  local os excl
  os="$(uname -s 2>/dev/null || true)"
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      excl='/load;/tests;/repo;/results;/spool;/migrations;/app;/etc/caddy'
      if [[ -n "${MSYS2_ARG_CONV_EXCL:-}" ]]; then excl="${MSYS2_ARG_CONV_EXCL};${excl}"; fi
      MSYS2_ARG_CONV_EXCL="$excl" docker run "$@"
      ;;
    *) docker run "$@" ;;
  esac
}

# Run a Dockerized test command with live logs. The stopped container is retained
# for post-failure inspection; the next run removes/replaces the same name.
run_docker_test(){
  local name="$1" logfile="$2"; shift 2
  local rc docker_rc tee_rc had_errexit=0
  local -a pipe_status
  [[ $- == *e* ]] && had_errexit=1
  test_remove_container "$name"
  test_set_status "container-start" "container=${name}"
  test_log "Starting test container ${name}"
  : > "$logfile"
  # docker/tee failures must be captured rather than letting errexit abort before
  # result copying/reporting. Restore the caller's original errexit state exactly.
  set +e
  test_docker_run --name "$name" "$@" 2>&1 | tee "$logfile"
  pipe_status=("${PIPESTATUS[@]}")
  docker_rc=${pipe_status[0]}
  tee_rc=${pipe_status[1]}
  rc=$docker_rc
  if [[ $rc -eq 0 && $tee_rc -ne 0 ]]; then
    rc=$tee_rc
  fi
  if [[ $had_errexit -eq 1 ]]; then set -e; else set +e; fi
  if [[ $rc -eq 0 ]]; then
    test_set_status "container-complete" "container=${name} exit=0"
    test_log "Container ${name} completed successfully"
  else
    test_set_status "container-failed" "container=${name} exit=${rc} docker_exit=${docker_rc} log_exit=${tee_rc}"
    if [[ $docker_rc -ne 0 ]]; then
      test_log "ERROR: container ${name} exited with ${docker_rc}"
    else
      test_log "ERROR: live log capture for ${name} failed with ${tee_rc}"
    fi
    docker inspect "$name" --format 'status={{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}} finished={{.State.FinishedAt}}' 2>/dev/null || true
  fi
  return "$rc"
}

# Copy optional /results content from a stopped test container into the host run dir.
test_copy_results(){
  local name="$1" dst="$2"
  mkdir -p "$dst"
  if mreader_docker_cp_from_container "${name}:/results/." "$dst/" >/dev/null 2>&1; then
    return 0
  fi
  test_log "ERROR: could not copy /results from ${name} into ${dst}"
  return 1
}
