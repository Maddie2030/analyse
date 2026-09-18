#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
ENV_FILE="${1:-.env}"
CONTRACT="${MREADER_POSTGRES_ROLE_CONTRACT:-$ROOT/contracts/ownership/postgres-roles.v1.json}"
COMPOSE_FILE="${MREADER_STATEFUL_COMPOSE_FILE:-$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml}"
# shellcheck source=../env/env-lib.sh
source "$ROOT/scripts/env/env-lib.sh"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"

env_ensure_healthy "$ENV_FILE" "$ROOT/.env.example"
"$ROOT/scripts/run-postgres-role-audit.sh" --contract "$CONTRACT"

POSTGRES_USER="$(env_get "$ENV_FILE" POSTGRES_USER)"
POSTGRES_DB="$(env_get "$ENV_FILE" POSTGRES_DB)"
POSTGRES_DB="${POSTGRES_DB:-manhwa}"
HYBRID_POSTGRES_PORT="$(env_get "$ENV_FILE" HYBRID_POSTGRES_PORT)"
HYBRID_POSTGRES_PORT="${HYBRID_POSTGRES_PORT:-5432}"
[[ -n "$POSTGRES_USER" ]] || { echo "ERROR: POSTGRES_USER is required for host-side role reconciliation." >&2; exit 2; }

mapfile -t role_rows < <("$PYTHON_RUNTIME" - "$CONTRACT" <<'PY'
import json, sys
contract=json.load(open(sys.argv[1], encoding='utf-8'))
for row in contract['workloads']:
    print(f"{row['role']}\t{row['dsn_env']}")
PY
)

for row in "${role_rows[@]}"; do
  IFS=$'\t' read -r role _dsn_env <<<"$row"
  role_upper="$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')"
  password_key="MREADER_DB_ROLE_PASSWORD_${role_upper}"
  dsn_key="MREADER_DB_DSN_${role_upper}"
  password="$(env_get "$ENV_FILE" "$password_key")"
  if [[ -z "$password" ]]; then
    password="$(openssl rand -hex 24)"
    env_set "$ENV_FILE" "$password_key" "$password"
  fi
  # Passwords are generated as lowercase hex, so no URL escaping is required.
  dsn="postgresql://${role}:${password}@host.docker.internal:${HYBRID_POSTGRES_PORT}/${POSTGRES_DB}"
  env_set "$ENV_FILE" "$dsn_key" "$dsn"
  export "$password_key=$password"
done

# Render secrets only into the psql stdin pipe. Do not log SQL or password values.
"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-postgres-role-sql.py" \
  --contract "$CONTRACT" \
  --database "$POSTGRES_DB" \
| docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
    psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"

"$PYTHON_RUNTIME" "$ROOT/scripts/hybrid/render-postgres-role-sql.py" \
  --contract "$CONTRACT" \
  --database "$POSTGRES_DB" \
  --mode verify \
| docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
    psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"

echo "PostgreSQL runtime roles reconciled and verified from the audited P09.3 contract."
