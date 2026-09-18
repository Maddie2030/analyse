#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

force_docker="${MREADER_PYTHON_FORCE_DOCKER:-0}"
if [[ "$force_docker" != "1" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    exec python3 "$@"
  fi
  if command -v python >/dev/null 2>&1; then
    exec python "$@"
  fi
  if command -v py >/dev/null 2>&1; then
    exec py -3 "$@"
  fi
fi

command -v docker >/dev/null 2>&1 || {
  echo "ERROR: Python 3 is not available on the host and Docker is unavailable for the fallback runtime." >&2
  exit 2
}

docker info >/dev/null 2>&1 || {
  echo "ERROR: Python 3 is not available on the host and Docker Engine is not ready for the fallback runtime." >&2
  exit 2
}

image="${MREADER_PYTHON_DOCKER_IMAGE:-python:3.12.11-slim-bookworm}"
os="$(uname -s 2>/dev/null || true)"

host_path_for_docker(){
  local value="$1"
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$value"
      else
        printf '%s\n' "$value"
      fi
      ;;
    *) printf '%s\n' "$value" ;;
  esac
}

host_input_exists(){
  local value="$1"
  local probe="$value"
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      if [[ "$value" =~ ^[A-Za-z]:[/\\] ]] && command -v cygpath >/dev/null 2>&1; then
        probe="$(cygpath -u "$value" 2>/dev/null || printf '%s\n' "$value")"
      fi
      ;;
  esac
  [[ -e "$probe" ]]
}

mount_root="$(host_path_for_docker "$ROOT")"
docker_args=(run --rm -i --mount "type=bind,source=${mount_root},target=/repo" -w /repo)

# Preserve only the runtime role passwords needed by the PostgreSQL grant renderer.
# Using -e NAME forwards the value without embedding the secret in the command line.
while IFS= read -r name; do
  [[ "$name" == MREADER_DB_ROLE_PASSWORD_* ]] || continue
  docker_args+=(-e "$name")
done < <(compgen -e)

mapped_args=()
extra_mount_index=0
for arg in "$@"; do
  if [[ "$arg" == "$ROOT" ]]; then
    mapped_args+=(/repo)
  elif [[ "$arg" == "$ROOT"/* ]]; then
    mapped_args+=("/repo/${arg#"$ROOT"/}")
  elif [[ "$os" =~ ^(MINGW|MSYS|CYGWIN) && "$arg" =~ ^[A-Za-z]:[/\\] ]] && host_input_exists "$arg"; then
    target="/mreader-host-input-${extra_mount_index}"
    source_path="$(host_path_for_docker "$arg")"
    docker_args+=(--mount "type=bind,source=${source_path},target=${target},readonly")
    mapped_args+=("$target")
    extra_mount_index=$((extra_mount_index + 1))
  elif [[ "$arg" == /* && -e "$arg" ]]; then
    target="/mreader-host-input-${extra_mount_index}"
    source_path="$(host_path_for_docker "$arg")"
    docker_args+=(--mount "type=bind,source=${source_path},target=${target},readonly")
    mapped_args+=("$target")
    extra_mount_index=$((extra_mount_index + 1))
  else
    mapped_args+=("$arg")
  fi
done

case "$os" in
  MINGW*|MSYS*|CYGWIN*)
    # Prevent Git Bash from rewriting container-internal POSIX paths.
    export MSYS2_ARG_CONV_EXCL="${MSYS2_ARG_CONV_EXCL:-};/repo;/mreader-host-input-"
    ;;
  *)
    if command -v id >/dev/null 2>&1; then
      docker_args+=(--user "$(id -u):$(id -g)")
    fi
    ;;
esac

exec docker "${docker_args[@]}" "$image" python "${mapped_args[@]}"
