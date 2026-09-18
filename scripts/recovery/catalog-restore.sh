#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/env/env-lib.sh"
source "$ROOT/scripts/docker/msys-paths.sh"
PYTHON_RUNTIME="$ROOT/scripts/hybrid/python-runtime.sh"

MODE=""
BACKUP_ID=""
ENV_FILE=".env"
NAS_CHECK_CONCURRENCY="${RECOVERY_NAS_CHECK_CONCURRENCY:-12}"
POSTGRES_IMAGE="${RECOVERY_POSTGRES_IMAGE:-postgres:16.10-alpine3.22}"
COMPOSE_FILE="$ROOT/deploy/compose/docker-compose.hybrid-stateful.yml"
RECOVERY_STORE_ENTRYPOINT="/usr/local/bin/mreader-local-recovery-store"

usage(){ cat <<'USAGE'
Usage:
  ./scripts/recovery/catalog-restore.sh --backup-id <bkp_...> --check
  ./scripts/recovery/catalog-restore.sh --backup-id <bkp_...> --import

The source must be a verified recovery point from the canonical host-local
recovery store. The recovery subsystem imports ONLY: series, chapters, pages,
genres, series_genres, tags and series_tags. NAS SeaweedFS is read-only
throughout. The import target must have an empty series/chapter/page catalog.
USAGE
}

while (($#)); do
  case "$1" in
    --backup-id) BACKUP_ID="${2:-}"; shift 2 ;;
    --check) MODE=check; shift ;;
    --import) MODE=import; shift ;;
    --env-file) ENV_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$BACKUP_ID" =~ ^bkp_[0-9a-f]{24}$ && -n "$MODE" ]] || { usage >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE is required for NAS/target configuration." >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required for read-only NAS validation." >&2; exit 2; }
command -v tar >/dev/null 2>&1 || { echo "ERROR: tar is required." >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker Engine is not ready." >&2; exit 2; }

env_ensure_healthy "$ENV_FILE" .env.example

recovery_store(){
  local docker_env_file docker_compose_file
  docker_env_file="$(mreader_docker_host_path "$ENV_FILE")" || return
  docker_compose_file="$(mreader_docker_host_path "$COMPOSE_FILE")" || return
  MSYS_NO_PATHCONV=1 docker compose \
    --env-file "$docker_env_file" -f "$docker_compose_file" \
    run --no-deps --rm --build --entrypoint "$RECOVERY_STORE_ENTRYPOINT" \
    backup_agent "$@"
}

MREADER_DB_PROTECTION_ROOT="$(bash "$ROOT/scripts/env/resolve-db-protection-root.sh" "$ENV_FILE")"
export MREADER_DB_PROTECTION_ROOT
[[ -d "$MREADER_DB_PROTECTION_ROOT" && ! -L "$MREADER_DB_PROTECTION_ROOT" ]] || {
  echo "ERROR: canonical database-protection root is unavailable or unsafe." >&2; exit 2;
}
DONOR="mreader-catalog-donor-$$"
HELPER="mreader-catalog-helper-$$"
DONOR_VOLUME="mreader_catalog_donor_$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/mreader-catalog-recovery.XXXXXX")"
EXPORT_DIR="$WORK/export"
SOURCE_REL="staging/catalog-recovery-${BACKUP_ID}-$$.source"
SOURCE="$MREADER_DB_PROTECTION_ROOT/$SOURCE_REL"
SOURCE_CONTAINER="/mreader-db-protection/$SOURCE_REL"
mkdir -p "$EXPORT_DIR" backups/recovery
cleanup(){
  docker rm -f "$DONOR" "$HELPER" >/dev/null 2>&1 || true
  docker volume rm -f "$DONOR_VOLUME" >/dev/null 2>&1 || true
  rm -f -- "$SOURCE" "$SOURCE.sha256"
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

SOURCE_ITEM="$(recovery_store copy-public-artifact /mreader-db-protection "$BACKUP_ID" "$SOURCE_CONTAINER")" || {
  echo "ERROR: backup id $BACKUP_ID did not resolve to a verified canonical recovery point." >&2; exit 3;
}
SOURCE_FIELDS_RAW="$("$PYTHON_RUNTIME" - "$SOURCE_ITEM" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print(payload.get("sha256") or "")
print(payload.get("kind") or "")
PY
)" || { echo "ERROR: canonical recovery source metadata is unreadable." >&2; exit 3; }
mapfile -t SOURCE_FIELDS <<<"$SOURCE_FIELDS_RAW"
SOURCE_SHA="${SOURCE_FIELDS[0]:-}"
SOURCE_KIND="${SOURCE_FIELDS[1]:-}"
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: canonical recovery source metadata has an invalid SHA-256." >&2; exit 3; }
SOURCE_TYPE=""
DONOR_USER=""
DONOR_DB=""
CURRENT_USER="$(env_get "$ENV_FILE" POSTGRES_USER)"; CURRENT_USER="${CURRENT_USER:-manhwa}"
CURRENT_DB="$(env_get "$ENV_FILE" POSTGRES_DB)"; CURRENT_DB="${CURRENT_DB:-manhwa}"

