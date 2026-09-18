#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
limit="${MREADER_CONFIG_MAX_BYTES:-2097152}"
echo "Checking mutable/config text files larger than ${limit} bytes..."
found=0
while IFS= read -r -d '' f; do
  size="$(stat -c '%s' "$f" 2>/dev/null || wc -c < "$f")"
  if (( size > limit )); then printf 'OVERSIZED\t%s\t%s bytes\n' "$f" "$size"; found=1; fi
done < <(find . -maxdepth 3 -type f \( -name '.env*' -o -name '*.log' -o -name '*.tmp*' -o -name '*.bak' -o -name '*.txt' \) -print0)
if (( found == 0 )); then echo "No oversized mutable/config files found."; fi
