#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# Remove only known interrupted-write/transient files. Corrupt .env backups are
# intentionally retained until the user verifies the recovered configuration.
find . -maxdepth 2 -type f \( -name '.env.tmp.*' -o -name '.env.bak' -o -name '*.env.tmp.*' \) -print -delete 2>/dev/null || true
find .runtime -maxdepth 1 -type f -name '*.tmp.*' -print -delete 2>/dev/null || true
echo "Transient env/runtime garbage cleanup complete."
echo "Oversized .env.corrupt.* files are not deleted automatically; remove them after verifying .env."