case "$SOURCE_KIND" in
  logical_dump)
    [[ "$(head -c 5 "$SOURCE" 2>/dev/null || true)" == PGDMP ]] || { echo "ERROR: verified logical recovery artifact is not PostgreSQL custom format." >&2; exit 3; }
    SOURCE_TYPE=logical-custom
    ;;
  physical_snapshot)
    tar -tf "$SOURCE" 2>/dev/null | grep -Eq '(^|/)base\.tar\.gz$' || { echo "ERROR: verified physical recovery artifact lacks base.tar.gz." >&2; exit 3; }
    SOURCE_TYPE=physical-snapshot
    ;;
  *) echo "ERROR: unsupported verified recovery source kind: $SOURCE_KIND" >&2; exit 3 ;;
esac

echo "==> Recovery source: $SOURCE_TYPE ($BACKUP_ID)"
echo "    SHA-256: $SOURCE_SHA"
docker volume create "$DONOR_VOLUME" >/dev/null

wait_ready(){
  local i
  for i in $(seq 1 90); do
    mreader_docker_no_pathconv exec "$DONOR" pg_isready >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "ERROR: isolated donor PostgreSQL did not become ready." >&2
  docker logs "$DONOR" >&2 || true
  return 1
}

if [[ "$SOURCE_TYPE" == logical-custom ]]; then
  mreader_docker_no_pathconv run -d --name "$DONOR" \
    -e POSTGRES_PASSWORD=mreader-recovery \
    -e POSTGRES_DB=manhwa \
    -v "$DONOR_VOLUME:/var/lib/postgresql/data" \
    "$POSTGRES_IMAGE" >/dev/null
  wait_ready
  mreader_docker_cp_to_container "$SOURCE" "$DONOR:/tmp/source.dump"
  mreader_docker_no_pathconv exec -e PGPASSWORD=mreader-recovery "$DONOR" \
    pg_restore -U postgres -d manhwa --no-owner --no-privileges --exit-on-error /tmp/source.dump >/dev/null
  DONOR_USER=postgres
  DONOR_DB=manhwa
else
  SNAP_DIR="$WORK/snapshot"
  mkdir -p "$SNAP_DIR"
  tar -xf "$SOURCE" -C "$SNAP_DIR"
  BASE_ARCHIVE="$(find "$SNAP_DIR" -type f -name base.tar.gz -print -quit)"
  WAL_ARCHIVE="$(find "$SNAP_DIR" -type f -name pg_wal.tar.gz -print -quit)"
  [[ -n "$BASE_ARCHIVE" && -n "$WAL_ARCHIVE" ]] || { echo "ERROR: physical snapshot lacks base.tar.gz or pg_wal.tar.gz." >&2; exit 3; }

  mreader_docker_no_pathconv create --name "$HELPER" -v "$DONOR_VOLUME:/var/lib/postgresql/data" "$POSTGRES_IMAGE" sh -c 'sleep 600' >/dev/null
  docker start "$HELPER" >/dev/null
  mreader_docker_cp_to_container "$BASE_ARCHIVE" "$HELPER:/tmp/base.tar.gz"
  mreader_docker_cp_to_container "$WAL_ARCHIVE" "$HELPER:/tmp/pg_wal.tar.gz"
  mreader_docker_no_pathconv exec "$HELPER" sh -ceu '
    find /var/lib/postgresql/data -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    tar -xzf /tmp/base.tar.gz -C /var/lib/postgresql/data
    mkdir -p /var/lib/postgresql/data/pg_wal
    tar -xzf /tmp/pg_wal.tar.gz -C /var/lib/postgresql/data/pg_wal
    rm -f /var/lib/postgresql/data/postmaster.pid
    chown -R postgres:postgres /var/lib/postgresql/data
    chmod 0700 /var/lib/postgresql/data
  '
  docker rm -f "$HELPER" >/dev/null
  mreader_docker_no_pathconv run -d --name "$DONOR" -v "$DONOR_VOLUME:/var/lib/postgresql/data" "$POSTGRES_IMAGE" postgres >/dev/null
  wait_ready

  for candidate in "$CURRENT_USER" manhwa postgres; do
    [[ -n "$candidate" ]] || continue
    if mreader_docker_no_pathconv exec -u postgres "$DONOR" psql -U "$candidate" -d postgres -Atqc 'SELECT 1' >/dev/null 2>&1; then DONOR_USER="$candidate"; break; fi
  done
  [[ -n "$DONOR_USER" ]] || { echo "ERROR: could not authenticate locally to recovered physical snapshot." >&2; exit 4; }
  for candidate in "$CURRENT_DB" manhwa; do
    if mreader_docker_no_pathconv exec -u postgres "$DONOR" psql -U "$DONOR_USER" -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname='${candidate//\'/\'\'}'" | grep -qx 1; then DONOR_DB="$candidate"; break; fi
  done
  [[ -n "$DONOR_DB" ]] || { echo "ERROR: recovered snapshot does not contain expected MReader database." >&2; exit 4; }
