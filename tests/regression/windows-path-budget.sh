#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Keep distributable relative paths comfortably below Windows Explorer's legacy
# MAX_PATH once the repository is extracted below a normal user directory.
# Generated/cache trees are never part of release archives and are excluded.
MAX_RELATIVE_PATH=120
max=0
max_path=""
while IFS= read -r path; do
  rel="${path#./}"
  len=${#rel}
  if (( len > max )); then
    max=$len
    max_path=$rel
  fi
done < <(find . -type f \
  ! -path './.git/*' \
  ! -path './node_modules/*' \
  ! -path '*/node_modules/*' \
  ! -path '*/__pycache__/*' \
  ! -path './test-results/*' \
  ! -name '*.pyc' \
  -print | sort)

if (( max > MAX_RELATIVE_PATH )); then
  echo "ERROR: Windows path budget exceeded: ${max} chars > ${MAX_RELATIVE_PATH}: ${max_path}" >&2
  exit 1
fi

# Distribution policy: short archive/destination name prevents the old release
# name from being duplicated by Explorer's Extract All destination folder.
[[ -f WINDOWS-EXTRACT.txt ]]
grep -q 'mreader-rc484' WINDOWS-EXTRACT.txt
printf 'Windows path budget PASSED: longest distributable relative path = %d chars (%s)\n' "$max" "$max_path"
