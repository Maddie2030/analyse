#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/env/env-lib.sh"
file="${1:-$ROOT/.env}"
[[ -f "$file" ]] || { echo "ERROR: env file not found: $file" >&2; exit 2; }

random_hex_32(){
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi
  if [[ -r /dev/urandom ]] && command -v od >/dev/null 2>&1; then
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    return
  fi
  echo "ERROR: openssl or /dev/urandom+od is required to generate private transport credentials." >&2
  return 2
}

for key in CATALOG_INTERNAL_TOKEN MEDIA_INTERNAL_TOKEN RECOVERY_BRIDGE_TOKEN; do
  current="$(env_get "$file" "$key")"
  if [[ -z "$current" ]]; then
    env_set "$file" "$key" "$(random_hex_32)"
    echo "Generated local $key"
  fi
done