fi

donor_sql(){ mreader_docker_no_pathconv exec -u postgres "$DONOR" psql -U "$DONOR_USER" -d "$DONOR_DB" -v ON_ERROR_STOP=1 -Atqc "$1"; }
donor_psql(){ mreader_docker_no_pathconv exec -u postgres "$DONOR" psql -U "$DONOR_USER" -d "$DONOR_DB" -v ON_ERROR_STOP=1 "$@"; }

required=(
  'genres:id,name'
  'tags:id,name'
  'series:id,title,slug,description,cover_image_path,status,created_at,updated_at'
  'chapters:id,series_id,chapter_number,title,slug,status,page_count,created_at,updated_at'
  'pages:id,chapter_id,page_number,image_path,width,height,responsive_image_path,responsive_width,responsive_height,encoding_version,encoding_rows,encoding_columns,encoding_seed'
  'series_genres:series_id,genre_id'
  'series_tags:series_id,tag_id'
)
for spec in "${required[@]}"; do
  table="${spec%%:*}"; csv="${spec#*:}"
  IFS=',' read -r -a cols <<< "$csv"
  [[ "$(donor_sql "SELECT to_regclass('public.${table}') IS NOT NULL")" == t ]] || { echo "ERROR: donor is missing required table: $table" >&2; exit 5; }
  for col in "${cols[@]}"; do
    [[ "$(donor_sql "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='${table}' AND column_name='${col}')")" == t ]] || {
      echo "ERROR: donor table $table is missing required column $col; no compatible catalog adapter exists." >&2; exit 5;
    }
  done
done

bad_pages="$(donor_sql "SELECT count(*) FROM pages WHERE encoding_version <> 4 OR encoding_seed IS NULL OR length(encoding_seed)<16 OR encoding_rows NOT BETWEEN 1 AND 32 OR encoding_columns NOT BETWEEN 1 AND 32 OR image_path IS NULL OR btrim(image_path)='' ")"
[[ "$bad_pages" == 0 ]] || { echo "ERROR: donor contains $bad_pages page(s) that do not satisfy the current v4 protected-page contract." >&2; exit 5; }
orphans="$(donor_sql "SELECT (SELECT count(*) FROM chapters c LEFT JOIN series s ON s.id=c.series_id WHERE s.id IS NULL) + (SELECT count(*) FROM pages p LEFT JOIN chapters c ON c.id=p.chapter_id WHERE c.id IS NULL)")"
[[ "$orphans" == 0 ]] || { echo "ERROR: donor catalog contains $orphans orphan chapter/page row(s)." >&2; exit 5; }

mkdir_cmd='mkdir -p /tmp/catalog-recovery && rm -f /tmp/catalog-recovery/*.csv'
mreader_docker_no_pathconv exec "$DONOR" sh -c "$mkdir_cmd"
export_query(){ local name="$1" query="$2"; donor_psql -c "\\copy (${query}) TO '/tmp/catalog-recovery/${name}.csv' WITH (FORMAT csv, HEADER true)" >/dev/null; }
export_query genres 'SELECT id,name FROM genres ORDER BY id'
export_query tags 'SELECT id,name FROM tags ORDER BY id'
export_query series 'SELECT id,title,slug,description,cover_image_path,status,created_at,updated_at FROM series ORDER BY id'
export_query chapters 'SELECT id,series_id,chapter_number,title,slug,status,page_count,created_at,updated_at FROM chapters ORDER BY series_id,chapter_number,id'
export_query pages 'SELECT id,chapter_id,page_number,image_path,width,height,responsive_image_path,responsive_width,responsive_height,encoding_version,encoding_rows,encoding_columns,encoding_seed FROM pages ORDER BY chapter_id,page_number,id'
export_query series_genres 'SELECT series_id,genre_id FROM series_genres ORDER BY series_id,genre_id'
export_query series_tags 'SELECT series_id,tag_id FROM series_tags ORDER BY series_id,tag_id'
mreader_docker_cp_from_container "$DONOR:/tmp/catalog-recovery/." "$EXPORT_DIR/"

