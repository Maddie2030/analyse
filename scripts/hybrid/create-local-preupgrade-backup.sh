#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT/.env}"
COMPOSE="$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml"

host_path_for_docker() {
  local value="$1"
  local host_os
  host_os="$(uname -s 2>/dev/null || true)"
  case "${MSYSTEM:-}:$host_os" in
    *MINGW*|*MSYS*|*CYGWIN*)
      if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$value"
      elif [[ "$value" =~ ^/([A-Za-z])(/.*)?$ ]]; then
        local drive rest
        drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')"
        rest="${BASH_REMATCH[2]:-}"
        printf '%s:%s\n' "$drive" "$rest"
      else
        printf '%s\n' "$value"
      fi
      ;;
    *) printf '%s\n' "$value" ;;
  esac
}

[[ -f "$ENV_FILE" ]] || {
  echo "ERROR: env file not found: $ENV_FILE" >&2
  exit 2
}
command -v docker >/dev/null 2>&1 || {
  echo "ERROR: docker is required for local pre-upgrade backup." >&2
  exit 2
}

protection_root="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")"
export MREADER_DB_PROTECTION_ROOT="$protection_root"
published_root="$protection_root/dumps/pre-upgrade"
staging_root="$protection_root/staging"
mkdir -p "$published_root" "$staging_root"
chmod 700 "$protection_root" "$protection_root/dumps" "$published_root" "$staging_root" 2>/dev/null || true

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
recovery_id="preupgrade-${stamp}-$$"
staging="$staging_root/$recovery_id"
final="$published_root/$recovery_id"
[[ ! -e "$final" ]] || {
  echo "ERROR: recovery bundle already exists: $recovery_id" >&2
  exit 4
}
mkdir "$staging"

container_dump="/tmp/${recovery_id}.dump"
container_globals="/tmp/${recovery_id}.globals.sql"
container_metadata="/tmp/${recovery_id}.metadata"
db_cid=""

cleanup() {
  if [[ -n "$db_cid" ]]; then
    MSYS_NO_PATHCONV=1 docker exec "$db_cid" rm -f "$container_dump" "$container_globals" "$container_metadata" >/dev/null 2>&1 || true
  fi
  if [[ -n "$staging" && -d "$staging" ]]; then
    case "$staging" in
      "$staging_root"/preupgrade-*) rm -rf -- "$staging" ;;
      *) echo "ERROR: refusing to clean unexpected staging path." >&2 ;;
    esac
  fi
}
trap cleanup EXIT INT TERM

db_cid="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE" ps -q db 2>/dev/null || true)"
[[ -n "$db_cid" ]] || {
  echo "ERROR: PostgreSQL container is not running; cannot create local pre-upgrade backup." >&2
  exit 3
}

if ! MSYS_NO_PATHCONV=1 docker exec "$db_cid" sh -ceu '
  dump="$1"; globals="$2"; metadata="$3"
  rm -f "$dump" "$globals" "$metadata"
  export PGPASSWORD="${POSTGRES_PASSWORD:-}"
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$dump"
  pg_dumpall -U "$POSTGRES_USER" --globals-only -f "$globals"
  pg_restore --list "$dump" >/dev/null
  server_version_num="$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SHOW server_version_num")"
  database_name="$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT current_database()")"
  dump_sha="$(sha256sum "$dump" | cut -d " " -f 1)"
  globals_sha="$(sha256sum "$globals" | cut -d " " -f 1)"
  test -s "$dump"
  test -s "$globals"
  printf "%s\n%s\n%s\n%s\n" "$server_version_num" "$database_name" "$dump_sha" "$globals_sha" > "$metadata"
' sh "$container_dump" "$container_globals" "$container_metadata"; then
  echo "ERROR: PostgreSQL capture failed; no recovery bundle was published." >&2
  exit 4
fi

if ! MSYS_NO_PATHCONV=1 docker cp "$db_cid:$container_dump" "$staging/database.dump" ||
   ! MSYS_NO_PATHCONV=1 docker cp "$db_cid:$container_globals" "$staging/globals.sql" ||
   ! MSYS_NO_PATHCONV=1 docker cp "$db_cid:$container_metadata" "$staging/metadata"; then
  echo "ERROR: PostgreSQL capture copy failed; no recovery bundle was published." >&2
  exit 4
fi

[[ -s "$staging/database.dump" && "$(head -c 5 "$staging/database.dump" 2>/dev/null || true)" == PGDMP ]] || {
  echo "ERROR: local database dump is not PostgreSQL custom format." >&2
  exit 4
}
[[ -s "$staging/globals.sql" ]] || {
  echo "ERROR: PostgreSQL globals capture is empty." >&2
  exit 4
}

