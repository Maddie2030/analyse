#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fail(){ echo "MSYS Docker host/container path regression FAILED: $*" >&2; exit 1; }

[[ -f scripts/docker/msys-paths.sh ]] || fail 'shared MSYS Docker path helper is missing'

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

uname(){ printf '%s\n' 'MINGW64_NT-10.0-22631'; }
cygpath(){
  [[ "${1:-}" == '-m' ]] || fail "unexpected cygpath mode: ${1:-}"
  shift
  case "${1:-}" in
    /tmp/*) printf 'C:/msys%s\n' "$1" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
docker(){
  {
    printf 'MSYS_NO_PATHCONV=%s\n' "${MSYS_NO_PATHCONV:-}"
    printf 'args='; printf '%q ' "$@"; printf '\n'
  } > "$TMP/docker-call"
}

# shellcheck source=scripts/docker/msys-paths.sh
source scripts/docker/msys-paths.sh

mreader_docker_cp_to_container '/tmp/source with spaces.dump' 'db:/tmp/source.dump'
grep -Fxq 'MSYS_NO_PATHCONV=1' "$TMP/docker-call" || fail 'copy-to-container did not disable MSYS conversion'
grep -Fq 'C:/msys/tmp/source\ with\ spaces.dump' "$TMP/docker-call" || fail 'copy-to-container did not preconvert the host source path'
grep -Fq 'db:/tmp/source.dump' "$TMP/docker-call" || fail 'copy-to-container did not preserve the Linux container destination'

mreader_docker_cp_from_container 'db:/results/.' '/tmp/results with spaces'
grep -Fxq 'MSYS_NO_PATHCONV=1' "$TMP/docker-call" || fail 'copy-from-container did not disable MSYS conversion'
grep -Fq 'db:/results/.' "$TMP/docker-call" || fail 'copy-from-container did not preserve the Linux container source'
grep -Fq 'C:/msys/tmp/results\ with\ spaces' "$TMP/docker-call" || fail 'copy-from-container did not preconvert the host destination path'

mreader_docker_no_pathconv exec db sh -ceu 'cat /tmp/source.dump >/tmp/result'
grep -Fxq 'MSYS_NO_PATHCONV=1' "$TMP/docker-call" || fail 'container-only command did not disable MSYS conversion'
grep -Fq '/tmp/source.dump' "$TMP/docker-call" || fail 'container-only command lost its Linux path'

# The catalog recovery path must route every Docker command that can carry Linux
# container paths through the shared wrapper/copy helpers.
grep -Fq 'source "$ROOT/scripts/docker/msys-paths.sh"' scripts/recovery/catalog-restore.sh \
  || fail 'catalog recovery does not load the shared MSYS Docker helper'
! grep -Eq '(^|[;&[:space:]])docker[[:space:]]+(run|create|exec|cp)([[:space:]]|$)' scripts/recovery/catalog-restore.sh \
  || fail 'catalog recovery still contains raw run/create/exec/cp calls'

# Test result extraction is another mixed container-source/host-destination copy.
grep -Fq 'mreader_docker_cp_from_container "${name}:/results/." "$dst/"' scripts/tests/test-runner-common.sh \
  || fail 'test result copying does not use the shared mixed-path helper'

echo 'MSYS Docker host/container path regression PASS'