donor_sql 'SELECT DISTINCT image_path FROM pages WHERE image_path IS NOT NULL ORDER BY 1' > "$WORK/primary-paths.txt"
donor_sql 'SELECT DISTINCT responsive_image_path FROM pages WHERE responsive_image_path IS NOT NULL ORDER BY 1' > "$WORK/responsive-paths.txt"
donor_sql "SELECT DISTINCT cover_image_path FROM series WHERE cover_image_path IS NOT NULL AND btrim(cover_image_path)<>'' ORDER BY 1" > "$WORK/cover-paths.txt"

NAS_HOST="$(env_get "$ENV_FILE" NAS_SEAWEEDFS_HOST)"
NAS_PORT="$(env_get "$ENV_FILE" NAS_SEAWEEDFS_PORT)"; NAS_PORT="${NAS_PORT:-8888}"
[[ -n "$NAS_HOST" ]] || { echo "ERROR: NAS_SEAWEEDFS_HOST is required for recovery validation." >&2; exit 6; }
NAS_BASE="http://${NAS_HOST}:${NAS_PORT}"
if ! curl -fsS --connect-timeout 3 --max-time 8 "$NAS_BASE/" >/dev/null; then
  echo "ERROR: NAS SeaweedFS filer is not reachable at $NAS_BASE; recovery is read-only and will not import without object validation." >&2
  exit 6
fi

check_paths(){
  local source_file="$1" missing_file="$2"
  : > "$missing_file"
  [[ -s "$source_file" ]] || return 0
  export NAS_BASE
  xargs -r -d '\n' -n 1 -P "$NAS_CHECK_CONCURRENCY" sh -c '
    p="$1"; safe="${p// /%20}"
    curl -fsSI --connect-timeout 3 --max-time 12 --path-as-is "$NAS_BASE/$safe" >/dev/null 2>&1 ||
      curl -fsS --range 0-0 --connect-timeout 3 --max-time 12 --path-as-is -o /dev/null "$NAS_BASE/$safe" >/dev/null 2>&1 ||
      printf "%s\n" "$p"
  ' _ < "$source_file" > "$missing_file"
}
check_paths "$WORK/primary-paths.txt" "$WORK/missing-primary.txt"
check_paths "$WORK/responsive-paths.txt" "$WORK/missing-responsive.txt"
check_paths "$WORK/cover-paths.txt" "$WORK/missing-covers.txt"

count_lines(){ awk 'NF{n++} END{print n+0}' "$1"; }
SERIES_COUNT="$(donor_sql 'SELECT count(*) FROM series')"
CHAPTER_COUNT="$(donor_sql 'SELECT count(*) FROM chapters')"
PAGE_COUNT="$(donor_sql 'SELECT count(*) FROM pages')"
PRIMARY_MISSING="$(count_lines "$WORK/missing-primary.txt")"
RESPONSIVE_MISSING="$(count_lines "$WORK/missing-responsive.txt")"
COVER_MISSING="$(count_lines "$WORK/missing-covers.txt")"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$ROOT/backups/recovery/catalog-recovery-${STAMP}.txt"
cat > "$REPORT" <<REPORT
MReader catalog recovery audit
backup_public_id=$BACKUP_ID
source_sha256=$SOURCE_SHA
source_type=$SOURCE_TYPE
catalog_contract=catalog-v4-v1
series=$SERIES_COUNT
chapters=$CHAPTER_COUNT
pages=$PAGE_COUNT
invalid_v4_pages=$bad_pages
orphan_rows=$orphans
primary_nas_missing=$PRIMARY_MISSING
responsive_nas_missing=$RESPONSIVE_MISSING
cover_nas_missing=$COVER_MISSING
nas_mode=read-only
REPORT

MISSING_PREFIX="${REPORT%.txt}"
cp "$WORK/missing-primary.txt" "${MISSING_PREFIX}-missing-primary.txt"
cp "$WORK/missing-responsive.txt" "${MISSING_PREFIX}-missing-responsive.txt"
cp "$WORK/missing-covers.txt" "${MISSING_PREFIX}-missing-covers.txt"

