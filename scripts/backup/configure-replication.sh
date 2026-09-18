#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
ENV_FILE="${1:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "ERROR: application environment file is required." >&2; exit 2; }
MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")"
export MREADER_DB_PROTECTION_ROOT

rep_user="$(env_get "$ENV_FILE" POSTGRES_BACKUP_REPLICATION_USER)"
rep_user="${rep_user:-mreader_backup}"
rep_pass="$(env_get "$ENV_FILE" POSTGRES_BACKUP_REPLICATION_PASSWORD)"
[[ -n "$rep_pass" ]] || rep_pass="$(env_get "$ENV_FILE" POSTGRES_PASSWORD)"
[[ -n "$rep_pass" ]] || { echo "ERROR: POSTGRES_PASSWORD/POSTGRES_BACKUP_REPLICATION_PASSWORD is empty." >&2; exit 2; }
[[ "$rep_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "ERROR: invalid replication role name." >&2; exit 2; }

# POSTGRES_USER created by the official image is the local cluster superuser.
# Configure the role and HBA inside the DB container so this repairs existing
# named volumes as well as fresh installs.
docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml exec -T \
  -e MREADER_REPL_USER="$rep_user" -e MREADER_REPL_PASS="$rep_pass" db sh <<'EOS'
set -eu
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v rep_user="$MREADER_REPL_USER" -v rep_password="$MREADER_REPL_PASS" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L', :'rep_user', :'rep_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'rep_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L', :'rep_user', :'rep_password')
\gexec
SQL

hba_file="$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc 'SHOW hba_file')"
marker="# mreader-backup-replication"
rule="host replication \"$MREADER_REPL_USER\" samenet scram-sha-256"
if ! grep -Fq "$marker" "$hba_file"; then
  printf '\n%s\n%s\n' "$marker" "$rule" >> "$hba_file"
else
  # Keep exactly one managed rule and allow role-name changes safely.
  tmp="${hba_file}.mreader.$$"
  awk -v marker="$marker" -v rule="$rule" '
    $0==marker { print marker; print rule; skip=1; next }
    skip==1 { skip=0; next }
    { print }
  ' "$hba_file" > "$tmp"
  cat "$tmp" > "$hba_file"
  rm -f "$tmp"
fi
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT pg_reload_conf();' >/dev/null
EOS

echo "PostgreSQL physical-backup replication access configured for role: $rep_user"
