#!/usr/bin/env bash
# Shared bounded .env helpers. Designed for Git Bash/Linux and safe on accidentally huge files.
set -euo pipefail

MREADER_ENV_MAX_BYTES="${MREADER_ENV_MAX_BYTES:-1048576}"        # 1 MiB hard sanity ceiling
MREADER_ENV_SALVAGE_BYTES="${MREADER_ENV_SALVAGE_BYTES:-2097152}" # scan only first 2 MiB of corrupt file
MREADER_ENV_MAX_VALUE_BYTES="${MREADER_ENV_MAX_VALUE_BYTES:-16384}"
MREADER_LOCAL_ORIGINS="${MREADER_LOCAL_ORIGINS:-http://localhost,http://localhost:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080,http://localhost:8081,http://127.0.0.1:8081}"

_env_size() {
  local f="$1"
  [[ -f "$f" ]] || { echo 0; return; }
  # GNU/MSYS stat first, wc fallback.
  stat -c '%s' "$f" 2>/dev/null || wc -c < "$f" | tr -d ' '
}

_env_validate_value() {
  local value="$1"
  [[ ${#value} -le $MREADER_ENV_MAX_VALUE_BYTES ]] || return 1
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]]
}

_env_known_keys_file() {
  local example="$1" out="$2"
  awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' "$example" | sort -u > "$out"
}

# Atomic key update; collapses duplicate assignments of the same key.
env_set() {
  local file="$1" key="$2" value="$3" tmp
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "ERROR: invalid env key: $key" >&2; return 2; }
  _env_validate_value "$value" || { echo "ERROR: refusing oversized/multiline value for $key" >&2; return 2; }
  [[ -f "$file" ]] || { echo "ERROR: env file does not exist: $file" >&2; return 2; }
  tmp="${file}.tmp.$$"
  awk -v k="$key" -v v="$value" '
    BEGIN { found=0 }
    index($0, k "=")==1 {
      if (!found) { print k "=" v; found=1 }
      next
    }
    { print }
    END { if (!found) print k "=" v }
  ' "$file" > "$tmp"
  mv -f "$tmp" "$file"
}

env_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  awk -v k="$key" 'index($0,k "=")==1 {v=substr($0,length(k)+2)} END{if(v!="") print v}' "$file" | tr -d '\r'
}

env_public_url_valid() {
  local url="$1"
  [[ -z "$url" ]] && return 1
  [[ ${#url} -le 512 ]] || return 1
  [[ "$url" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9](:[0-9]{1,5})?$ ]]
}

env_rebuild_allowed_origin() {
  local file="$1" public_csv="${2:-}" value="$MREADER_LOCAL_ORIGINS"
  if [[ -n "$public_csv" ]]; then value+=",$public_csv"; fi
  env_set "$file" ALLOWED_ORIGIN "$value"
  env_set "$file" PUBLIC_ALLOWED_ORIGINS "$public_csv"
  env_set "$file" PUBLIC_BASE_URLS "$public_csv"
}

# Detect corrupt/garbage env files and rebuild without loading the entire file.
# The old file is MOVED, never copied, so a 13+ GB corrupt file does not duplicate disk use.
env_ensure_healthy() {
  local file="${1:-.env}" example="${2:-.env.example}" size stamp corrupt keys tmp salvage
  [[ -f "$example" ]] || { echo "ERROR: missing $example" >&2; return 2; }
  if [[ ! -f "$file" ]]; then cp "$example" "$file"; return 0; fi
  size="$(_env_size "$file")"
  if [[ "$size" =~ ^[0-9]+$ ]] && (( size <= MREADER_ENV_MAX_BYTES )); then
    # Small-file structural sanity: no absurd line lengths and only text-like data.
    if LC_ALL=C awk 'length($0)>32768{exit 8} END{if(NR>5000) exit 9}' "$file" >/dev/null 2>&1; then
      return 0
    fi
  fi

  stamp="$(date +%Y%m%d-%H%M%S)"
  corrupt="${file}.corrupt.${stamp}.${size}bytes"
  echo "WARNING: $file is corrupt/oversized (${size} bytes). Moving it to: $corrupt" >&2
  mv -f "$file" "$corrupt"
  cp "$example" "$file"

  # Salvage only known keys from the bounded prefix of the corrupt file. This preserves
  # normal secrets/NAS settings that were at the top while refusing arbitrary log garbage.
  keys="${file}.keys.$$"; tmp="${file}.salvage.$$"; salvage="${file}.salvage-input.$$"
  _env_known_keys_file "$example" "$keys"
  head -c "$MREADER_ENV_SALVAGE_BYTES" "$corrupt" > "$salvage" 2>/dev/null || true
  awk -F= 'NR==FNR{ok[$1]=1;next}
    /^[A-Za-z_][A-Za-z0-9_]*=/ {
      k=$1; if(!ok[k]) next;
      v=substr($0,index($0,"=")+1);
      if(length(v)<=16384 && v !~ /[[:cntrl:]]/) latest[k]=v
    }
    END{for(k in latest) print k "=" latest[k]}
  ' "$keys" "$salvage" > "$tmp"
  while IFS='=' read -r key value; do
    [[ -n "$key" ]] || continue
    env_set "$file" "$key" "$value" || true
  done < "$tmp"
  rm -f "$keys" "$tmp" "$salvage" "${file}.tmp."* "${file}.bak" 2>/dev/null || true

  echo "Recovered a clean $file from $example plus bounded known-key salvage." >&2
  echo "The moved corrupt file was NOT copied. After verifying settings, delete it to reclaim disk:" >&2
  echo "  rm -f '$corrupt'" >&2
}
