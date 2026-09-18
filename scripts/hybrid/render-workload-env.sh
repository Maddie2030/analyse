#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/env/env-lib.sh"

usage(){ echo "Usage: $0 SOURCE_ENV KEY_ALLOWLIST OUTPUT_ENV" >&2; exit 2; }
[[ $# -eq 3 ]] || usage
source_env="$1"
key_file="$2"
output_env="$3"
[[ -f "$source_env" ]] || { echo "ERROR: source env not found: $source_env" >&2; exit 2; }
[[ -f "$key_file" ]] || { echo "ERROR: key allowlist not found: $key_file" >&2; exit 2; }

mkdir -p "$(dirname "$output_env")"
tmp="${output_env}.tmp.$$"
rm -f "$tmp"
cleanup(){ rm -f "$tmp"; }
trap cleanup EXIT
: > "$tmp"

declare -A seen=()
while IFS= read -r raw || [[ -n "$raw" ]]; do
  raw="${raw%$'\r'}"
  [[ -n "$raw" ]] || continue
  [[ "$raw" == \#* ]] && continue
  key="$raw"
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "ERROR: invalid env key in $key_file: $key" >&2
    exit 2
  }
  [[ -z "${seen[$key]+x}" ]] || {
    echo "ERROR: duplicate env key in $key_file: $key" >&2
    exit 2
  }
  seen[$key]=1

  set +e
  value="$(awk -v k="$key" '
    index($0,k "=")==1 { found=1; v=substr($0,length(k)+2) }
    END { if(found) { sub(/\r$/, "", v); printf "%s", v } else exit 3 }
  ' "$source_env")"
  rc=$?
  set -e
  if [[ $rc -eq 3 ]]; then
    continue
  fi
  [[ $rc -eq 0 ]] || { echo "ERROR: failed reading $key from $source_env" >&2; exit "$rc"; }
  _env_validate_value "$value" || { echo "ERROR: refusing oversized/multiline value for $key" >&2; exit 2; }
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
done < "$key_file"

mv -f "$tmp" "$output_env"
trap - EXIT
