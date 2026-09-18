#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
ENV_FILE="${ENV_FILE:-.env}"
CANONICAL="${1:-mreader_pgdata}"
LEGACY="${2:-mreader-hybrid-stateful_pgdata}"
PROBE_IMAGE="${MREADER_VOLUME_PROBE_IMAGE:-postgres:16.10-alpine3.22}"

command -v docker >/dev/null 2>&1 || { echo 'ERROR: docker is required.' >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo 'ERROR: Docker Engine is not ready.' >&2; exit 2; }

volume_exists(){ docker volume inspect "$1" >/dev/null 2>&1; }

inspect_one(){
  local source="$1" clone ctr major image role db series_count chapter_count page_count seed_count in_use
  echo "==> Inspecting PostgreSQL volume: $source"
  if ! volume_exists "$source"; then
    echo "volume=$source"
    echo "exists=no"
    echo
    return 0
  fi

  major="$(docker run --rm --network none -v "$source:/probe:ro" "$PROBE_IMAGE" sh -ceu 'test -f /probe/PG_VERSION; cat /probe/PG_VERSION' 2>/dev/null || true)"
  if [[ -z "$major" ]]; then
    echo "volume=$source"
    echo "exists=yes"
    echo "pgdata_valid=no"
    echo
    return 0
  fi

  in_use="$(docker ps -a --filter "volume=$source" --format '{{.Names}}' | paste -sd, -)"
  clone="mreader-pginspect-${RANDOM}-$$"
  ctr="mreader-pginspect-${RANDOM}-$$"
  docker volume create "$clone" >/dev/null
  cleanup(){ docker rm -f "$ctr" >/dev/null 2>&1 || true; docker volume rm -f "$clone" >/dev/null 2>&1 || true; }
  trap cleanup RETURN

  # Safety rule: never start PostgreSQL against the original volume. Copy the
  # PGDATA into a temporary clone, query that clone, then destroy it.
  echo "Creating temporary clone for read-only catalog inspection..."
  docker run --rm --network none \
    -v "$source:/from:ro" -v "$clone:/to" \
    "$PROBE_IMAGE" sh -ceu 'cd /from; tar cf - . | tar xf - -C /to'

  case "$major" in
    16) image="${MREADER_PG16_INSPECT_IMAGE:-postgres:16.10-alpine3.22}" ;;
    17) image="${MREADER_PG17_INSPECT_IMAGE:-postgres:17-alpine}" ;;
    *)
      echo "volume=$source"
      echo "exists=yes"
      echo "pgdata_valid=yes"
      echo "pg_major=$major"
      echo "catalog_query=unsupported_postgres_major"
      echo
      return 0
      ;;
  esac

  docker run -d --name "$ctr" --network none \
    -v "$clone:/var/lib/postgresql/data" \
    "$image" -c listen_addresses='' >/dev/null

  for _ in $(seq 1 60); do
    if docker exec "$ctr" pg_isready -q >/dev/null 2>&1; then break; fi
    sleep 1
  done
  docker exec "$ctr" pg_isready -q >/dev/null 2>&1 || {
    echo "volume=$source"
    echo "exists=yes"
    echo "pgdata_valid=yes"
    echo "pg_major=$major"
    echo "catalog_query=postgres_start_failed"
    docker logs "$ctr" 2>&1 | tail -30 >&2 || true
    echo
    return 0
  }

  role=""
  for candidate in "${POSTGRES_USER:-}" "$( [[ -f "$ENV_FILE" ]] && env_get "$ENV_FILE" POSTGRES_USER || true )" mreader postgres; do
    [[ -n "$candidate" ]] || continue
    if docker exec "$ctr" psql -U "$candidate" -d postgres -Atqc 'select 1' >/dev/null 2>&1; then role="$candidate"; break; fi
  done
  [[ -n "$role" ]] || {
    echo "volume=$source"
    echo "exists=yes"
    echo "pgdata_valid=yes"
    echo "pg_major=$major"
    echo "catalog_query=no_local_superuser_candidate"
    echo
    return 0
  }

  db=""
  for candidate in "${POSTGRES_DB:-}" "$( [[ -f "$ENV_FILE" ]] && env_get "$ENV_FILE" POSTGRES_DB || true )" manhwa mreader postgres; do
    [[ -n "$candidate" ]] || continue
    if docker exec "$ctr" psql -U "$role" -d postgres -Atqc "select 1 from pg_database where datname='${candidate//\'/\'\'}'" 2>/dev/null | grep -qx 1; then db="$candidate"; break; fi
  done
  if [[ -z "$db" ]]; then
    db="$(docker exec "$ctr" psql -U "$role" -d postgres -Atqc "select datname from pg_database where not datistemplate and datname <> 'postgres' order by datname limit 1" | head -1)"
  fi
  [[ -n "$db" ]] || db=postgres

  count_table(){
    local table="$1"
    if [[ "$(docker exec "$ctr" psql -U "$role" -d "$db" -Atqc "select to_regclass('public.$table') is not null")" == t ]]; then
      docker exec "$ctr" psql -U "$role" -d "$db" -Atqc "select count(*) from public.$table"
    else
      echo -1
    fi
  }
  series_count="$(count_table series)"
  chapter_count="$(count_table chapters)"
  page_count="$(count_table pages)"
  if [[ "$page_count" =~ ^[0-9]+$ ]] && (( page_count >= 0 )) && [[ "$(docker exec "$ctr" psql -U "$role" -d "$db" -Atqc "select exists(select 1 from information_schema.columns where table_schema='public' and table_name='pages' and column_name='encoding_seed')")" == t ]]; then
    seed_count="$(docker exec "$ctr" psql -U "$role" -d "$db" -Atqc "select count(*) from public.pages where encoding_seed is not null and length(encoding_seed) >= 16")"
  else
    seed_count=-1
  fi

  echo "volume=$source"
  echo "exists=yes"
  echo "pgdata_valid=yes"
  echo "pg_major=$major"
  echo "mounted_by=${in_use:-none}"
  echo "database=$db"
  echo "series_count=$series_count"
  echo "chapter_count=$chapter_count"
  echo "page_count=$page_count"
  echo "valid_encoding_seed_count=$seed_count"
  if [[ "$series_count" =~ ^[0-9]+$ && "$chapter_count" =~ ^[0-9]+$ && "$page_count" =~ ^[0-9]+$ ]] && (( series_count > 0 || chapter_count > 0 || page_count > 0 )); then
    echo "catalog_state=contains_mreader_catalog"
  elif [[ "$series_count" == 0 && "$chapter_count" == 0 && "$page_count" == 0 ]]; then
    echo "catalog_state=empty_catalog"
  else
    echo "catalog_state=unknown"
  fi
  echo
  cleanup
  trap - RETURN
}

inspect_one "$CANONICAL"
inspect_one "$LEGACY"

cat <<'MSG'
Selection rule (upgrade continuity):
- A populated legacy `mreader-hybrid-stateful_pgdata` volume is preferred by default.
- If inspection proves legacy is empty while canonical contains the MReader catalog, canonical is selected.
- Set MREADER_PREFER_LEGACY_STATEFUL_VOLUMES=false only when you deliberately want a configured canonical volume to win.
- If neither contains catalog data, restore catalog metadata from the supplied dump/snapshot instead of overwriting NAS media.

Preferred upgrade example:
  HYBRID_PGDATA_VOLUME_NAME=mreader-hybrid-stateful_pgdata
MSG
