#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mapfile -t files < <(find scripts tests -type f -name '*.sh' -print | sort)
for file in "${files[@]}"; do
  # Comments and string literals mentioning Python are fine; an executable host
  # command beginning with python/python3 is not.
  if awk '
    /^[[:space:]]*#/ {next}
    {
      line=$0
      if(line ~ /^[[:space:]]*python3?[[:space:]-]/ || line ~ /[;&|][[:space:]]*python3?[[:space:]-]/ || line ~ /\$\([[:space:]]*python3?[[:space:]-]/){print FILENAME ":" NR ":" line; bad=1}
    }
    END{if(bad)exit 1}
  ' "$file"; then
    :
  else
    echo "hybrid host dependency regression FAILED: host Python invocation found in $file" >&2
    exit 1
  fi
done

[[ -x scripts/hybrid/python-runtime.sh ]] || {
  echo 'hybrid host dependency regression FAILED: scripts/hybrid/python-runtime.sh is missing or not executable' >&2
  exit 1
}

grep -q 'MREADER_PYTHON_FORCE_DOCKER' scripts/hybrid/python-runtime.sh || {
  echo 'hybrid host dependency regression FAILED: Python runtime has no forced Docker fallback test hook' >&2
  exit 1
}
grep -q 'python:3.12.11-slim-bookworm' scripts/hybrid/python-runtime.sh || {
  echo 'hybrid host dependency regression FAILED: Python runtime fallback is not version-pinned to the project Python line' >&2
  exit 1
}

tmp="$(mktemp -d)"
cleanup(){ rm -rf "$tmp"; }
trap cleanup EXIT
cat >"$tmp/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "info" ]]; then exit 0; fi
printf '%s\n' "$@" >"${MREADER_FAKE_DOCKER_LOG:?}"
DOCKER
chmod +x "$tmp/docker"
MREADER_FAKE_DOCKER_LOG="$tmp/docker.log" \
MREADER_PYTHON_FORCE_DOCKER=1 \
PATH="$tmp:$PATH" \
  scripts/hybrid/python-runtime.sh -c 'print("fallback")'
grep -Fxq 'run' "$tmp/docker.log" || {
  echo 'hybrid host dependency regression FAILED: Docker fallback did not invoke docker run' >&2
  exit 1
}
grep -Fxq 'python:3.12.11-slim-bookworm' "$tmp/docker.log" || {
  echo 'hybrid host dependency regression FAILED: Docker fallback did not use the expected Python image' >&2
  exit 1
}
grep -Fxq 'python' "$tmp/docker.log" || {
  echo 'hybrid host dependency regression FAILED: Docker fallback did not invoke Python in-container' >&2
  exit 1
}


# Git Bash may supply an external host file in canonical Windows drive form.
# The Docker fallback must mount that file and pass a container path to Python;
# forwarding Z:/... literally would make the Linux Python container unable to
# read an otherwise valid host file (the P09.4 restore-control failure mode).
mkdir -p "$tmp/windows-host-input"
printf '{}\n' >"$tmp/windows-host-input/control.json"
cat >"$tmp/uname" <<'UNAME'
#!/usr/bin/env bash
printf '%s\n' 'MINGW64_NT-10.0'
UNAME
cat >"$tmp/cygpath" <<'CYGPATH'
#!/usr/bin/env bash
set -euo pipefail
mode="${1:-}"
value="${2:-}"
case "$mode" in
  -w)
    if [[ "$value" =~ ^[A-Za-z]:/ ]]; then
      printf '%s\n' "${value//\//\\}"
    else
      printf '%s\n' 'C:\\mreader-repo'
    fi
    ;;
  -u)
    if [[ "$value" == 'Z:/mreader-python-runtime-test/control.json' ]]; then
      printf '%s\n' "${MREADER_FAKE_WINDOWS_POSIX_PATH:?}"
    else
      printf '%s\n' "$value"
    fi
    ;;
  *) exit 2 ;;
esac
CYGPATH
chmod +x "$tmp/uname" "$tmp/cygpath"
: >"$tmp/docker.log"
MREADER_FAKE_DOCKER_LOG="$tmp/docker.log" \
MREADER_FAKE_WINDOWS_POSIX_PATH="$tmp/windows-host-input/control.json" \
MREADER_PYTHON_FORCE_DOCKER=1 \
PATH="$tmp:$PATH" \
  scripts/hybrid/python-runtime.sh 'Z:/mreader-python-runtime-test/control.json'
grep -Fq 'target=/mreader-host-input-0,readonly' "$tmp/docker.log" || {
  echo 'hybrid host dependency regression FAILED: Windows drive-form host input was not bind-mounted into the Docker Python runtime' >&2
  exit 1
}
grep -Fxq '/mreader-host-input-0' "$tmp/docker.log" || {
  echo 'hybrid host dependency regression FAILED: Windows drive-form host input was forwarded literally instead of mapped to the container path' >&2
  exit 1
}

echo 'hybrid no-host-python regression PASSED'
