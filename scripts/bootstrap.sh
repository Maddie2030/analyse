#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose v2 is required." >&2; exit 1; }

# A fresh release archive intentionally has no .env. Create it before the
# one-time stateful-volume adoption step, because adoption records the selected
# authoritative Docker volume names in this file.
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

source ./scripts/env/env-lib.sh
saved_db_protection_root="$(env_get .env MREADER_DB_PROTECTION_ROOT)"
if [[ -z "$saved_db_protection_root" ]]; then
  # A blank saved root may still have an intentional process-level override.
  # Honor it only when the shared resolver accepts it; otherwise treat it as
  # stale shell state and establish the dedicated platform default.
  if [[ -n "${MREADER_DB_PROTECTION_ROOT:-}" ]] &&
     resolved_db_protection_root="$(bash ./scripts/env/resolve-db-protection-root.sh .env 2>/dev/null)"; then
    MREADER_DB_PROTECTION_ROOT="$resolved_db_protection_root"
  else
    MREADER_DB_PROTECTION_ROOT="$(MREADER_DB_PROTECTION_ROOT= bash ./scripts/env/resolve-db-protection-root.sh .env)"
  fi
else
  MREADER_DB_PROTECTION_ROOT="$(bash ./scripts/env/resolve-db-protection-root.sh .env)"
fi
export MREADER_DB_PROTECTION_ROOT
mkdir -p "$MREADER_DB_PROTECTION_ROOT"
[[ -d "$MREADER_DB_PROTECTION_ROOT" && ! -L "$MREADER_DB_PROTECTION_ROOT" ]] || {
  echo "ERROR: database-protection root could not be created safely: $MREADER_DB_PROTECTION_ROOT" >&2
  exit 2
}

./scripts/hybrid/adopt-existing-stateful-volumes.sh .env

if grep -q '^TOKEN_SECRET=change-me-in-production-use-a-long-random-string$' .env; then
  if command -v openssl >/dev/null 2>&1; then
    SECRET="$(openssl rand -hex 32)"
    # sed syntax works in GNU sed and Git Bash sed.
    sed -i "s|^TOKEN_SECRET=change-me-in-production-use-a-long-random-string$|TOKEN_SECRET=${SECRET}|" .env
    echo "Generated a local TOKEN_SECRET"
  elif [[ -r /dev/urandom ]] && command -v od >/dev/null 2>&1; then
    SECRET="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
    sed -i "s|^TOKEN_SECRET=change-me-in-production-use-a-long-random-string$|TOKEN_SECRET=${SECRET}|" .env
    echo "Generated a local TOKEN_SECRET"
  else
    echo "WARNING: could not generate TOKEN_SECRET automatically; set it manually in .env." >&2
  fi
fi

mkdir -p backups
./scripts/preflight.sh
printf 'MReader ready (%s)\n' "$(cat VERSION)"
