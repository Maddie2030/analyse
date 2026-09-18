#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$ROOT"

services=(
  services/reader_go
  services/catalog_go
  services/progress_go
  services/realtime_go
  services/notification_worker
  services/outbox_relay
)

failed=0
while IFS= read -r file; do
  while IFS='|' read -r alias import_path; do
    [[ -n "$import_path" ]] || continue
    [[ "$alias" == '_' || "$alias" == '.' ]] && continue

    if [[ -n "$alias" ]]; then
      ident="$alias"
    else
      ident="${import_path##*/}"
      if [[ "$ident" =~ ^v[0-9]+$ ]]; then
        parent="${import_path%/*}"
        ident="${parent##*/}"
      fi
      case "$ident" in
        go-redis) ident=redis ;;
        amqp091-go) ident=amqp091 ;;
        *) ident="${ident//-/_}" ;;
      esac
    fi

    # Go requires ordinary imports to be referenced through their package
    # identifier. The import declaration itself cannot satisfy this pattern.
    if ! grep -Eq "(^|[^[:alnum:]_])${ident}[[:space:]]*\\." "$file"; then
      printf 'ERROR: unused Go import candidate: %s: %s (identifier %s)\n' \
        "$file" "$import_path" "$ident" >&2
      failed=1
    fi
  done < <(
    awk '
      /^import[[:space:]]*\(/ { inblock=1; next }
      inblock && /^\)/ { inblock=0; next }
      inblock {
        line=$0
        sub(/^[[:space:]]+/, "", line)
        if (line ~ /^"[^"]+"/) {
          sub(/^"/, "", line)
          sub(/".*$/, "", line)
          print "|" line
        } else if (line ~ /^[_A-Za-z.][_A-Za-z0-9.]*[[:space:]]+"[^"]+"/) {
          alias=line
          sub(/[[:space:]].*$/, "", alias)
          path=line
          sub(/^[_A-Za-z.][_A-Za-z0-9.]*[[:space:]]+"/, "", path)
          sub(/".*$/, "", path)
          print alias "|" path
        }
        next
      }
      /^import[[:space:]]+"[^"]+"/ {
        line=$0
        sub(/^import[[:space:]]+"/, "", line)
        sub(/".*$/, "", line)
        print "|" line
        next
      }
      /^import[[:space:]]+[_A-Za-z.][_A-Za-z0-9.]*[[:space:]]+"[^"]+"/ {
        line=$0
        sub(/^import[[:space:]]+/, "", line)
        alias=line
        sub(/[[:space:]].*$/, "", alias)
        path=line
        sub(/^[_A-Za-z.][_A-Za-z0-9.]*[[:space:]]+"/, "", path)
        sub(/".*$/, "", path)
        print alias "|" path
      }
    ' "$file"
  )
done < <(find "${services[@]}" -type f -name '*.go' -print | sort)

[[ "$failed" -eq 0 ]] || exit 1
printf '%s\n' 'go import usage guard: ok'
