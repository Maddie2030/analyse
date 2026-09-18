#!/usr/bin/env bash
# Shared Git-Bash/MSYS2-safe Docker path boundary helpers.
# shellcheck shell=bash

mreader_docker_is_windows_shell(){
  case "$(uname -s 2>/dev/null || true)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

# Print a host filesystem path in a form Docker Desktop's native Windows CLI can
# consume while MSYS argument conversion is disabled. Container paths must never
# be passed through this function.
mreader_docker_host_path(){
  local value="${1:?host path is required}"
  if ! mreader_docker_is_windows_shell; then
    printf '%s\n' "$value"
    return 0
  fi

  # The canonical database-protection resolver already emits C:/... on Windows.
  # Keep drive-form paths stable rather than passing them through MSYS twice.
  if [[ "$value" =~ ^[A-Za-z]:[/\\] ]]; then
    printf '%s\n' "${value//\\//}"
    return 0
  fi

  # Relative paths remain valid relative to Docker's inherited working directory.
  if [[ "$value" != /* ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$value"
    return 0
  fi

  printf 'ERROR: cannot convert Git-Bash host path for Docker without cygpath: %s\n' "$value" >&2
  return 2
}

# Use when every path-like argument belongs to the Linux container/Docker API
# namespace (for example /tmp/... or a named-volume target).
mreader_docker_no_pathconv(){
  MSYS_NO_PATHCONV=1 docker "$@"
}

mreader_docker_cp_to_container(){
  local host_source="${1:?host source path is required}"
  local container_destination="${2:?container destination is required}"
  local docker_source
  docker_source="$(mreader_docker_host_path "$host_source")" || return
  MSYS_NO_PATHCONV=1 docker cp "$docker_source" "$container_destination"
}

mreader_docker_cp_from_container(){
  local container_source="${1:?container source is required}"
  local host_destination="${2:?host destination path is required}"
  local docker_destination
  docker_destination="$(mreader_docker_host_path "$host_destination")" || return
  MSYS_NO_PATHCONV=1 docker cp "$container_source" "$docker_destination"
}
