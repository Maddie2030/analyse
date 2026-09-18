#!/usr/bin/env bash
# Minimal jq-compatible fixture for backup-daily-policy.sh.
# It intentionally implements only the expressions exercised by that isolated
# policy simulation so Windows Git Bash does not need a host jq installation.
set -euo pipefail

args=("$@")
joined=" $* "

arg_value(){
  local want="$1" i
  for ((i=0; i<${#args[@]}-2; i++)); do
    if [[ "${args[$i]}" == "--arg" || "${args[$i]}" == "--argjson" ]] \
        && [[ "${args[$((i+1))]}" == "$want" ]]; then
      printf '%s' "${args[$((i+2))]}"
      return 0
    fi
  done
  return 1
}

json_escape(){
  sed 's/\\/\\\\/g; s/"/\\"/g'
}

json_input(){
  local candidate="${args[${#args[@]}-1]}"
  if [[ -f "$candidate" ]]; then
    cat "$candidate"
  else
    cat
  fi
}

# Fake SeaweedFS directory listing builder used by the curl fixture.
if [[ "$joined" == *" -Rn "* ]]; then
  prefix="$(arg_value p || true)"
  printf '{"Entries":[\n'
  first=1
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    path="${prefix%/}/$name"
    [[ -n "$prefix" ]] || path="/$name"
    esc="$(printf '%s' "$path" | json_escape)"
    if [[ $first -eq 0 ]]; then printf ',\n'; fi
    printf '{"FullPath":"%s","FileSize":0}' "$esc"
    first=0
  done
  printf '\n]}\n'
  exit 0
fi

# Raw extraction expressions used against fixture JSON.
if [[ "$joined" == *" .Entries[]?.FullPath // empty "* ]]; then
  sed -n 's/.*"FullPath":"\([^"]*\)".*/\1/p'
  exit 0
fi

if [[ "$joined" == *" startswith(\$d)"* && "$joined" == *" | length "* ]]; then
  day="$(arg_value d || true)"
  count=0
  while IFS= read -r line; do
    if [[ "$line" == *'"type":"daily"'* || "$line" == *'"type":"manual"'* ]]; then
      if [[ "$line" == *"\"timestamp_local\":\"$day"* ]]; then
        count=$((count+1))
      fi
    fi
  done
  printf '%s\n' "$count"
  exit 0
fi

if [[ "$joined" == *" sort_by(.timestamp_utc) | last | .filename // empty "* ]]; then
  last=""
  while IFS= read -r line; do
    if [[ "$line" == *'"type":"daily"'* || "$line" == *'"type":"manual"'* ]]; then
      value="$(printf '%s\n' "$line" | sed -n 's/.*"filename":"\([^"]*\)".*/\1/p')"
      [[ -z "$value" ]] || last="$value"
    fi
  done
  printf '%s\n' "$last"
  exit 0
fi


# Optional boolean/null storage-proof field reader.
if [[ "$joined" == *'runtime_mount_matches_config'* && "$joined" == *'has("runtime_mount_matches_config")'* ]]; then
  content="$(json_input)"
  if grep -q '"runtime_mount_matches_config":true' <<<"$content"; then
    printf 'true\n'
  elif grep -q '"runtime_mount_matches_config":false' <<<"$content"; then
    printf 'false\n'
  else
    printf 'unknown\n'
  fi
  exit 0
fi

# NAS storage-proof validation/field extraction.
if [[ "$joined" == *'.verified == true'* && "$joined" == *'.physical_volume_root'* && "$joined" == *'.logical_backup_root'* ]]; then
  content="$(json_input)"
  grep -q '"verified":true' <<<"$content" \
    && grep -q '"physical_volume_root":"[^"]\+"' <<<"$content" \
    && grep -q '"logical_backup_root":"[^"]\+"' <<<"$content"
  exit $?
fi
for field in physical_volume_root logical_backup_root; do
  if [[ "$joined" == *" .$field // empty "* ]]; then
    content="$(json_input)"
    sed -n "s/.*\"$field\":\"\\([^\"]*\\)\".*/\\1/p" <<<"$content" | head -n1
    exit 0
  fi
done

# Simple field readers used by backup-agent bookkeeping.
for field in request_id filename remote_url; do
  if [[ "$joined" == *" .$field // empty "* ]]; then
    input="${args[${#args[@]}-1]}"
    if [[ -f "$input" ]]; then
      sed -n "s/.*\"$field\":\"\\([^\"]*\\)\".*/\\1/p" "$input" | head -n1
    else
      sed -n "s/.*\"$field\":\"\\([^\"]*\\)\".*/\\1/p" | head -n1
    fi
    exit 0
  fi
done

# Slurp backup manifests into the remote index. The test only needs valid
# entries and today's timestamp/type/filename fields; sort order is immaterial.
if [[ "$joined" == *" -s "* && "$joined" == *"backups:(sort_by(.timestamp_utc)|reverse)"* ]]; then
  category="$(arg_value category || true)"
  generated="$(arg_value generated_local || true)"
  input="${args[${#args[@]}-1]}"
  count="$(grep -c '[^[:space:]]' "$input" 2>/dev/null || true)"
  printf '{"category":"%s","generated_local":"%s","count":%s,"backups":[\n' "$category" "$generated" "$count"
  first=1
  while IFS= read -r line; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    if [[ $first -eq 0 ]]; then printf ',\n'; fi
    printf '%s' "$line"
    first=0
  done < "$input"
  printf '\n]}\n'
  exit 0
fi

# Manifest creation.
if [[ "$joined" == *" -n "* && "$joined" == *"backup_id:\$backup_id"* ]]; then
  type="$(arg_value type || true)"
  trigger="$(arg_value trigger || true)"
  timestamp_utc="$(arg_value timestamp_utc || true)"
  timestamp_local="$(arg_value timestamp_local || true)"
  backup_id="$(arg_value backup_id || true)"
  filename="$(arg_value filename || true)"
  size="$(arg_value size || printf '0')"
  printf '{"backup_id":"%s","type":"%s","trigger":"%s","timestamp_utc":"%s","timestamp_local":"%s","filename":"%s","size_bytes":%s,"verified":true}\n' \
    "$backup_id" "$type" "$trigger" "$timestamp_utc" "$timestamp_local" "$filename" "$size"
  exit 0
fi

# Root index creation; category merge content is irrelevant to this focused
# daily/manual scheduling test but must remain syntactically valid JSON.
if [[ "$joined" == *" -n "* && "$joined" == *"categories:{}"* ]]; then
  generated="$(arg_value generated_local || true)"
  printf '{"generated_local":"%s","categories":{}}\n' "$generated"
  exit 0
fi

# Manual completion marker (kept for future policy coverage).
if [[ "$joined" == *" -n "* && "$joined" == *"request_id:\$request_id"* ]]; then
  request_id="$(arg_value request_id || true)"
  filename="$(arg_value filename || true)"
  remote_url="$(arg_value remote_url || true)"
  printf '{"request_id":"%s","filename":"%s","remote_url":"%s","verified_on_nas":true}\n' "$request_id" "$filename" "$remote_url"
  exit 0
fi

# Root-index category merge: preserve the existing root index. It is not read
# by the scheduling assertions in this fixture.
if [[ "$joined" == *" --slurpfile data "* && "$joined" == *".categories[\$c]=\$data[0]"* ]]; then
  input="${args[${#args[@]}-1]}"
  cat "$input"
  exit 0
fi

# Add remote_url to the latest manifest. The focused policy assertions do not
# consume this field, so preserving the manifest is sufficient.
if [[ "$joined" == *".remote_url=\$remote"* ]]; then
  input="${args[${#args[@]}-1]}"
  cat "$input"
  exit 0
fi

echo "fake-jq: unsupported invocation: jq $*" >&2
exit 64