echo "==> Catalog recovery audit"
cat "$REPORT"
if (( PRIMARY_MISSING > 0 )); then
  echo "ERROR: $PRIMARY_MISSING primary page object(s) are missing on NAS. Import is blocked. See ${MISSING_PREFIX}-missing-primary.txt." >&2
  exit 7
fi
if (( RESPONSIVE_MISSING > 0 || COVER_MISSING > 0 )); then
  echo "WARNING: optional responsive/cover objects are missing; primary protected pages are intact." >&2
fi

if [[ "$MODE" == check ]]; then
  echo "CHECK ONLY: donor and NAS were read; current PostgreSQL was not modified."
  echo "Recovery report: $REPORT"
  exit 0
fi

# Import only after donor + NAS validation is complete.
"$ROOT/scripts/hybrid/adopt-existing-stateful-volumes.sh" "$ENV_FILE"
docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml up -d db >/dev/null
for _ in $(seq 1 60); do
  db_cid="$(docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml ps -q db)"
  [[ -n "$db_cid" ]] && mreader_docker_no_pathconv exec "$db_cid" pg_isready -U "$CURRENT_USER" -d "$CURRENT_DB" >/dev/null 2>&1 && break
  sleep 2
done
[[ -n "${db_cid:-}" ]] || { echo "ERROR: current PostgreSQL container did not start." >&2; exit 8; }

docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml --profile migration run --rm migrate >/dev/null
current_series="$(mreader_docker_no_pathconv exec "$db_cid" sh -ceu 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM series"')"
[[ "$current_series" == 0 ]] || { echo "ERROR: current catalog contains $current_series series. Catalog recovery imports only into an empty target; no changes made." >&2; exit 8; }

SAFETY_LABEL="catalog-import-${STAMP}-$$"
docker compose --env-file "$ENV_FILE" -f deploy/compose/docker-compose.hybrid-stateful.yml run --rm backup_agent pre-restore "$SAFETY_LABEL" >/dev/null
SAFETY_CATALOG="$(recovery_store catalog /mreader-db-protection)" || {
  echo "ERROR: canonical pre-import safety recovery catalog could not be read." >&2; exit 8;
}
SAFETY_PUBLIC_ID="$("$PYTHON_RUNTIME" - "$SAFETY_CATALOG" "-$SAFETY_LABEL" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
suffix = sys.argv[2]
matches = [
    row for row in payload.get("recovery_points", [])
    if row.get("purpose") == "pre-restore" and str(row.get("recovery_id") or "").endswith(suffix)
]
if len(matches) != 1:
    raise SystemExit("catalog import safety recovery point did not resolve uniquely")
print(matches[0].get("public_id") or "")
PY
)" || {
  echo "ERROR: canonical pre-import safety recovery point could not be resolved." >&2; exit 8;
}
[[ "$SAFETY_PUBLIC_ID" =~ ^bkp_[0-9a-f]{24}$ ]] || { echo "ERROR: canonical pre-import safety recovery point has an invalid public id." >&2; exit 8; }
mreader_docker_no_pathconv exec "$db_cid" rm -rf /tmp/mreader-catalog-recovery >/dev/null 2>&1 || true
mreader_docker_no_pathconv exec "$db_cid" mkdir -p /tmp/mreader-catalog-recovery
mreader_docker_cp_to_container "$EXPORT_DIR/." "$db_cid:/tmp/mreader-catalog-recovery/"
mreader_docker_no_pathconv exec -i "$db_cid" sh -ceu 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$ROOT/scripts/recovery/catalog-import.sql"
mreader_docker_no_pathconv exec "$db_cid" rm -rf /tmp/mreader-catalog-recovery >/dev/null 2>&1 || true

final_counts="$(mreader_docker_no_pathconv exec "$db_cid" sh -ceu 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF"," -c "SELECT (SELECT count(*) FROM series),(SELECT count(*) FROM chapters),(SELECT count(*) FROM pages)"')"
[[ "$final_counts" == "$SERIES_COUNT,$CHAPTER_COUNT,$PAGE_COUNT" ]] || { echo "ERROR: post-import catalog counts do not match donor ($final_counts)." >&2; exit 9; }

cat >> "$REPORT" <<REPORT
imported=true
pre_import_backup_public_id=$SAFETY_PUBLIC_ID
final_counts=$final_counts
REPORT

echo "Catalog import completed transactionally."
echo "Pre-import safety recovery point: $SAFETY_PUBLIC_ID"
echo "Recovery report: $REPORT"
echo "NAS SeaweedFS was validated read-only and was not modified."