server_version_num="$(sed -n '1p' "$staging/metadata" | tr -d '\r')"
database_name="$(sed -n '2p' "$staging/metadata" | tr -d '\r')"
source_dump_sha="$(sed -n '3p' "$staging/metadata" | tr -d '\r')"
source_globals_sha="$(sed -n '4p' "$staging/metadata" | tr -d '\r')"
[[ "$server_version_num" =~ ^[0-9]{5,6}$ ]] || {
  echo "ERROR: PostgreSQL server version metadata is invalid." >&2
  exit 4
}
[[ "$database_name" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || {
  echo "ERROR: PostgreSQL database identity is invalid for the recovery manifest." >&2
  exit 4
}
[[ "$source_dump_sha" =~ ^[a-f0-9]{64}$ && "$source_globals_sha" =~ ^[a-f0-9]{64}$ ]] || {
  echo "ERROR: PostgreSQL source checksum metadata is invalid." >&2
  exit 4
}
postgres_major="$((server_version_num / 10000))"

if command -v sha256sum >/dev/null 2>&1; then
  copied_dump_sha="$(sha256sum "$staging/database.dump" | awk '{print $1}')"
  copied_globals_sha="$(sha256sum "$staging/globals.sql" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  copied_dump_sha="$(shasum -a 256 "$staging/database.dump" | awk '{print $1}')"
  copied_globals_sha="$(shasum -a 256 "$staging/globals.sql" | awk '{print $1}')"
else
  echo "ERROR: sha256sum or shasum is required to verify the local recovery bundle." >&2
  exit 5
fi
[[ "$copied_dump_sha" == "$source_dump_sha" && "$copied_globals_sha" == "$source_globals_sha" ]] || {
  echo "ERROR: copied PostgreSQL files do not match their source checksum; no recovery bundle was published." >&2
  exit 4
}

mreader_version="unknown"
if [[ -f "$ROOT/VERSION" ]]; then
  mreader_version="$(tr -d '\r\n' < "$ROOT/VERSION")"
fi
[[ "$mreader_version" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || mreader_version="unknown"

rm -f "$staging/metadata"
printf '%s\n' \
  '{' \
  '  "schema_version": 1,' \
  "  \"recovery_id\": \"$recovery_id\"," \
  '  "type": "logical",' \
  '  "purpose": "pre-upgrade",' \
  '  "scope": "mreader_database_plus_globals",' \
  "  \"database\": \"$database_name\"," \
  "  \"postgres_major\": $postgres_major," \
  "  \"mreader_version\": \"$mreader_version\"," \
  "  \"created_at\": \"$created_at\"," \
  '  "verification": "verified",' \
  '  "files": ["database.dump", "globals.sql"],' \
  '  "checksums_file": "checksums.sha256"' \
  '}' > "$staging/manifest.json"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$staging" && sha256sum database.dump globals.sql manifest.json > checksums.sha256)
  (cd "$staging" && sha256sum -c checksums.sha256 >/dev/null)
elif command -v shasum >/dev/null 2>&1; then
  (cd "$staging" && shasum -a 256 database.dump globals.sql manifest.json > checksums.sha256)
  (cd "$staging" && shasum -a 256 -c checksums.sha256 >/dev/null)
else
  echo "ERROR: sha256sum or shasum is required to verify the local recovery bundle." >&2
  exit 5
fi

chmod 600 "$staging/database.dump" "$staging/globals.sql" "$staging/manifest.json" "$staging/checksums.sha256" 2>/dev/null || true

publish_staged_bundle() {
  if command -v jq >/dev/null 2>&1; then
    "$ROOT/scripts/backup/local-recovery-store.sh" publish-staged "$protection_root" "$staging"
    return
  fi

  local container_staging="/mreader-db-protection/staging/$recovery_id"
  local docker_env_file="$ENV_FILE"
  local docker_compose="$COMPOSE"
  if [[ "$docker_env_file" != /* && ! "$docker_env_file" =~ ^[A-Za-z]:[/\\] ]]; then
    docker_env_file="$ROOT/${docker_env_file#./}"
  fi
  docker_env_file="$(host_path_for_docker "$docker_env_file")"
  docker_compose="$(host_path_for_docker "$docker_compose")"
  echo "Host jq is unavailable; validating recovery bundle with the backup-agent runtime." >&2
  MSYS_NO_PATHCONV=1 docker compose --env-file "$docker_env_file" -f "$docker_compose" run --rm --build --no-deps \
    --entrypoint /usr/local/bin/mreader-local-recovery-store backup_agent \
    publish-staged /mreader-db-protection "$container_staging"
}

if ! published="$(publish_staged_bundle)"; then
  echo "ERROR: local recovery bundle failed canonical validation; no recovery bundle was published." >&2
  exit 4
fi
staging=""
printf '%s\n' "$published"
