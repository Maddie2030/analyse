#!/usr/bin/env bash
set -euo pipefail
umask 077

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-manhwa}"
DB_NAME="${POSTGRES_DB:-manhwa}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"
LOCAL_ROOT="${POSTGRES_BACKUP_LOCAL_ROOT:?POSTGRES_BACKUP_LOCAL_ROOT is required}"
STORE="${MREADER_LOCAL_RECOVERY_STORE:-/usr/local/bin/mreader-local-recovery-store}"

for tool in jq psql mktemp sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'ERROR: required catalog-sync tool is missing: %s\n' "$tool" >&2
    exit 1
  }
done
[[ -x "$STORE" ]] || {
  printf 'ERROR: local recovery-store helper is unavailable.\n' >&2
  exit 1
}

catalog="$($STORE catalog "$LOCAL_ROOT")"
scan_token="$(printf '%s-%s-%s' "$(date -u +%s%N)" "$$" "$RANDOM" | sha256sum | cut -c1-32)"
tsv="$(mktemp /tmp/mreader-recovery-catalog.XXXXXX.tsv)"
cleanup() { rm -f -- "$tsv"; }
trap cleanup EXIT INT TERM

jq -r '.recovery_points[] |
  [.recovery_id,.public_id,.kind,.purpose,.relative_directory,.artifact,.created_at,
   (.postgres_major|tostring),.mreader_version,(.size_bytes|tostring),.sha256] | @tsv' \
  <<<"$catalog" > "$tsv"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 >/dev/null <<SQL
BEGIN;
CREATE TEMP TABLE _local_recovery_scan (
  recovery_id TEXT,
  public_id TEXT,
  kind TEXT,
  purpose TEXT,
  relative_directory TEXT,
  artifact_name TEXT,
  created_at TIMESTAMPTZ,
  postgres_major INTEGER,
  mreader_version TEXT,
  size_bytes BIGINT,
  sha256 TEXT
) ON COMMIT DROP;
\copy _local_recovery_scan FROM '$tsv' WITH (FORMAT text, DELIMITER E'\t')

INSERT INTO database_recovery_points(
  recovery_id,public_id,kind,purpose,relative_directory,artifact_name,created_at,
  postgres_major,mreader_version,size_bytes,sha256,verified,available,last_seen_at,
  unavailable_at,scan_token
)
SELECT recovery_id,public_id,kind,purpose,relative_directory,artifact_name,created_at,
       postgres_major,mreader_version,size_bytes,sha256,TRUE,TRUE,now(),NULL,'$scan_token'
  FROM _local_recovery_scan
ON CONFLICT (recovery_id) DO UPDATE SET
  public_id=EXCLUDED.public_id,
  kind=EXCLUDED.kind,
  purpose=EXCLUDED.purpose,
  relative_directory=EXCLUDED.relative_directory,
  artifact_name=EXCLUDED.artifact_name,
  created_at=EXCLUDED.created_at,
  postgres_major=EXCLUDED.postgres_major,
  mreader_version=EXCLUDED.mreader_version,
  size_bytes=EXCLUDED.size_bytes,
  sha256=EXCLUDED.sha256,
  verified=TRUE,
  available=TRUE,
  last_seen_at=now(),
  unavailable_at=NULL,
  scan_token='$scan_token';

UPDATE database_recovery_points
   SET available=FALSE,
       unavailable_at=COALESCE(unavailable_at,now())
 WHERE scan_token <> '$scan_token'
   AND available=TRUE;
COMMIT;
SQL

printf '%s\n' "$(jq -r '.count' <<<"$catalog")"
