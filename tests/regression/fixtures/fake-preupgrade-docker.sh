#!/usr/bin/env bash
set -euo pipefail

container="${DBP_FAKE_CONTAINER:?}"

require_no_pathconv() {
  if [[ "${DBP_FAKE_REQUIRE_NO_PATHCONV:-false}" == true && "${MSYS_NO_PATHCONV:-}" != 1 ]]; then
    echo "fake docker: missing MSYS_NO_PATHCONV=1 for container-path command" >&2
    exit 65
  fi
}

if [[ "$1" == compose && "${*: -3}" == "ps -q db" ]]; then
  printf 'fixture-db\n'
  exit 0
fi


if [[ "$1" == compose && "$*" == *"run --rm --build --no-deps --entrypoint /usr/local/bin/mreader-local-recovery-store backup_agent publish-staged /mreader-db-protection /mreader-db-protection/staging/"* ]]; then
  require_no_pathconv
  if [[ "${DBP_FAKE_REQUIRE_NATIVE_COMPOSE_PATHS:-false}" == true ]]; then
    env_path=""
    compose_path=""
    for ((i = 1; i <= $#; i++)); do
      if [[ "${!i}" == --env-file ]]; then
        j=$((i + 1)); env_path="${!j}"
      elif [[ "${!i}" == -f ]]; then
        j=$((i + 1)); compose_path="${!j}"
      fi
    done
    [[ "$env_path" == [A-Za-z]:/* ]] || { echo "fake docker: env-file path was not preconverted for Windows: $env_path" >&2; exit 67; }
    [[ "$compose_path" == [A-Za-z]:/* ]] || { echo "fake docker: compose path was not preconverted for Windows: $compose_path" >&2; exit 68; }
  fi
  recovery_id="$(basename "${@: -1}")"
  root="${MREADER_DB_PROTECTION_ROOT:?}"
  staging="$root/staging/$recovery_id"
  final="$root/dumps/pre-upgrade/$recovery_id"
  mkdir -p "$(dirname "$final")"
  [[ -d "$staging" ]] || { echo "fake docker: staged recovery bundle missing" >&2; exit 66; }
  mv "$staging" "$final"
  printf '%s\n' "/mreader-db-protection/dumps/pre-upgrade/$recovery_id"
  exit 0
fi

if [[ "$1" == exec && "$2" == fixture-db && "$3" == sh ]]; then
  require_no_pathconv
  [[ "${DBP_FAKE_CAPTURE_FAIL:-false}" != true ]] || exit 41
  dump="${@: -3:1}"
  globals="${@: -2:1}"
  metadata="${@: -1:1}"
  printf 'PGDMP-fixture\n' > "$container/$(basename "$dump")"
  printf '%s\n' '-- PostgreSQL globals fixture' > "$container/$(basename "$globals")"
  dump_sha="$(sha256sum "$container/$(basename "$dump")" | awk '{print $1}')"
  globals_sha="$(sha256sum "$container/$(basename "$globals")" | awk '{print $1}')"
  printf '%s\n' '160010' 'mreader' "$dump_sha" "$globals_sha" > "$container/$(basename "$metadata")"
  exit 0
fi

if [[ "$1" == cp ]]; then
  require_no_pathconv
  source_path="${2#fixture-db:}"
  cp "$container/$(basename "$source_path")" "$3"
  if [[ "${DBP_FAKE_CORRUPT_COPY:-false}" == true && "$source_path" == *.dump ]]; then
    printf 'corruption' >> "$3"
  fi
  exit 0
fi

if [[ "$1" == exec && "$2" == fixture-db && "$3" == rm ]]; then
  require_no_pathconv
  shift 3
  for path in "$@"; do
    [[ "$path" == -f ]] && continue
    rm -f "$container/$(basename "$path")"
  done
  exit 0
fi

exit 64
