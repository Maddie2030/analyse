#!/usr/bin/env bash
set -euo pipefail

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-manhwa}"
DB_NAME="${POSTGRES_DB:-manhwa}"
DB_PASSWORD="${POSTGRES_PASSWORD:-}"
REPL_USER="${POSTGRES_REPLICATION_USER:-mreader_backup}"
REPL_PASSWORD="${POSTGRES_REPLICATION_PASSWORD:-${DB_PASSWORD}}"
export PGPASSWORD="$DB_PASSWORD"
SPOOL="${POSTGRES_BACKUP_SPOOL:-/spool}"
LOCAL_ROOT="${POSTGRES_BACKUP_LOCAL_ROOT:-/mreader-db-protection}"
RESTORE_CONTROL_DIR="$LOCAL_ROOT/control"
RESTORE_CONTROL_FILE="$RESTORE_CONTROL_DIR/restore-control.json"
CATALOG_SYNC_SECONDS="${POSTGRES_BACKUP_CATALOG_SYNC_SECONDS:-300}"
LOCAL_STORE="${MREADER_LOCAL_RECOVERY_STORE:-/usr/local/bin/mreader-local-recovery-store}"
SYNC_CATALOG="${MREADER_SYNC_RECOVERY_CATALOG:-/usr/local/bin/mreader-sync-recovery-catalog}"
RECOVERY_BRIDGE_BIN="${MREADER_RECOVERY_BRIDGE_BIN:-/usr/local/bin/mreader-recovery-bridge}"
RECOVERY_BRIDGE_TOKEN="${RECOVERY_BRIDGE_TOKEN:-}"
RECOVERY_BRIDGE_LOCAL_URL="${RECOVERY_BRIDGE_LOCAL_URL:-http://127.0.0.1:8082}"
RECOVERY_BRIDGE_PID=""
DAILY_KEEP_DAYS="${POSTGRES_BACKUP_DAILY_RETENTION_DAYS:-4}"
SNAPSHOT_KEEP_DAYS="${POSTGRES_BACKUP_SNAPSHOT_RETENTION_DAYS:-2}"
SNAPSHOT_DAYS="${POSTGRES_BACKUP_SNAPSHOT_EVERY_DAYS:-2}"
SNAPSHOT_MAX_RATE="${POSTGRES_BACKUP_SNAPSHOT_MAX_RATE:-32M}"
SNAPSHOT_STAGE_PORT="${POSTGRES_BACKUP_SNAPSHOT_STAGE_PORT:-55432}"
VERIFY_TIME="${POSTGRES_BACKUP_VERIFY_TIME:-21:00}"
AUTO_WINDOW_START="${POSTGRES_BACKUP_AUTO_WINDOW_START:-20:00}"
AUTO_WINDOW_END="${POSTGRES_BACKUP_AUTO_WINDOW_END:-22:00}"
MREADER_VERSION="${MREADER_VERSION:-unknown}"
TZ="${TZ:-Asia/Kolkata}"; export TZ
mkdir -p "$SPOOL" "$SPOOL/state"
[[ -f "$SPOOL/state/scheduler-started-epoch" ]] || date +%s > "$SPOOL/state/scheduler-started-epoch"

log(){ printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
fail(){ log "ERROR: $*" >&2; exit 1; }
storage_contract_fail(){ log "ERROR: $*" >&2; exit 42; }

ensure_restore_control_dir(){
  [[ "$LOCAL_ROOT" == /* && -d "$LOCAL_ROOT" && ! -L "$LOCAL_ROOT" ]] \
    || fail "restore-control root must be a real absolute directory: $LOCAL_ROOT"
  if [[ -e "$RESTORE_CONTROL_DIR" || -L "$RESTORE_CONTROL_DIR" ]]; then
    [[ -d "$RESTORE_CONTROL_DIR" && ! -L "$RESTORE_CONTROL_DIR" ]] \
      || fail "restore-control directory must be a real directory: $RESTORE_CONTROL_DIR"
  else
    mkdir "$RESTORE_CONTROL_DIR" || fail "could not create restore-control directory"
  fi
  chmod 700 "$RESTORE_CONTROL_DIR" 2>/dev/null || true
}

write_restore_control(){
  local installation_id="$1" fingerprint="$2" generation="$3" tmp
  [[ "$installation_id" =~ ^[0-9a-f]{32}$ ]] || fail "invalid restore-control installation id"
  [[ "$fingerprint" =~ ^inst_[0-9a-f]{16}$ ]] || fail "invalid restore-control installation fingerprint"
  [[ "$generation" =~ ^[0-9]+$ && "$generation" -ge 1 ]] || fail "invalid restore generation"
  ensure_restore_control_dir
  tmp="$(mktemp "$RESTORE_CONTROL_DIR/.restore-control.XXXXXX")" || fail "could not allocate restore-control temp file"
  jq -n \
    --arg installation_id "$installation_id" \
    --arg installation_fingerprint "$fingerprint" \
    --argjson restore_generation "$generation" \
    '{schema_version:1,installation_id:$installation_id,installation_fingerprint:$installation_fingerprint,restore_generation:$restore_generation,updated_at_utc:(now|todate)}' \
    > "$tmp" || { rm -f -- "$tmp"; fail "could not serialize restore control"; }
  chmod 600 "$tmp" 2>/dev/null || true
  mv -f -- "$tmp" "$RESTORE_CONTROL_FILE" || { rm -f -- "$tmp"; fail "could not persist restore control"; }
  sync "$RESTORE_CONTROL_FILE" 2>/dev/null || true
  sync "$RESTORE_CONTROL_DIR" 2>/dev/null || true
}

ensure_restore_control(){
  local installation_id fingerprint generation
  ensure_restore_control_dir
  if [[ -e "$RESTORE_CONTROL_FILE" || -L "$RESTORE_CONTROL_FILE" ]]; then
    [[ -f "$RESTORE_CONTROL_FILE" && ! -L "$RESTORE_CONTROL_FILE" ]] \
      || fail "restore-control file must be a regular file: $RESTORE_CONTROL_FILE"
    jq -e '
      .schema_version == 1 and
      (.installation_id | type == "string" and test("^[0-9a-f]{32}$")) and
      (.installation_fingerprint | type == "string" and test("^inst_[0-9a-f]{16}$")) and
      (.restore_generation | type == "number" and . >= 1 and floor == .)
    ' "$RESTORE_CONTROL_FILE" >/dev/null || fail "restore-control file is malformed"
    return 0
  fi
  installation_id="$(printf '%s' "$(date +%s%N)-$$-$RANDOM-$RANDOM" | sha256sum | cut -c1-32)"
  fingerprint="inst_$(printf '%s' "$installation_id" | sha256sum | cut -c1-16)"
  generation=1
  write_restore_control "$installation_id" "$fingerprint" "$generation"
}

restore_control_snapshot(){
  ensure_restore_control
  jq -c '{installation_fingerprint,restore_generation}' "$RESTORE_CONTROL_FILE"
}

initialize_restore_state(){
  local control installation_fingerprint restore_generation
  control="$(restore_control_snapshot)" || return 1
  installation_fingerprint="$(jq -r '.installation_fingerprint' <<<"$control")"
  restore_generation="$(jq -r '.restore_generation' <<<"$control")"
  [[ "$installation_fingerprint" =~ ^inst_[0-9a-f]{16}$ ]] || fail "invalid restore-control installation fingerprint"
  [[ "$restore_generation" =~ ^[0-9]+$ && "$restore_generation" -ge 1 ]] || fail "invalid restore-control generation"

  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -v installation_fingerprint="$installation_fingerprint" \
    -v restore_generation="$restore_generation" >/dev/null <<'SQL'
\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE restore_init_expected(
    installation_fingerprint text,
    restore_generation bigint
) ON COMMIT DROP;
INSERT INTO restore_init_expected
VALUES (:'installation_fingerprint', :restore_generation::bigint);
DO $restore_init$
DECLARE
  mirror_rows integer;
  current_fingerprint text;
  current_generation bigint;
  expected record;
BEGIN
  SELECT * INTO STRICT expected FROM restore_init_expected;
  SELECT count(*) INTO mirror_rows FROM database_restore_state WHERE singleton = TRUE;
  IF mirror_rows <> 1 THEN
    RAISE EXCEPTION 'restore generation mirror row count mismatch';
  END IF;
  SELECT installation_fingerprint, restore_generation
    INTO current_fingerprint, current_generation
    FROM database_restore_state
    WHERE singleton = TRUE;
  IF current_fingerprint = '' AND current_generation = 0 THEN
    UPDATE database_restore_state
       SET installation_fingerprint = expected.installation_fingerprint,
           restore_generation = expected.restore_generation,
           updated_at = now()
     WHERE singleton = TRUE
       AND installation_fingerprint = ''
       AND restore_generation = 0;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'restore generation mirror initialization lost race';
    END IF;
  ELSIF current_fingerprint = expected.installation_fingerprint
    AND current_generation = expected.restore_generation THEN
    NULL;
  ELSE
    RAISE EXCEPTION 'restore generation mirror mismatch';
  END IF;
END
$restore_init$;
COMMIT;
SQL
  printf '%s\n' "$control"
}

advance_restore_generation(){
  local expected_fingerprint="$1" expected_generation="$2" installation_id current_fingerprint current_generation next_generation
  ensure_restore_control
  installation_id="$(jq -r '.installation_id' "$RESTORE_CONTROL_FILE")"
  current_fingerprint="$(jq -r '.installation_fingerprint' "$RESTORE_CONTROL_FILE")"
  current_generation="$(jq -r '.restore_generation' "$RESTORE_CONTROL_FILE")"
  [[ "$current_fingerprint" == "$expected_fingerprint" ]] || fail "restore installation fingerprint changed before generation commit"
  [[ "$current_generation" == "$expected_generation" ]] || fail "restore generation changed before generation commit"
  next_generation=$((current_generation + 1))
  write_restore_control "$installation_id" "$current_fingerprint" "$next_generation"
  restore_control_snapshot
}

sync_database_restore_state(){
  local installation_fingerprint="$1" restore_generation="$2" operation_id="$3" source_public_id="$4"
  [[ "$installation_fingerprint" =~ ^inst_[0-9a-f]{16}$ ]] || return 1
  [[ "$restore_generation" =~ ^[0-9]+$ && "$restore_generation" -ge 1 ]] || return 1
  [[ "$operation_id" =~ ^[0-9a-fA-F-]{36}$ ]] || return 1
  [[ "$source_public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || return 1
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -v installation_fingerprint="$installation_fingerprint" \
    -v restore_generation="$restore_generation" \
    -v operation_id="$operation_id" \
    -v source_public_id="$source_public_id" >/dev/null <<'SQL'
INSERT INTO database_restore_state(
    singleton, installation_fingerprint, restore_generation,
    last_restore_operation_id, last_restore_source_public_id, updated_at
)
VALUES (
    TRUE, :'installation_fingerprint', :restore_generation::bigint,
    :'operation_id'::uuid, :'source_public_id', now()
)
ON CONFLICT (singleton) DO UPDATE
SET installation_fingerprint = EXCLUDED.installation_fingerprint,
    restore_generation = EXCLUDED.restore_generation,
    last_restore_operation_id = EXCLUDED.last_restore_operation_id,
    last_restore_source_public_id = EXCLUDED.last_restore_source_public_id,
    updated_at = now();
SQL
}
write_restore_cutover_journal(){
  local file="$1" payload="$2" tmp basename
  ensure_restore_control_dir
  basename="${file##*/}"
  [[ "$file" == "$RESTORE_CONTROL_DIR/$basename" && "$basename" =~ ^restore-cutover-[0-9a-fA-F-]{36}\.json$ ]] \
    || fail "unsafe restore cutover journal path: $file"
  [[ ! -L "$file" ]] || fail "restore cutover journal must not be a symlink: $file"
  payload="$(printf '%s' "$payload" | jq -ce 'if type == "object" and .schema_version == 2 then . else error("invalid restore cutover journal") end')" \
    || fail "invalid restore cutover journal payload"
  tmp="$(mktemp "$RESTORE_CONTROL_DIR/.restore-cutover.XXXXXX")" || fail "could not allocate restore cutover journal temp file"
  printf '%s\n' "$payload" > "$tmp" || { rm -f -- "$tmp"; fail "could not write restore cutover journal"; }
  chmod 600 "$tmp" 2>/dev/null || true
  mv -f -- "$tmp" "$file" || { rm -f -- "$tmp"; fail "could not persist restore cutover journal"; }
  sync "$file" 2>/dev/null || true
  sync "$RESTORE_CONTROL_DIR" 2>/dev/null || true
}

update_restore_cutover_phase(){
  local file="$1" phase="$2" payload
  payload="$(jq -c --arg phase "$phase" '.phase=$phase | .updated_at_utc=(now|todate)' "$file")" \
    || fail "could not update restore cutover journal phase"
  write_restore_cutover_journal "$file" "$payload"
}
sync_local_catalog_if_due(){
  local marker="$SPOOL/state/last-local-catalog-sync-epoch" last now
  [[ "$CATALOG_SYNC_SECONDS" =~ ^[0-9]+$ ]] || return 1
  last="$(cat "$marker" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  (( now - last >= CATALOG_SYNC_SECONDS )) || return 0
  [[ -x "$SYNC_CATALOG" ]] || return 1
  if POSTGRES_BACKUP_LOCAL_ROOT="$LOCAL_ROOT" MREADER_LOCAL_RECOVERY_STORE="$LOCAL_STORE" "$SYNC_CATALOG" >/dev/null; then
    printf '%s\n' "$now" > "$marker"
    return 0
  fi
  return 1
}
valid_hhmm(){ [[ "$1" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; }
clock_minutes(){
  local value="$1" h m
  valid_hhmm "$value" || fail "invalid HH:MM value: $value"
  IFS=: read -r h m <<<"$value"
  printf '%d\n' "$((10#$h * 60 + 10#$m))"
}
auto_window_open(){
  local now start end
  now="${POSTGRES_BACKUP_TEST_NOW_HHMM:-$(date '+%H:%M')}"
  start="$(clock_minutes "$AUTO_WINDOW_START")"
  end="$(clock_minutes "$AUTO_WINDOW_END")"
  now="$(clock_minutes "$now")"
  (( start < end )) || fail "POSTGRES_BACKUP_AUTO_WINDOW_START must be earlier than POSTGRES_BACKUP_AUTO_WINDOW_END"
  (( now >= start && now < end ))
}
attempted_today(){
  local marker="$1" today
  today="$(date '+%Y-%m-%d')"
  [[ "$(cat "$marker" 2>/dev/null || true)" == "$today" ]]
}
mark_attempt_today(){
  local marker="$1"
  date '+%Y-%m-%d' > "$marker"
}
sanitize_component(){
  printf '%s' "$1" | sed -E 's/[^A-Za-z0-9._-]+/-/g; s/^-+//; s/-+$//'
}
backup_identity(){
  # Human-readable local timestamp is primary. A short random id prevents
  # collisions when manual/pre-upgrade backups occur in the same second.
  local type="$1" label="${2:-}" local_stamp zone version db uid suffix
  local_stamp="$(date '+%Y-%m-%d_%H-%M-%S')"
  zone="$(date '+%Z')"; [[ -n "$zone" ]] || zone="$(date '+%z')"
  version="$(sanitize_component "$MREADER_VERSION")"
  db="$(sanitize_component "$DB_NAME")"
  uid="$(printf '%s-%s-%s-%s-%s' "$type" "$label" "$(date +%s%N)" "$$" "$RANDOM" | sha256sum | cut -c1-8)"
  suffix=""; [[ -z "$label" ]] || suffix="-$(sanitize_component "$label")"
  printf 'mreader-%s-%s-%s_%s-%s-%s%s' "$(sanitize_component "$type")" "$db" "$local_stamp" "$(sanitize_component "$zone")" "$version" "$uid" "$suffix"
}
require_tools(){
  local tool
  for tool in pg_isready psql pg_dump pg_dumpall pg_restore pg_basebackup pg_ctl postgres createdb dropdb jq sha256sum tar stat date awk sed grep find mktemp su-exec; do
    command -v "$tool" >/dev/null 2>&1 || fail "required backup tool is missing: $tool"
  done
}
wait_db(){
  local i
  for i in $(seq 1 60); do
    pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && return 0
    sleep 2
  done
  fail "PostgreSQL is not ready at ${DB_HOST}:${DB_PORT}/${DB_NAME}"
}
local_storage_ready_quiet(){
  local probe="$LOCAL_ROOT/staging/.write-test-$$"
  [[ "$LOCAL_ROOT" == /* && -d "$LOCAL_ROOT" && ! -L "$LOCAL_ROOT" ]] || return 1
  [[ -x "$LOCAL_STORE" ]] || return 1
  mkdir -p "$LOCAL_ROOT/staging" || return 1
  [[ ! -L "$LOCAL_ROOT/staging" ]] || return 1
  : > "$probe" || return 1
  rm -f -- "$probe"
  "$LOCAL_STORE" catalog "$LOCAL_ROOT" >/dev/null 2>&1
}

recovery_bridge_health_quiet(){
  [[ -n "$RECOVERY_BRIDGE_TOKEN" ]] || return 1
  "$RECOVERY_BRIDGE_BIN" healthcheck >/dev/null 2>&1
}

start_recovery_bridge(){
  [[ -x "$RECOVERY_BRIDGE_BIN" ]] || fail "private recovery bridge binary is unavailable: $RECOVERY_BRIDGE_BIN"
  [[ -n "$RECOVERY_BRIDGE_TOKEN" ]] || fail "RECOVERY_BRIDGE_TOKEN is empty"
  "$RECOVERY_BRIDGE_BIN" &
  RECOVERY_BRIDGE_PID=$!
  local attempt
  for attempt in $(seq 1 20); do
    recovery_bridge_health_quiet && return 0
    kill -0 "$RECOVERY_BRIDGE_PID" >/dev/null 2>&1 || fail "private recovery bridge exited during startup"
    sleep 0.25
  done
  fail "private recovery bridge did not become ready"
}

stop_recovery_bridge(){
  [[ -n "$RECOVERY_BRIDGE_PID" ]] || return 0
  kill "$RECOVERY_BRIDGE_PID" >/dev/null 2>&1 || true
  wait "$RECOVERY_BRIDGE_PID" >/dev/null 2>&1 || true
  RECOVERY_BRIDGE_PID=""
}

replication_ready_quiet(){
  local can_replicate
  [[ -n "$REPL_USER" && -n "$REPL_PASSWORD" && "$REPL_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 1
  can_replicate="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Atc "select case when coalesce((select rolreplication or rolsuper from pg_roles where rolname='${REPL_USER//\'/\'\'}'),false) then 'yes' else 'no' end" 2>/dev/null || echo no)"
  [[ "$can_replicate" == "yes" ]]
}

runtime_publish(){
  local local_ready=false replication=false logical_backup=false physical_snapshot=false restore_drill=false restore=false status=degraded runtime_error=''
  local control_json='{}' installation_fingerprint='' restore_generation=0
  if local_storage_ready_quiet; then
    local_ready=true
    logical_backup=true
    restore_drill=true
    if control_json="$(restore_control_snapshot 2>/dev/null)"; then
      installation_fingerprint="$(jq -r '.installation_fingerprint' <<<"$control_json")"
      restore_generation="$(jq -r '.restore_generation' <<<"$control_json")"
      restore=true
    else
      runtime_error='host-local restore control unavailable'
    fi
  else
    runtime_error='host-local recovery storage unavailable'
  fi
  if replication_ready_quiet; then replication=true; fi
  if [[ "$local_ready" == "true" && "$replication" == "true" ]]; then physical_snapshot=true; fi
  if [[ "$logical_backup" == "true" && "$physical_snapshot" == "true" && "$restore_drill" == "true" && "$restore" == "true" ]]; then status=ready; fi
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -q -v ON_ERROR_STOP=1 \
    -v status="$status" -v local_ready="$local_ready" -v replication="$replication" \
    -v logical_backup="$logical_backup" -v physical_snapshot="$physical_snapshot" \
    -v restore_drill="$restore_drill" -v restore="$restore" -v runtime_error="$runtime_error" \
    -v installation_fingerprint="$installation_fingerprint" -v restore_generation="$restore_generation" >/dev/null <<'SQL' || return 1
INSERT INTO database_protection_runtime(component,status,capabilities,last_heartbeat_at,last_error,updated_at)
VALUES (
  'backup-agent', :'status',
  jsonb_build_object(
    'local_storage_ready', :'local_ready'::boolean,
    'replication_ready', :'replication'::boolean,
    'logical_backup', :'logical_backup'::boolean,
    'physical_snapshot', :'physical_snapshot'::boolean,
    'restore_drill', :'restore_drill'::boolean,
    'restore', :'restore'::boolean,
    'installation_fingerprint', NULLIF(:'installation_fingerprint',''),
    'restore_generation', :'restore_generation'::bigint
  ),
  now(), NULLIF(:'runtime_error',''), now()
)
ON CONFLICT (component) DO UPDATE
   SET status=EXCLUDED.status, capabilities=EXCLUDED.capabilities,
       last_heartbeat_at=EXCLUDED.last_heartbeat_at, last_error=EXCLUDED.last_error,
       updated_at=EXCLUDED.updated_at;
SQL
}

daemon_preflight(){
  require_tools
  [[ -n "$PGPASSWORD" ]] || fail "POSTGRES_PASSWORD is empty"
  [[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "POSTGRES_DB must be a simple PostgreSQL identifier for protected restore operations"
  mkdir -p "$SPOOL/state"
  touch "$SPOOL/state/.write-test" || fail "backup spool is not writable: $SPOOL"
  rm -f "$SPOOL/state/.write-test"
  wait_db
  runtime_publish || log "WARNING: could not publish initial database-protection runtime heartbeat"
}

self_test(){
  require_tools
  [[ -n "$PGPASSWORD" ]] || fail "POSTGRES_PASSWORD is empty"
  [[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "POSTGRES_DB must be a simple PostgreSQL identifier for protected restore operations"
  mkdir -p "$SPOOL/state"
  touch "$SPOOL/state/.write-test" || fail "backup spool is not writable: $SPOOL"
  rm -f "$SPOOL/state/.write-test"
  wait_db
  local_storage_ready_quiet || storage_contract_fail "host-local recovery root is not writable or its catalog cannot be verified"
  [[ -n "$REPL_USER" ]] || fail "POSTGRES_REPLICATION_USER is empty"
  [[ "$REPL_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "invalid POSTGRES_REPLICATION_USER: $REPL_USER"
  [[ -n "$REPL_PASSWORD" ]] || fail "POSTGRES_REPLICATION_PASSWORD is empty"
  local can_replicate repl_probe
  can_replicate="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Atc "select case when coalesce((select rolreplication or rolsuper from pg_roles where rolname='${REPL_USER//\'/\'\'}'),false) then 'yes' else 'no' end" 2>/dev/null || echo no)"
  [[ "$can_replicate" == "yes" ]] || fail "configured snapshot role '$REPL_USER' is missing or lacks REPLICATION privilege"
  # A normal SQL login does not exercise pg_hba.conf's special `replication`
  # database selector. Probe the actual physical replication protocol so the
  # exact pg_basebackup HBA failure is detected during bootstrap/self-test.
  repl_probe="$(PGPASSWORD="$REPL_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
    -d "host=$DB_HOST port=$DB_PORT user=$REPL_USER dbname=postgres replication=true" \
    -Atc 'IDENTIFY_SYSTEM' 2>/dev/null || true)"
  [[ -n "$repl_probe" ]] || fail "physical replication protocol probe failed for '$REPL_USER' (check pg_hba.conf/credentials)"
  date +%s > "$SPOOL/state/last-self-test-success-epoch"
  log "Backup self-test passed: db=${DB_HOST}:${DB_PORT}/${DB_NAME} storage=host-local"
}
make_local_bundle_manifest(){
  local recovery_id="$1" type="$2" purpose="$3" created_at="$4" out="$5"
  local server_version_num postgres_major version
  server_version_num="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Atc 'show server_version_num')"
  [[ "$server_version_num" =~ ^[0-9]{5,6}$ ]] || fail "PostgreSQL server version metadata is invalid"
  postgres_major="$((server_version_num / 10000))"
  version="$(sanitize_component "$MREADER_VERSION")"
  [[ -n "$version" ]] || version=unknown
  jq -n \
    --arg recovery_id "$recovery_id" --arg type "$type" --arg purpose "$purpose" \
    --arg database "$DB_NAME" --arg mreader_version "$version" --arg created_at "$created_at" \
    --argjson postgres_major "$postgres_major" \
    '{schema_version:1,recovery_id:$recovery_id,type:$type,purpose:$purpose,
      scope:(if $type == "logical" then "mreader_database_plus_globals" else "postgres_cluster" end),
      database:$database,postgres_major:$postgres_major,mreader_version:$mreader_version,
      created_at:$created_at,verification:"verified",
      files:(if $type == "logical" then ["database.dump","globals.sql"] else ["snapshot.tar"] end),
      checksums_file:"checksums.sha256"}' > "$out"
}
build_retention_pin_file(){
  local pin_file active_tmp marker filename source_recovery_id safety_recovery_id
  pin_file="$(mktemp "$SPOOL/state/retention-pins.XXXXXX")" || return 1
  active_tmp="$(mktemp "$SPOOL/state/retention-active.XXXXXX")" || { rm -f -- "$pin_file"; return 1; }
  if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At -v ON_ERROR_STOP=1 \
      -c "SELECT backup_filename FROM database_operations WHERE operation_type IN ('restore','restore_drill') AND status IN ('queued','running') AND backup_filename IS NOT NULL;" \
      </dev/null >"$active_tmp" 2>/dev/null; then
    rm -f -- "$pin_file" "$active_tmp"
    return 1
  fi
  while IFS= read -r filename; do
    [[ "$filename" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || continue
    printf '%s\n' "$filename" >> "$pin_file"
  done < "$active_tmp"
  rm -f -- "$active_tmp"
  shopt -s nullglob
  for marker in "$RESTORE_CONTROL_DIR"/restore-cutover-*.json; do
    source_recovery_id="$(jq -r '.source_recovery_id // empty' "$marker" 2>/dev/null || true)"
    safety_recovery_id="$(jq -r '.safety_recovery_id // empty' "$marker" 2>/dev/null || true)"
    for filename in "$source_recovery_id" "$safety_recovery_id"; do
      [[ "$filename" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || continue
      printf '%s\n' "$filename" >> "$pin_file"
    done
  done
  # Compatibility: pre-P08.8 cutover markers used only .filename under the spool.
  for marker in "$SPOOL"/state/restore-cutover-*.json; do
    filename="$(jq -r '.filename // empty' "$marker" 2>/dev/null || true)"
    [[ "$filename" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || continue
    printf '%s\n' "$filename" >> "$pin_file"
  done
  shopt -u nullglob
  sort -u -o "$pin_file" "$pin_file"
  printf '%s\n' "$pin_file"
}
prune_local_recovery_store(){
  local pin_file
  pin_file="$(build_retention_pin_file)" || return 1
  if ! "$LOCAL_STORE" prune "$LOCAL_ROOT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DAILY_KEEP_DAYS" "$SNAPSHOT_KEEP_DAYS" "$pin_file"; then
    rm -f -- "$pin_file"
    return 1
  fi
  rm -f -- "$pin_file"
}
finish_local_logical_bundle(){
  local purpose="$1" recovery_id="$2" dump="$3" globals="$4" created_at="$5"
  local stage="$LOCAL_ROOT/staging/$recovery_id" published published_item latest_category public_id
  [[ -x "$LOCAL_STORE" ]] || fail "local recovery-store helper is unavailable"
  mkdir -p "$LOCAL_ROOT/staging"
  [[ ! -e "$stage" && ! -L "$stage" ]] || fail "local recovery staging bundle already exists: $recovery_id"
  mkdir "$stage"
  if ! cp -- "$dump" "$stage/database.dump" || ! cp -- "$globals" "$stage/globals.sql"; then
    rm -rf -- "$stage"
    fail "could not stage local PostgreSQL recovery bundle"
  fi
  make_local_bundle_manifest "$recovery_id" logical "$purpose" "$created_at" "$stage/manifest.json"
  (cd "$stage" && sha256sum database.dump globals.sql manifest.json > checksums.sha256)
  chmod 600 "$stage/database.dump" "$stage/globals.sql" "$stage/manifest.json" "$stage/checksums.sha256" 2>/dev/null || true
  if ! published="$("$LOCAL_STORE" publish-staged "$LOCAL_ROOT" "$stage")"; then
    rm -rf -- "$stage"
    fail "local PostgreSQL recovery bundle validation failed"
  fi
  published_item="$("$LOCAL_STORE" verify-bundle "$published")" || fail "published recovery bundle could not be reverified"
  public_id="$(jq -r '.public_id // empty' <<<"$published_item")"
  [[ "$public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || fail "published recovery bundle did not return a valid public id"
  rm -f -- "$dump" "$globals"
  prune_local_recovery_store >/dev/null \
    || log "WARNING: local recovery retention scan failed"
  POSTGRES_BACKUP_LOCAL_ROOT="$LOCAL_ROOT" MREADER_LOCAL_RECOVERY_STORE="$LOCAL_STORE" "$SYNC_CATALOG" >/dev/null \
    || log "WARNING: verified local recovery point is awaiting catalog projection"
  case "$purpose" in
    automatic|manual) latest_category=daily ;;
    *) latest_category="$purpose" ;;
  esac
  jq -n --arg recovery_id "$recovery_id" --arg public_id "$public_id" --arg purpose "$purpose" --arg created_at "$created_at" \
    '{recovery_id:$recovery_id,public_id:$public_id,filename:$recovery_id,purpose:$purpose,timestamp_utc:$created_at,
      source_format:"logical-dump",verified:true}' \
    > "$SPOOL/state/latest-${latest_category}.json"
  log "PostgreSQL logical recovery bundle verified locally: $purpose/$recovery_id"
}
finish_local_snapshot_bundle(){
  local recovery_id="$1" snapshot="$2" created_at="$3" stage="$LOCAL_ROOT/staging/$recovery_id"
  local published published_item public_id
  [[ -x "$LOCAL_STORE" ]] || fail "local recovery-store helper is unavailable"
  mkdir -p "$LOCAL_ROOT/staging"
  [[ ! -e "$stage" && ! -L "$stage" ]] || fail "local recovery staging bundle already exists: $recovery_id"
  mkdir "$stage"
  if ! cp -- "$snapshot" "$stage/snapshot.tar"; then
    rm -rf -- "$stage"
    fail "could not stage local PostgreSQL snapshot bundle"
  fi
  make_local_bundle_manifest "$recovery_id" physical snapshot "$created_at" "$stage/manifest.json"
  (cd "$stage" && sha256sum snapshot.tar manifest.json > checksums.sha256)
  chmod 600 "$stage/snapshot.tar" "$stage/manifest.json" "$stage/checksums.sha256" 2>/dev/null || true
  if ! published="$("$LOCAL_STORE" publish-staged "$LOCAL_ROOT" "$stage")"; then
    rm -rf -- "$stage"
    fail "local PostgreSQL snapshot bundle validation failed"
  fi
  published_item="$("$LOCAL_STORE" verify-bundle "$published")" || fail "published snapshot bundle could not be reverified"
  public_id="$(jq -r '.public_id // empty' <<<"$published_item")"
  [[ "$public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || fail "published snapshot bundle did not return a valid public id"
  rm -f -- "$snapshot"
  prune_local_recovery_store >/dev/null \
    || log "WARNING: local recovery retention scan failed"
  POSTGRES_BACKUP_LOCAL_ROOT="$LOCAL_ROOT" MREADER_LOCAL_RECOVERY_STORE="$LOCAL_STORE" "$SYNC_CATALOG" >/dev/null \
    || log "WARNING: verified local snapshot is awaiting catalog projection"
  jq -n --arg recovery_id "$recovery_id" --arg public_id "$public_id" --arg created_at "$created_at" \
    '{recovery_id:$recovery_id,public_id:$public_id,filename:$recovery_id,purpose:"snapshot",timestamp_utc:$created_at,
      source_format:"physical-snapshot",verified:true}' > "$SPOOL/state/latest-snapshots.json"
  log "PostgreSQL physical snapshot bundle verified locally: snapshot/$recovery_id"
}
logical_backup(){
  local category="$1" type="$2" label="${3:-}" trigger="${4:-automatic}" ts recovery_id file globals purpose
  wait_db
  recovery_id="$(backup_identity "$type" "$label")"
  file="$SPOOL/$recovery_id.dump"
  globals="$SPOOL/$recovery_id.globals.sql"
  log "Creating PostgreSQL logical backup: $(basename "$file")"
  if ! pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -Z 6 --no-owner --no-privileges > "$file"; then
    rm -f -- "$file" "$globals"
    fail "pg_dump failed"
  fi
  [[ -s "$file" ]] || fail "pg_dump produced an empty file"
  pg_restore --list "$file" >/dev/null
  if ! pg_dumpall -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --globals-only > "$globals"; then
    rm -f -- "$file" "$globals"
    fail "pg_dumpall --globals-only failed"
  fi
  [[ -s "$globals" ]] || { rm -f -- "$file" "$globals"; fail "pg_dumpall produced an empty globals file"; }
  case "$category" in
    daily) [[ "$type" == "daily" ]] && purpose=automatic || purpose=manual ;;
    pre-upgrade) purpose=pre-upgrade ;;
    pre-restore) purpose=pre-restore ;;
    *) rm -f -- "$file" "$globals"; fail "unsupported logical recovery category: $category" ;;
  esac
  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  finish_local_logical_bundle "$purpose" "$recovery_id" "$file" "$globals" "$ts"
  if [[ "$category" == "daily" ]]; then
    date +%s > "$SPOOL/state/last-daily-success-epoch"
    date '+%Y-%m-%d' > "$SPOOL/state/last-daily-date"
    printf '%s\n' "$type" > "$SPOOL/state/last-daily-type"
  fi
}
snapshot_backup(){
  local ts tmp file recovery_id
  wait_db
  recovery_id="$(backup_identity snapshot)"
  tmp="$SPOOL/snapshot-$(date +%s)-$$"; file="$SPOOL/$recovery_id.tar"
  rm -rf "$tmp"; mkdir -p "$tmp"
  log "Creating PostgreSQL physical base backup"
  if ! PGPASSWORD="$REPL_PASSWORD" pg_basebackup -h "$DB_HOST" -p "$DB_PORT" -U "$REPL_USER" -D "$tmp" -Ft -z -X stream -c fast --max-rate="$SNAPSHOT_MAX_RATE" --no-password; then
    date +%s > "$SPOOL/state/last-snapshot-failure-epoch"
    rm -rf "$tmp"
    fail "pg_basebackup failed using replication role $REPL_USER"
  fi
  [[ -s "$tmp/base.tar.gz" ]] || fail "pg_basebackup did not produce base.tar.gz"
  # -X stream creates a separate compressed pg_wal tar; package all generated
  # tar files without recompressing them a second time.
  tar -cf "$file" -C "$tmp" .
  rm -rf "$tmp"
  ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  finish_local_snapshot_bundle "$recovery_id" "$file" "$ts"
  date +%s > "$SPOOL/state/last-snapshot-epoch"
  rm -f "$SPOOL/state/last-snapshot-failure-epoch"
}
latest_daily_name(){
  "$LOCAL_STORE" catalog "$LOCAL_ROOT" 2>/dev/null \
    | jq -r '[.recovery_points[]? | select(.kind == "logical_dump" and (.purpose == "automatic" or .purpose == "manual"))] | sort_by(.created_at) | last | .recovery_id // empty'
}
latest_snapshot_name(){
  "$LOCAL_STORE" catalog "$LOCAL_ROOT" 2>/dev/null \
    | jq -r '[.recovery_points[]? | select(.kind == "physical_snapshot")] | sort_by(.created_at) | last | .recovery_id // empty'
}

run_cli_database_operation(){
  local operation_type="$1" category="$2" name="$3" expected_status="$4" metadata="${5:-{\"trigger\":\"cli\"}}" opid status
  wait_db; local_storage_ready_quiet || fail "host-local recovery storage is unavailable"
  metadata="$(printf '%s' "$metadata" | jq -ce 'if type == "object" then . else error("metadata must be an object") end')" \
    || fail "invalid CLI database-operation metadata"
  opid="$(queue_cli_database_operation "$operation_type" "$category" "$name" "$metadata")"
  [[ -n "$opid" ]] || fail "could not queue CLI $operation_type; another database operation may already be active"
  process_database_operation || true
  status="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -At -v ON_ERROR_STOP=1 -v rid="$opid" -c "SELECT status FROM database_operations WHERE id=:'rid'::uuid;" 2>/dev/null | tr -d '\r')"
  [[ "$status" == "$expected_status" ]] || fail "$operation_type did not complete successfully (operation=$opid status=${status:-unknown})"
  log "$operation_type completed from $category/$name using database operation $opid"
}

restore_backup_cli(){
  local category="$1" requested="$2" name
  case "$category" in
    daily|automatic|manual)
      if [[ "$requested" == "latest" ]]; then name="$(latest_daily_name)"; else name="$requested"; fi
      [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail "unsafe logical recovery identifier: $name"
      ;;
    snapshots|snapshot)
      if [[ "$requested" == "latest" ]]; then name="$(latest_snapshot_name)"; else name="$requested"; fi
      [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail "unsafe snapshot recovery identifier: $name"
      ;;
    pre-upgrade|pre-restore)
      name="$requested"
      [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail "unsafe logical recovery identifier: $name"
      ;;
    *) fail "unsupported restore category: $category" ;;
  esac
  [[ -n "$name" ]] || fail "No $category recovery point found locally"
  run_cli_database_operation restore "$category" "$name" completed
}

restore_daily(){ restore_backup_cli daily "${1:-latest}"; }

resolve_public_restore_target(){
  local public_id="$1" category_var="$2" recovery_var="$3" item recovery_id purpose resolved_category
  [[ "$public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || fail "invalid public recovery identifier: $public_id"
  item="$("$LOCAL_STORE" resolve-public-id "$LOCAL_ROOT" "$public_id")" || fail "public recovery identifier is unavailable: $public_id"
  recovery_id="$(jq -r '.recovery_id' <<<"$item")"
  purpose="$(jq -r '.purpose' <<<"$item")"
  case "$purpose" in
    automatic|manual|pre-upgrade|pre-restore) resolved_category="$purpose" ;;
    snapshot) resolved_category="snapshots" ;;
    *) fail "unsupported recovery purpose for public identifier: $purpose" ;;
  esac
  printf -v "$category_var" '%s' "$resolved_category"
  printf -v "$recovery_var" '%s' "$recovery_id"
}

resolve_restore_request(){
  local selector="$1" public_id item purpose category control
  case "$selector" in
    latest)
      public_id="$("$LOCAL_STORE" catalog "$LOCAL_ROOT" | jq -r '[.recovery_points[]? | select(.kind == "logical_dump" and (.purpose == "automatic" or .purpose == "manual"))] | sort_by(.created_at) | last | .public_id // empty')"
      ;;
    latest-snapshot)
      public_id="$("$LOCAL_STORE" catalog "$LOCAL_ROOT" | jq -r '[.recovery_points[]? | select(.kind == "physical_snapshot")] | sort_by(.created_at) | last | .public_id // empty')"
      ;;
    bkp_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f])
      public_id="$selector"
      ;;
    *) fail "restore selector must be latest, latest-snapshot, or an opaque public recovery id" ;;
  esac
  [[ "$public_id" =~ ^bkp_[0-9a-f]{24}$ ]] || fail "no verified recovery point is available for selector: $selector"
  item="$("$LOCAL_STORE" resolve-public-id "$LOCAL_ROOT" "$public_id")" || fail "recovery point is unavailable or failed verification: $public_id"
  purpose="$(jq -r '.purpose' <<<"$item")"
  case "$purpose" in
    automatic|manual|pre-upgrade|pre-restore) category="$purpose" ;;
    snapshot) category="snapshots" ;;
    *) fail "unsupported recovery purpose for restore request: $purpose" ;;
  esac
  control="$(restore_control_snapshot)" || return 1
  jq -cn \
    --arg public_id "$public_id" \
    --arg recovery_id "$(jq -r '.recovery_id' <<<"$item")" \
    --arg category "$category" \
    --arg sha256 "$(jq -r '.sha256' <<<"$item")" \
    --arg installation_fingerprint "$(jq -r '.installation_fingerprint' <<<"$control")" \
    --argjson restore_generation "$(jq -r '.restore_generation' <<<"$control")" \
    '{public_id:$public_id,recovery_id:$recovery_id,category:$category,sha256:$sha256,installation_fingerprint:$installation_fingerprint,restore_generation:$restore_generation}'
}

validate_restore_request_fence(){
  local category="$1" recovery_id="$2" recovery_public_id="$3" recovery_sha256="$4"
  local expected_installation_fingerprint="$5" expected_restore_generation="$6"
  local control item current_fingerprint current_generation actual_recovery_id actual_purpose actual_category actual_sha256
  [[ "$recovery_public_id" =~ ^bkp_[0-9a-f]{24}$ && "$recovery_sha256" =~ ^[0-9a-f]{64}$ ]] || {
    log "ERROR: restore fence metadata is missing or malformed"
    return 1
  }
  [[ "$expected_installation_fingerprint" =~ ^inst_[0-9a-f]{16}$ && "$expected_restore_generation" =~ ^[0-9]+$ && "$expected_restore_generation" -ge 1 ]] || {
    log "ERROR: restore installation/generation fence is missing or malformed"
    return 1
  }
  control="$(restore_control_snapshot)" || return 1
  current_fingerprint="$(jq -r '.installation_fingerprint' <<<"$control")"
  current_generation="$(jq -r '.restore_generation' <<<"$control")"
  [[ "$current_fingerprint" == "$expected_installation_fingerprint" && "$current_generation" == "$expected_restore_generation" ]] || {
    log "ERROR: restore control changed after confirmation"
    return 1
  }
  item="$("$LOCAL_STORE" resolve-public-id "$LOCAL_ROOT" "$recovery_public_id" 2>/dev/null)" || {
    log "ERROR: confirmed restore source is unavailable or failed verification: $recovery_public_id"
    return 1
  }
  actual_recovery_id="$(jq -r '.recovery_id' <<<"$item")"
  actual_purpose="$(jq -r '.purpose' <<<"$item")"
  actual_sha256="$(jq -r '.sha256' <<<"$item")"
  case "$actual_purpose" in
    automatic|manual|pre-upgrade|pre-restore) actual_category="$actual_purpose" ;;
    snapshot) actual_category="snapshots" ;;
    *) return 1 ;;
  esac
  [[ "$actual_recovery_id" == "$recovery_id" && "$actual_category" == "$category" && "$actual_sha256" == "$recovery_sha256" ]] || {
    log "ERROR: restore source changed after confirmation"
    return 1
  }
}

restore_public_id(){
  local recovery_public_id="$1" expected_installation_fingerprint="$2" expected_restore_generation="$3" recovery_sha256="$4"
  local category recovery_id metadata
  resolve_public_restore_target "$recovery_public_id" category recovery_id || return 1
  validate_restore_request_fence "$category" "$recovery_id" "$recovery_public_id" "$recovery_sha256" "$expected_installation_fingerprint" "$expected_restore_generation" \
    || fail "restore confirmation fence is stale or invalid"
  metadata="$(jq -cn \
    --arg recovery_public_id "$recovery_public_id" \
    --arg recovery_sha256 "$recovery_sha256" \
    --arg expected_installation_fingerprint "$expected_installation_fingerprint" \
    --argjson expected_restore_generation "$expected_restore_generation" \
    '{trigger:"cli",recovery_public_id:$recovery_public_id,recovery_sha256:$recovery_sha256,expected_installation_fingerprint:$expected_installation_fingerprint,expected_restore_generation:$expected_restore_generation}')"
  run_cli_database_operation restore "$category" "$recovery_id" completed "$metadata"
}

restore_drill_public_id(){
  local public_id="$1" category recovery_id
  resolve_public_restore_target "$public_id" category recovery_id || return 1
  run_cli_database_operation restore_drill "$category" "$recovery_id" verified
}


verify_restore_latest(){
  local name tmp checkdb counts
  wait_db; local_storage_ready_quiet || fail "host-local recovery storage is unavailable"
  name="$(latest_daily_name)"
  [[ -n "$name" ]] || fail "No local logical recovery point is available for restore verification"
  tmp="$SPOOL/verify-$name"
  log "Restore drill: staging local recovery point $name"
  download_verified_backup daily "$name" "$tmp"
  checkdb="mreader_restorecheck_$(date +%s)"
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
  createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -O "$DB_USER" "$checkdb" || return 1
  if ! pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$checkdb" --no-owner --no-privileges --exit-on-error "$tmp"; then
    dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
    rm -f "$tmp" "$tmp.sha256"
    fail "Restore drill pg_restore failed"
  fi
  counts="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$checkdb" -At -F ',' -c "select (select count(*) from series),(select count(*) from chapters),(select count(*) from pages);" 2>/dev/null || echo unknown)"
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
  rm -f "$tmp" "$tmp.sha256"
  log "Restore drill succeeded: backup=$name counts=$counts"
  date +%s > "$SPOOL/state/last-restore-verify-epoch"
}
logical_backup_done_today(){
  local today local_date created catalog
  today="$(date '+%Y-%m-%d')"
  local_date="$(cat "$SPOOL/state/last-daily-date" 2>/dev/null || true)"
  [[ "$local_date" == "$today" ]] && return 0
  catalog="$($LOCAL_STORE catalog "$LOCAL_ROOT" 2>/dev/null)" || return 1
  while IFS= read -r created; do
    [[ -n "$created" ]] || continue
    local_date="$(date -d "$created" '+%Y-%m-%d' 2>/dev/null || true)"
    if [[ "$local_date" == "$today" ]]; then
      printf '%s\n' "$today" > "$SPOOL/state/last-daily-date"
      date +%s > "$SPOOL/state/last-daily-success-epoch"
      printf 'local-catalog\n' > "$SPOOL/state/last-daily-type"
      return 0
    fi
  done < <(jq -r '.recovery_points[]? | select(.kind == "logical_dump" and (.purpose == "automatic" or .purpose == "manual")) | .created_at' <<<"$catalog")
  return 1
}

sql_quote_identifier(){
  # Identifiers here are generated by this script; quote defensively anyway.
  printf '"%s"' "${1//\"/\"\"}"
}

operation_update(){
  local id="$1" status="$2" phase="$3" error="${4:-}" result="${5-}" attempt
  [[ -n "$result" ]] || result='{}'
  if ! result="$(printf '%s' "$result" | jq -ce 'if type == "object" then . else error("database operation result must be a JSON object") end')"; then
    log "ERROR: refusing invalid database-operation result JSON: id=$id status=$status phase=$phase"
    return 1
  fi

  for attempt in 1 2 3; do
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -q -v ON_ERROR_STOP=1 \
      -v rid="$id" -v status="$status" -v phase="$phase" -v err="$error" -v result="$result" >/dev/null <<'SQL'
UPDATE database_operations
   SET status=:'status', phase=:'phase', error=NULLIF(:'err',''), result=:'result'::jsonb,
       completed_at=CASE WHEN :'status' IN ('verified','completed','failed','cancelled') THEN now() ELSE completed_at END
 WHERE id=:'rid'::uuid;
SQL
    then
      return 0
    fi
    log "ERROR: database-operation ledger update failed (attempt $attempt/3): id=$id status=$status phase=$phase"
    (( attempt < 3 )) && sleep "$attempt"
  done
  return 1
}

claim_database_operation(){
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -qAt -F '|' -v ON_ERROR_STOP=1 <<'SQL' 2>/dev/null || true
WITH candidate AS (
  SELECT id FROM database_operations
   WHERE status='queued'
   ORDER BY requested_at
   FOR UPDATE SKIP LOCKED LIMIT 1
), claimed AS (
  UPDATE database_operations d
     SET status='running', phase='claimed', started_at=now(), error=NULL
    FROM candidate
   WHERE d.id=candidate.id
  RETURNING d.id::text,d.operation_type,coalesce(d.category,''),coalesce(d.backup_filename,''),
            coalesce(d.metadata->>'recovery_public_id',''),coalesce(d.metadata->>'recovery_sha256',''),
            coalesce(d.metadata->>'expected_installation_fingerprint',''),coalesce(d.metadata->>'expected_restore_generation','')
)
SELECT * FROM claimed;
SQL
}

apply_current_migrations(){
  local target_db="$1" host="${2:-$DB_HOST}" port="${3:-$DB_PORT}"
  # Restore candidates use the same lock and preservation hook as upgrades.
  sh /usr/local/lib/mreader/migrate/apply.sh \
    -h "$host" -p "$port" -U "$DB_USER" -d "$target_db"
}

download_verified_backup(){
  local category="$1" recovery_id="$2" dest="$3" item purpose kind
  [[ "$recovery_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
    || fail "unsafe local recovery identifier: $recovery_id"
  [[ "$category" =~ ^(automatic|manual|pre-upgrade|pre-restore|snapshot|daily|snapshots)$ ]] \
    || fail "unsupported recovery category: $category"
  log "Staging verified local recovery point: $category/$recovery_id"
  item="$("$LOCAL_STORE" copy-artifact "$LOCAL_ROOT" "$recovery_id" "$dest")" || return 1
  purpose="$(jq -r '.purpose' <<<"$item")"
  kind="$(jq -r '.kind' <<<"$item")"
  case "$category:$purpose" in
    daily:automatic|daily:manual|snapshots:snapshot|automatic:automatic|manual:manual|pre-upgrade:pre-upgrade|pre-restore:pre-restore|snapshot:snapshot) ;;
    *) rm -f -- "$dest" "$dest.sha256"; fail "recovery point purpose does not match the requested category" ;;
  esac
  if [[ "$kind" == "physical_snapshot" ]]; then
    tar -tf "$dest" >/dev/null || fail "physical snapshot outer tar is unreadable: $recovery_id"
    tar -tf "$dest" | grep -Eq '(^|/)base\.tar\.gz$' || fail "physical snapshot is missing base.tar.gz: $recovery_id"
  else
    pg_restore --list "$dest" >/dev/null || fail "logical PostgreSQL archive is unreadable: $recovery_id"
  fi
}


validate_database_contents(){
  local target_db="$1" host="${2:-$DB_HOST}" port="${3:-$DB_PORT}" counts
  counts="$(psql -h "$host" -p "$port" -U "$DB_USER" -d "$target_db" -At -F ',' -v ON_ERROR_STOP=1 \
    -c "SELECT (SELECT count(*) FROM series),(SELECT count(*) FROM chapters),(SELECT count(*) FROM pages);" 2>/dev/null)" || return 1
  [[ "$counts" =~ ^[0-9]+,[0-9]+,[0-9]+$ ]] || return 1
  printf '%s\n' "$counts"
}

latest_migration(){
  local migration
  find "${MREADER_MIGRATIONS_DIR:-/migrations}" -maxdepth 1 -type f -name '*.sql' -print0 2>/dev/null |
    while IFS= read -r -d '' migration; do
      printf '%s\n' "${migration##*/}"
    done | sort | tail -n 1
}

validate_recovery_database_state(){
  local target_db="$1" host="${2:-$DB_HOST}" port="${3:-$DB_PORT}"
  local counts migration validation encoding orphan_rows bad_pages unvalidated_fks migration_applied connect_ok series_select_ok extras extra_json
  counts="$(validate_database_contents "$target_db" "$host" "$port")" || return 1
  migration="$(latest_migration)"
  [[ -n "$migration" ]] || { log "ERROR: no current migration files are available for drill validation"; return 1; }
  validation="$(psql -h "$host" -p "$port" -U "$DB_USER" -d "$target_db" -At -F '|' -v ON_ERROR_STOP=1 -v latest="$migration" -c "
SELECT current_setting('server_encoding'),
       ((SELECT count(*) FROM chapters c LEFT JOIN series s ON s.id=c.series_id WHERE s.id IS NULL)
        + (SELECT count(*) FROM pages p LEFT JOIN chapters c ON c.id=p.chapter_id WHERE c.id IS NULL)) AS orphan_rows,
       (SELECT count(*) FROM pages WHERE encoding_version <> 4 OR encoding_seed IS NULL OR length(encoding_seed) < 16 OR encoding_rows NOT BETWEEN 1 AND 32 OR encoding_columns NOT BETWEEN 1 AND 32) AS bad_page_encoding,
       (SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated) AS unvalidated_foreign_keys,
       EXISTS(SELECT 1 FROM schema_migrations WHERE version=:'latest') AS latest_migration_applied,
       has_database_privilege(current_user,current_database(),'CONNECT') AS database_connect,
       has_table_privilege(current_user,'series','SELECT') AS series_select;" 2>/dev/null)" || return 1
  IFS='|' read -r encoding orphan_rows bad_pages unvalidated_fks migration_applied connect_ok series_select_ok <<<"$validation"
  [[ "$encoding" == "UTF8" ]] || { log "ERROR: restored database encoding is $encoding, expected UTF8"; return 1; }
  [[ "$orphan_rows" == "0" ]] || { log "ERROR: restored database contains $orphan_rows orphan chapter/page row(s)"; return 1; }
  [[ "$bad_pages" == "0" ]] || { log "ERROR: restored database contains $bad_pages invalid protected-page encoding row(s)"; return 1; }
  [[ "$unvalidated_fks" == "0" ]] || { log "ERROR: restored database has $unvalidated_fks unvalidated foreign key constraint(s)"; return 1; }
  [[ "$migration_applied" == "t" ]] || { log "ERROR: latest migration $migration is not recorded in schema_migrations"; return 1; }
  [[ "$connect_ok" == "t" && "$series_select_ok" == "t" ]] || { log "ERROR: restored database runtime role lacks required CONNECT/series SELECT privileges"; return 1; }
  extras="$(psql -h "$host" -p "$port" -U "$DB_USER" -d postgres -At -v ON_ERROR_STOP=1 -v source_db="$DB_NAME" -v target_db="$target_db" -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate AND datname <> 'postgres' AND datname <> :'source_db' AND datname <> :'target_db' ORDER BY datname;" 2>/dev/null)" || return 1
  extra_json="$(printf '%s\n' "$extras" | jq -Rsc 'split("\n") | map(select(length > 0))')"
  jq -cn --arg counts "$counts" --arg server_encoding "$encoding" --arg latest_migration "$migration" --argjson orphan_rows "$orphan_rows" --argjson bad_page_encoding "$bad_pages" --argjson unvalidated_foreign_keys "$unvalidated_fks" --argjson extra_databases "$extra_json" \
    '{counts:$counts,server_encoding:$server_encoding,latest_migration:$latest_migration,orphan_rows:$orphan_rows,bad_page_encoding:$bad_page_encoding,unvalidated_foreign_keys:$unvalidated_foreign_keys,required_grants:true,extra_databases:$extra_databases}'
}

tar_paths_safe(){
  local mode="$1" archive="$2"
  local listing
  if [[ "$mode" == "gzip" ]]; then listing="$(tar -tzf "$archive")"; else listing="$(tar -tf "$archive")"; fi
  ! printf '%s\n' "$listing" | grep -Eq '(^/|(^|/)\.\.(/|$))'
}

snapshot_stage_stop(){
  local stage_root="$1" data="$stage_root/data"
  if [[ -f "$data/postmaster.pid" ]]; then
    su-exec postgres pg_ctl -D "$data" -m fast -w stop >/dev/null 2>&1 || true
  fi
}

snapshot_stage_cleanup(){
  local stage_root="$1"
  snapshot_stage_stop "$stage_root"
  rm -rf "$stage_root"
}

snapshot_stage_start(){
  local snapshot_file="$1" stage_root="$2" port="$3"
  local package="$stage_root/package" data="$stage_root/data" socket="$stage_root/socket"
  local base wal extra pg_major runtime_major hba logfile
  rm -rf "$stage_root"
  mkdir -p "$package" "$data" "$socket"
  tar_paths_safe plain "$snapshot_file" || { log "ERROR: unsafe path inside physical snapshot outer tar"; return 1; }
  tar -xf "$snapshot_file" -C "$package" || return 1
  base="$(find "$package" -maxdepth 1 -type f -name 'base.tar.gz' -print -quit)"
  [[ -n "$base" && -s "$base" ]] || { log "ERROR: physical snapshot is missing base.tar.gz"; return 1; }
  wal="$(find "$package" -maxdepth 1 -type f -name 'pg_wal.tar.gz' -print -quit)"
  extra="$(find "$package" -maxdepth 1 -type f -name '*.tar.gz' ! -name 'base.tar.gz' ! -name 'pg_wal.tar.gz' -print -quit)"
  if [[ -n "$extra" ]]; then
    log "ERROR: physical snapshot contains external tablespace archive $(basename "$extra"); automated snapshot restore does not support external PostgreSQL tablespaces"
    return 1
  fi
  tar_paths_safe gzip "$base" || { log "ERROR: unsafe path inside physical snapshot base.tar.gz"; return 1; }
  tar -xzf "$base" -C "$data" || return 1
  if [[ -s "$data/tablespace_map" ]]; then
    log "ERROR: physical snapshot uses external tablespaces; automated restore is refused"
    return 1
  fi
  if [[ -n "$wal" && -s "$wal" ]]; then
    mkdir -p "$data/pg_wal"
    tar_paths_safe gzip "$wal" || { log "ERROR: unsafe path inside physical snapshot pg_wal.tar.gz"; return 1; }
    tar -xzf "$wal" -C "$data/pg_wal" || return 1
  fi
  [[ -s "$data/PG_VERSION" ]] || { log "ERROR: physical snapshot is missing PG_VERSION"; return 1; }
  pg_major="$(tr -d '[:space:]' < "$data/PG_VERSION")"
  runtime_major="$(postgres --version | sed -nE 's/.* ([0-9]+)(\..*)?$/\1/p')"
  [[ "$pg_major" == "$runtime_major" ]] || {
    log "ERROR: physical snapshot PostgreSQL major version $pg_major does not match restore runtime major $runtime_major"
    return 1
  }
  hba="$stage_root/pg_hba.restore.conf"
  cat > "$hba" <<'HBA'
local all all trust
HBA
  logfile="$stage_root/postgres.log"
  chmod 700 "$data" "$socket"
  chown -R postgres:postgres "$stage_root"
  if ! su-exec postgres pg_ctl -D "$data" -l "$logfile" \
      -o "-c listen_addresses='' -c unix_socket_directories='$socket' -p $port -c hba_file='$hba' -c shared_preload_libraries=''" \
      -w start >/dev/null; then
    log "ERROR: isolated physical snapshot PostgreSQL failed to start; tail follows"
    tail -n 80 "$logfile" >&2 2>/dev/null || true
    return 1
  fi
  pg_isready -h "$socket" -p "$port" -d "$DB_NAME" >/dev/null 2>&1 || {
    log "ERROR: isolated physical snapshot PostgreSQL is not ready for database $DB_NAME"
    snapshot_stage_stop "$stage_root"
    return 1
  }
}

prepare_snapshot_stage(){
  local category="$1" filename="$2" opid="$3" stage_name="$4" tmp_var="$5" root_var="$6" socket_var="$7"
  local prepared_tmp prepared_root prepared_socket
  prepared_tmp="$SPOOL/op-${opid}-${filename}"
  prepared_root="$SPOOL/${stage_name}-${opid}"
  prepared_socket="$prepared_root/socket"
  operation_update "$opid" running verifying-physical-snapshot || return 1
  download_verified_backup "$category" "$filename" "$prepared_tmp" || return 1
  if ! operation_update "$opid" running starting-isolated-snapshot-cluster; then
    rm -f "$prepared_tmp" "$prepared_tmp.sha256"
    return 1
  fi
  snapshot_stage_start "$prepared_tmp" "$prepared_root" "$SNAPSHOT_STAGE_PORT" || {
    rm -f "$prepared_tmp" "$prepared_tmp.sha256"
    snapshot_stage_cleanup "$prepared_root"
    return 1
  }
  if ! operation_update "$opid" running applying-current-migrations-to-snapshot \
      || ! apply_current_migrations "$DB_NAME" "$prepared_socket" "$SNAPSHOT_STAGE_PORT"; then
    snapshot_stage_cleanup "$prepared_root"
    rm -f "$prepared_tmp" "$prepared_tmp.sha256"
    return 1
  fi
  printf -v "$tmp_var" '%s' "$prepared_tmp"
  printf -v "$root_var" '%s' "$prepared_root"
  printf -v "$socket_var" '%s' "$prepared_socket"
}

snapshot_restore_drill_selected(){
  local category="$1" filename="$2" opid="$3" tmp stage_root socket counts validation result rc=0
  prepare_snapshot_stage "$category" "$filename" "$opid" snapshot-drill tmp stage_root socket || return 1
  operation_update "$opid" running validating-physical-snapshot || rc=1
  if (( rc == 0 )); then validation="$(validate_recovery_database_state "$DB_NAME" "$socket" "$SNAPSHOT_STAGE_PORT")" || rc=1; fi
  if (( rc == 0 )); then counts="$(jq -r '.counts' <<<"$validation")"; fi
  snapshot_stage_cleanup "$stage_root"
  rm -f "$tmp" "$tmp.sha256"
  (( rc == 0 )) || return 1
  result="$(jq -cn --arg backup "$filename" --argjson validation "$validation" '{counts:$validation.counts,backup:$backup,source_format:"physical-snapshot",validation:$validation}')"
  operation_update "$opid" verified restore-drill-complete "" "$result" || return 1
  log "Physical snapshot restore drill verified: operation=$opid backup=$filename counts=$counts"
}

snapshot_convert_to_logical(){
  local category="$1" filename="$2" opid="$3" output="$4"
  local tmp stage_root socket counts rc=0
  prepare_snapshot_stage "$category" "$filename" "$opid" snapshot-restore tmp stage_root socket || return 1
  operation_update "$opid" running validating-physical-snapshot || rc=1
  if (( rc == 0 )); then counts="$(validate_database_contents "$DB_NAME" "$socket" "$SNAPSHOT_STAGE_PORT")" || rc=1; fi
  operation_update "$opid" running converting-snapshot-to-logical-stage || rc=1
  if (( rc == 0 )); then
    PGPASSWORD='' pg_dump -h "$socket" -p "$SNAPSHOT_STAGE_PORT" -U "$DB_USER" -d "$DB_NAME" \
      -Fc -Z 6 --no-owner --no-privileges > "$output" || rc=1
    [[ -s "$output" ]] || rc=1
    if (( rc == 0 )); then pg_restore --list "$output" >/dev/null || rc=1; fi
  fi
  snapshot_stage_cleanup "$stage_root"
  rm -f "$tmp" "$tmp.sha256"
  if (( rc != 0 )); then rm -f "$output"; return 1; fi
  log "Physical snapshot converted to validated logical staging archive: backup=$filename counts=$counts"
}

restore_drill_selected(){
  local category="$1" filename="$2" opid="$3" tmp checkdb counts validation result
  if [[ "$category" == "snapshots" || "$category" == "snapshot" ]]; then
    snapshot_restore_drill_selected "$category" "$filename" "$opid"
    return $?
  fi
  tmp="$SPOOL/op-${opid}-${filename}"
  checkdb="mreader_drill_${opid:0:8}"
  operation_update "$opid" running verifying-backup || return 1
  download_verified_backup "$category" "$filename" "$tmp" || return 1
  operation_update "$opid" running restoring-temporary-database || return 1
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
  createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -O "$DB_USER" "$checkdb" || return 1
  if ! pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$checkdb" --no-owner --no-privileges --exit-on-error "$tmp" >/dev/null; then
    dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
    rm -f "$tmp" "$tmp.sha256"
    return 1
  fi
  operation_update "$opid" running applying-current-migrations || return 1
  apply_current_migrations "$checkdb" || { dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true; return 1; }
  operation_update "$opid" running validating-restored-database || return 1
  validation="$(validate_recovery_database_state "$checkdb")" || { dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true; return 1; }
  counts="$(jq -r '.counts' <<<"$validation")"
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$checkdb" >/dev/null 2>&1 || true
  rm -f "$tmp" "$tmp.sha256"
  result="$(jq -cn --arg backup "$filename" --argjson validation "$validation" '{counts:$validation.counts,backup:$backup,source_format:"logical-dump",validation:$validation}')"
  operation_update "$opid" verified restore-drill-complete "" "$result" || return 1
  log "Restore drill verified: operation=$opid backup=$filename counts=$counts"
}

capture_pre_restore_safety_ids(){
  local opid="$1" safety_state
  (logical_backup pre-restore pre-restore "admin-${opid:0:8}" restore) || return 1
  safety_state="$SPOOL/state/latest-pre-restore.json"
  [[ -f "$safety_state" && ! -L "$safety_state" ]] || return 1
  jq -ce '
    select((.public_id | type == "string" and test("^bkp_[0-9a-f]{24}$")) and
           (.recovery_id | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"))) |
    {public_id,recovery_id}
  ' "$safety_state"
}

journaled_database_cutover(){
  local cutover_marker="$1" staged="$2" olddb="$3"
  update_restore_cutover_phase "$cutover_marker" rename-live-pending
  if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME','$staged') AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$olddb" WITH (FORCE);
ALTER DATABASE "$DB_NAME" RENAME TO "$olddb";
SQL
  then
    log "ERROR: live database rename interrupted; persistent cutover journal retained"
    return 1
  fi
  update_restore_cutover_phase "$cutover_marker" live-renamed
  update_restore_cutover_phase "$cutover_marker" promote-staged-pending
  if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$staged' AND pid <> pg_backend_pid();
ALTER DATABASE "$staged" RENAME TO "$DB_NAME";
SQL
  then
    log "ERROR: staged database promotion interrupted; persistent cutover journal retained"
    return 1
  fi
  update_restore_cutover_phase "$cutover_marker" cutover-live
}

classify_v2_restore_recovery(){
  local phase="$1" live_exists="$2" old_exists="$3" staged_exists="$4"
  local current_generation="$5" expected_generation="$6" next_generation="$7"

  if (( current_generation == expected_generation )); then
    if (( live_exists == 1 && old_exists == 0 && staged_exists == 1 )); then
      case "$phase" in
        prepared|rename-live-pending) printf '%s\n' abort-unstarted; return 0 ;;
      esac
    fi
    if (( live_exists == 0 && old_exists == 1 && staged_exists == 1 )); then
      case "$phase" in
        rename-live-pending|live-renamed|promote-staged-pending) printf '%s\n' rollback-first-rename; return 0 ;;
      esac
    fi
    if (( live_exists == 1 && old_exists == 1 && staged_exists == 0 )); then
      case "$phase" in
        promote-staged-pending|cutover-live|reconciling|generation-commit-pending) printf '%s\n' finalize-expected-generation; return 0 ;;
      esac
    fi
  elif (( current_generation == next_generation )); then
    if (( live_exists == 1 && staged_exists == 0 )); then
      case "$phase" in
        cutover-live|reconciling|generation-commit-pending|generation-committed) printf '%s\n' finalize-committed-generation; return 0 ;;
      esac
    fi
  fi
  printf '%s\n' ambiguous
}

reconcile_restored_application_work(){
  local restore_generation="$1"
  [[ "$restore_generation" =~ ^[0-9]+$ && "$restore_generation" -ge 1 ]] || return 1
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -v restore_generation="$restore_generation" >/dev/null <<'SQL'
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('mreader:restore-reconcile'));

UPDATE ingestion_operations
   SET status='cancelled',
       phase='superseded-by-restore',
       revision=revision+1,
       lease_generation=lease_generation+1,
       cancel_requested_at=COALESCE(cancel_requested_at,now()),
       acknowledged_at=now(),
       error_code='restore-superseded',
       updated_at=now()
 WHERE status IN ('queued','running','cancel_requested');

UPDATE media_operations
   SET status='failed',
       media_generation=media_generation+1,
       queue_dispatched_at=NULL,
       processing_started_at=NULL,
       processing_heartbeat_at=NULL,
       failed_at=now(),
       completed_at=NULL,
       last_error='Superseded by database restore generation ' || :restore_generation::text,
       updated_at=now()
 WHERE status IN ('queued','retry','processing');

UPDATE event_outbox
   SET published_at=now(),
       locked_at=NULL,
       locked_by=NULL,
       last_error='Suppressed by database restore generation ' || :restore_generation::text,
       headers=COALESCE(headers,'{}'::jsonb) || jsonb_build_object(
         'restore_suppressed', true,
         'restore_generation', :restore_generation::bigint
       )
 WHERE published_at IS NULL;
COMMIT;
SQL
}

prepare_restore_generation_mirror(){
  local installation_fingerprint="$1" next_restore_generation="$2" opid="$3" source_public_id="$4"
  validate_database_contents "$DB_NAME" >/dev/null || return 1
  sync_database_restore_state "$installation_fingerprint" "$next_restore_generation" "$opid" "$source_public_id"
}

commit_restored_generation(){
  local cutover_marker="$1" opid="$2" expected_installation_fingerprint="$3"
  local expected_restore_generation="$4" next_restore_generation="$5" source_public_id="$6"

  update_restore_cutover_phase "$cutover_marker" reconciling
  reconcile_restored_application_work "$next_restore_generation" || return 1
  prepare_restore_generation_mirror "$expected_installation_fingerprint" "$next_restore_generation" "$opid" "$source_public_id" || return 1
  update_restore_cutover_phase "$cutover_marker" generation-commit-pending
  advance_restore_generation "$expected_installation_fingerprint" "$expected_restore_generation" >/dev/null || return 1
  update_restore_cutover_phase "$cutover_marker" generation-committed
}

complete_recovered_restore_ledger(){
  local marker="$1" opid="$2" olddb="$3" audit_sql="$4" next_generation="$5"
  operation_update "$opid" completed recovered-after-agent-restart "" \
    "{\"recovered\":true,\"restore_generation\":$next_generation}" || return 1
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$olddb" >/dev/null 2>&1 || true
  rm -f -- "$marker" "$audit_sql"
}

finalize_expected_restore_generation(){
  local marker="$1" opid="$2" olddb="$3" audit_sql="$4" fingerprint="$5"
  local expected_generation="$6" next_generation="$7" source_public_id="$8"
  commit_restored_generation "$marker" "$opid" "$fingerprint" "$expected_generation" "$next_generation" "$source_public_id" || return 1
  complete_recovered_restore_ledger "$marker" "$opid" "$olddb" "$audit_sql" "$next_generation"
}

finalize_committed_restore_generation(){
  local marker="$1" opid="$2" olddb="$3" audit_sql="$4" fingerprint="$5" next_generation="$6" source_public_id="$7"
  prepare_restore_generation_mirror "$fingerprint" "$next_generation" "$opid" "$source_public_id" || return 1
  update_restore_cutover_phase "$marker" generation-committed
  complete_recovered_restore_ledger "$marker" "$opid" "$olddb" "$audit_sql" "$next_generation"
}

reconcile_v2_restore_cutover(){
  local marker="$1" opid staged olddb audit_sql phase journal_fingerprint expected_generation next_generation source_public_id
  local control current_fingerprint current_generation live_exists=0 old_exists=0 staged_exists=0 action
  opid="$(jq -r '.operation_id // empty' "$marker")"
  staged="$(jq -r '.staged_db // empty' "$marker")"
  olddb="$(jq -r '.old_db // empty' "$marker")"
  audit_sql="$(jq -r '.audit_sql // empty' "$marker")"
  phase="$(jq -r '.phase // empty' "$marker")"
  journal_fingerprint="$(jq -r '.installation_fingerprint // empty' "$marker")"
  expected_generation="$(jq -r '.expected_restore_generation // empty' "$marker")"
  next_generation="$(jq -r '.next_restore_generation // empty' "$marker")"
  source_public_id="$(jq -r '.source_public_id // empty' "$marker")"

  [[ "$opid" =~ ^[0-9a-fA-F-]{36}$ && "$staged" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$olddb" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 2
  [[ "$journal_fingerprint" =~ ^inst_[0-9a-f]{16}$ && "$expected_generation" =~ ^[0-9]+$ && "$next_generation" =~ ^[0-9]+$ ]] || return 2
  [[ "$source_public_id" =~ ^bkp_[0-9a-f]{24}$ && "$next_generation" -eq $((expected_generation + 1)) ]] || return 2

  control="$(restore_control_snapshot)" || return 2
  current_fingerprint="$(jq -r '.installation_fingerprint' <<<"$control")"
  current_generation="$(jq -r '.restore_generation' <<<"$control")"
  [[ "$current_fingerprint" == "$journal_fingerprint" ]] || return 2

  database_exists "$DB_NAME" && live_exists=1 || true
  database_exists "$olddb" && old_exists=1 || true
  database_exists "$staged" && staged_exists=1 || true
  action="$(classify_v2_restore_recovery "$phase" "$live_exists" "$old_exists" "$staged_exists" "$current_generation" "$expected_generation" "$next_generation")"

  case "$action" in
    abort-unstarted)
      dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      operation_update "$opid" failed cutover-not-started "Restore worker restarted before database cutover; production database was unchanged." || return 1
      rm -f -- "$marker" "$audit_sql"
      ;;
    rollback-first-rename)
      psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL || return 1
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$olddb' AND pid <> pg_backend_pid();
ALTER DATABASE "$olddb" RENAME TO "$DB_NAME";
SQL
      operation_update "$opid" failed recovered-by-rollback "Interrupted cutover rolled back after backup-agent restart." || return 1
      database_exists "$staged" && dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      rm -f -- "$marker" "$audit_sql"
      ;;
    finalize-expected-generation)
      if validate_database_contents "$DB_NAME" >/dev/null \
          && restore_import_audit "$audit_sql" \
          && restore_mark_superseded_operations \
          && validate_database_contents "$DB_NAME" >/dev/null; then
        finalize_expected_restore_generation "$marker" "$opid" "$olddb" "$audit_sql" "$journal_fingerprint" \
          "$expected_generation" "$next_generation" "$source_public_id" || return 1
      else
        log "ERROR: interrupted restore validation failed at expected generation; rolling back to $olddb"
        rollback_database_cutover "$staged" "$olddb" || return 1
        operation_update "$opid" failed recovered-by-rollback "Interrupted restore was rolled back after restart." || return 1
        dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
        rm -f -- "$marker" "$audit_sql"
      fi
      ;;
    finalize-committed-generation)
      # Host generation already committed. Never auto-rollback to the old generation.
      finalize_committed_restore_generation "$marker" "$opid" "$olddb" "$audit_sql" "$journal_fingerprint" "$next_generation" "$source_public_id" || return 1
      ;;
    ambiguous|*) return 2 ;;
  esac
}

restore_logical_source_enterprise(){
  local category="$1" filename="$2" opid="$3" tmp="$4" source_format="$5"
  local recovery_public_id="$6" recovery_sha256="$7" expected_installation_fingerprint="$8" expected_restore_generation="$9"
  local staged olddb audit_sql counts safety_state safety_public_id safety_recovery_id next_restore_generation
  local cutover_marker journal_payload
  staged="mreader_restore_${opid:0:8}"
  olddb="mreader_before_${opid:0:8}"

  operation_update "$opid" running staging-restore || return 1
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
  createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -O "$DB_USER" "$staged" || return 1
  pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$staged" --no-owner --no-privileges --exit-on-error "$tmp" >/dev/null || return 1

  operation_update "$opid" running migrating-staged-database || return 1
  apply_current_migrations "$staged" || return 1
  counts="$(validate_database_contents "$staged")" || return 1

  audit_sql="$SPOOL/state/database-operations-${opid}.sql"
  pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --data-only --table=database_operations --column-inserts --no-owner --no-privileges > "$audit_sql" || return 1

  operation_update "$opid" running creating-pre-restore-safety-backup || return 1
  safety_state="$(capture_pre_restore_safety_ids "$opid")" || return 1
  safety_public_id="$(jq -r '.public_id' <<<"$safety_state")"
  safety_recovery_id="$(jq -r '.recovery_id' <<<"$safety_state")"

  validate_restore_request_fence "$category" "$filename" "$recovery_public_id" "$recovery_sha256" "$expected_installation_fingerprint" "$expected_restore_generation" || return 42
  next_restore_generation=$((expected_restore_generation + 1))
  cutover_marker="$RESTORE_CONTROL_DIR/restore-cutover-${opid}.json"
  journal_payload="$(jq -cn --arg opid "$opid" --arg phase prepared --arg installation_fingerprint "$expected_installation_fingerprint" \
    --argjson expected_restore_generation "$expected_restore_generation" --argjson next_restore_generation "$next_restore_generation" \
    --arg source_public_id "$recovery_public_id" --arg source_recovery_id "$filename" --arg source_sha256 "$recovery_sha256" \
    --arg safety_public_id "$safety_public_id" --arg safety_recovery_id "$safety_recovery_id" --arg staged "$staged" --arg olddb "$olddb" \
    --arg filename "$filename" --arg category "$category" --arg source_format "$source_format" --arg audit_sql "$audit_sql" \
    '{schema_version:2,operation_id:$opid,phase:$phase,installation_fingerprint:$installation_fingerprint,
      expected_restore_generation:$expected_restore_generation,next_restore_generation:$next_restore_generation,
      source_public_id:$source_public_id,source_recovery_id:$source_recovery_id,source_sha256:$source_sha256,
      safety_public_id:$safety_public_id,safety_recovery_id:$safety_recovery_id,staged_db:$staged,old_db:$olddb,
      filename:$filename,category:$category,source_format:$source_format,audit_sql:$audit_sql,created_at_utc:(now|todate),updated_at_utc:(now|todate)}')" || return 1
  write_restore_cutover_journal "$cutover_marker" "$journal_payload"

  operation_update "$opid" running atomic-cutover || return 1
  journaled_database_cutover "$cutover_marker" "$staged" "$olddb" || return 1

  if ! restore_import_audit "$audit_sql" || ! restore_mark_superseded_operations; then
    log "ERROR: database-protection audit import/cleanup failed after cutover; rolling back database names"
    if rollback_database_cutover "$staged" "$olddb"; then
      operation_update "$opid" failed audit-import-rollback "Restore cutover rolled back because database-protection audit history could not be imported safely." || true
      dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      rm -f "$cutover_marker" "$audit_sql"
    else
      log "ERROR: rollback after audit import failure also failed; persistent recovery journal retained"
    fi
    return 1
  fi

  operation_update "$opid" running validating-cutover || return 1
  if ! validate_database_contents "$DB_NAME" >/dev/null; then
    log "ERROR: post-cutover validation failed; rolling back database names"
    if rollback_database_cutover "$staged" "$olddb"; then
      operation_update "$opid" failed validation-rollback "Restore cutover rolled back because post-cutover validation failed." || true
      dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      rm -f "$cutover_marker" "$audit_sql"
    else
      log "ERROR: rollback after validation failure also failed; persistent recovery journal retained"
    fi
    return 1
  fi

  commit_restored_generation "$cutover_marker" "$opid" "$expected_installation_fingerprint" \
    "$expected_restore_generation" "$next_restore_generation" "$recovery_public_id" || return 1
  operation_update "$opid" completed restore-complete "" \
    "{\"backup\":\"$filename\",\"counts\":\"$counts\",\"source_format\":\"$source_format\"}" || {
      log "ERROR: restored database is valid but terminal operation ledger update failed; retaining rollback database and recovery journal"
      return 1
    }
  dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$olddb" >/dev/null 2>&1 || true
  rm -f "$tmp" "$tmp.sha256" "$audit_sql" "$cutover_marker"
  log "Enterprise restore completed: operation=$opid backup=$category/$filename source=$source_format"
}

restore_selected_enterprise(){
  local category="$1" filename="$2" opid="$3"
  local recovery_public_id="$4" recovery_sha256="$5" expected_installation_fingerprint="$6" expected_restore_generation="$7"
  local tmp source_format
  if [[ "$category" == "snapshots" || "$category" == "snapshot" ]]; then
    tmp="$SPOOL/op-${opid}-snapshot-converted.dump"
    source_format="physical-snapshot"
    snapshot_convert_to_logical "$category" "$filename" "$opid" "$tmp" || return 1
  else
    tmp="$SPOOL/op-${opid}-${filename}"
    source_format="logical-dump"
    operation_update "$opid" running verifying-backup || return 1
    download_verified_backup "$category" "$filename" "$tmp" || return 1
  fi
  restore_logical_source_enterprise "$category" "$filename" "$opid" "$tmp" "$source_format" \
    "$recovery_public_id" "$recovery_sha256" "$expected_installation_fingerprint" "$expected_restore_generation"
}


database_exists(){
  local name="$1"
  [[ "$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -At -v ON_ERROR_STOP=1 -v dbname="$name" -c "SELECT 1 FROM pg_database WHERE datname=:'dbname' LIMIT 1;" 2>/dev/null | tr -d '\r')" == "1" ]]
}

restore_import_audit(){
  local audit_sql="$1"
  [[ -s "$audit_sql" ]] || return 0
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "TRUNCATE database_operations;" >/dev/null || return 1
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 < "$audit_sql" >/dev/null || return 1
}

restore_mark_superseded_operations(){
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
UPDATE database_operations
   SET status='cancelled', phase='superseded-by-restore', completed_at=now(),
       error='Superseded by point-in-time database restore.'
 WHERE status IN ('queued','running') AND operation_type <> 'restore';
SQL
}

rollback_database_cutover(){
  local staged="$1" olddb="$2"
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME','$olddb','$staged') AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$staged" WITH (FORCE);
ALTER DATABASE "$DB_NAME" RENAME TO "$staged";
ALTER DATABASE "$olddb" RENAME TO "$DB_NAME";
SQL
}

reconcile_restore_cutovers(){
  local marker schema_version opid staged olddb audit_sql live_exists old_exists staged_exists
  shopt -s nullglob
  for marker in "$RESTORE_CONTROL_DIR"/restore-cutover-*.json "$SPOOL"/state/restore-cutover-*.json; do
    schema_version="$(jq -r '.schema_version // 1' "$marker" 2>/dev/null || true)"
    if [[ "$schema_version" == "2" ]]; then
      if ! reconcile_v2_restore_cutover "$marker"; then
        log "ERROR: ambiguous v2 restore recovery state; leaving journal for operator inspection: $marker"
      fi
      continue
    fi
    opid="$(jq -r '.operation_id // empty' "$marker" 2>/dev/null || true)"
    staged="$(jq -r '.staged_db // empty' "$marker" 2>/dev/null || true)"
    olddb="$(jq -r '.old_db // empty' "$marker" 2>/dev/null || true)"
    audit_sql="$(jq -r '.audit_sql // empty' "$marker" 2>/dev/null || true)"
    [[ "$opid" =~ ^[0-9a-fA-F-]{36}$ && "$staged" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$olddb" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
      log "ERROR: invalid restore recovery marker; leaving it for manual inspection: $marker"
      continue
    }

    live_exists=0; old_exists=0; staged_exists=0
    database_exists "$DB_NAME" && live_exists=1 || true
    database_exists "$olddb" && old_exists=1 || true
    database_exists "$staged" && staged_exists=1 || true
    log "Restore recovery marker detected: op=$opid live=$live_exists old=$old_exists staged=$staged_exists"

    if (( live_exists == 1 && old_exists == 1 )); then
      # Both rename steps completed. Validate current live DB; if valid, preserve
      # audit history and finalize. Otherwise restore the old DB name.
      if validate_database_contents "$DB_NAME" >/dev/null && apply_current_migrations "$DB_NAME"; then
        if restore_import_audit "$audit_sql" && restore_mark_superseded_operations && validate_database_contents "$DB_NAME" >/dev/null; then
          if ! operation_update "$opid" completed recovered-after-agent-restart "" '{"recovered":true}'; then
            log "ERROR: recovered database is valid but terminal ledger update failed; retaining rollback database and recovery marker"
            continue
          fi
          dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$olddb" >/dev/null 2>&1 || true
          rm -f "$marker" "$audit_sql"
          database_exists "$staged" && dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
          log "Recovered and finalized interrupted restore: operation=$opid"
          continue
        fi
      fi
      log "ERROR: interrupted restore validation failed; rolling back to $olddb"
      psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL || true
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME','$olddb') AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$staged" WITH (FORCE);
ALTER DATABASE "$DB_NAME" RENAME TO "$staged";
ALTER DATABASE "$olddb" RENAME TO "$DB_NAME";
SQL
      operation_update "$opid" failed recovered-by-rollback "Interrupted restore was rolled back after restart."
      dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      rm -f "$marker" "$audit_sql"
      continue
    fi

    if (( live_exists == 0 && old_exists == 1 )); then
      # First rename succeeded but staged->live did not. Restore the original DB.
      psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL || true
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$olddb' AND pid <> pg_backend_pid();
ALTER DATABASE "$olddb" RENAME TO "$DB_NAME";
SQL
      operation_update "$opid" failed recovered-by-rollback "Interrupted cutover rolled back after backup-agent restart."
      database_exists "$staged" && dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      rm -f "$marker" "$audit_sql"
      log "Rolled back interrupted first-step database rename: operation=$opid"
      continue
    fi

    if (( live_exists == 1 && old_exists == 0 && staged_exists == 1 )); then
      # Marker was persisted, but cutover never replaced the live DB.
      dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$staged" >/dev/null 2>&1 || true
      operation_update "$opid" failed cutover-not-started "Restore worker restarted before database cutover; production database was unchanged."
      rm -f "$marker" "$audit_sql"
      continue
    fi

    if (( live_exists == 1 && old_exists == 0 && staged_exists == 0 )); then
      # Likely completed cutover where old DB cleanup succeeded just before the
      # agent restarted. Validate and finalize rather than reporting a false failure.
      if validate_database_contents "$DB_NAME" >/dev/null && restore_import_audit "$audit_sql" && restore_mark_superseded_operations; then
        if ! operation_update "$opid" completed recovered-after-agent-restart "" '{"recovered":true,"old_database_already_removed":true}'; then
          log "ERROR: recovered completed cutover is valid but terminal ledger update failed; retaining recovery marker"
          continue
        fi
        rm -f "$marker" "$audit_sql"
        continue
      fi
      log "ERROR: completed-cutover recovery could not validate/import audit state; leaving marker for operator inspection: $marker"
    fi

    log "ERROR: ambiguous restore recovery state; leaving marker for operator inspection: $marker"
  done
  shopt -u nullglob
}

reconcile_orphaned_database_operations_on_startup(){
  local row opid optype phase marker legacy_marker
  while IFS='|' read -r opid optype phase; do
    [[ "$opid" =~ ^[0-9a-fA-F-]{36}$ ]] || continue
    marker="$RESTORE_CONTROL_DIR/restore-cutover-${opid}.json"
    legacy_marker="$SPOOL/state/restore-cutover-${opid}.json"
    if [[ "$optype" == "restore" && ( -f "$marker" || -f "$legacy_marker" ) ]]; then
      # A persisted cutover marker is reconciled separately and remains the
      # authoritative source of truth for an interrupted destructive restore.
      continue
    fi
    log "Recovering orphaned database operation from prior backup-agent process: id=$opid type=$optype phase=$phase"
    operation_update "$opid" failed worker-restarted       "Backup agent restarted before this operation ledger reached a terminal state; rerun the operation after reviewing logs." '{}'       || log "ERROR: could not mark orphaned database operation failed: id=$opid"
  done < <(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -qAt -F '|' -v ON_ERROR_STOP=1 <<'SQL' 2>/dev/null || true
SELECT id::text, operation_type, phase
  FROM database_operations
 WHERE status='running'
 ORDER BY requested_at;
SQL
  )
}

reconcile_stale_database_operations(){
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -q -v ON_ERROR_STOP=1 >/dev/null <<'SQL' || true
UPDATE database_operations
   SET status='failed', phase='worker-restart-timeout', completed_at=now(),
       error='Database protection worker stopped before this operation completed; inspect backup-agent logs.'
 WHERE status='running' AND started_at < now() - interval '6 hours';
SQL
}


queue_cli_database_operation(){
  local optype="$1" category="${2:-}" filename="${3:-}" metadata="${4:-{\"trigger\":\"cli\"}}" created
  metadata="$(printf '%s' "$metadata" | jq -ce 'if type == "object" then . else error("metadata must be an object") end')" || return 1
  created="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -qAt -v ON_ERROR_STOP=1 \
    -v optype="$optype" -v category="$category" -v filename="$filename" -v metadata="$metadata" <<'SQL' 2>/dev/null || true
INSERT INTO database_operations(operation_type,status,phase,category,backup_filename,requested_by_username,metadata)
VALUES (:'optype','queued','queued',NULLIF(:'category',''),NULLIF(:'filename',''),'cli',:'metadata'::jsonb)
ON CONFLICT DO NOTHING
RETURNING id::text;
SQL
  )"
  created="$(printf '%s\n' "$created" | head -n1 | tr -d '\r')"
  [[ "$created" =~ ^[0-9a-fA-F-]{36}$ ]] && printf '%s\n' "$created"
}

process_database_operation(){
  local row opid optype category filename recovery_public_id recovery_sha256 expected_installation_fingerprint expected_restore_generation
  # Older RC databases may not have the operation table until migrations run.
  row="$(claim_database_operation)"
  [[ -n "$row" ]] || return 1
  IFS='|' read -r opid optype category filename recovery_public_id recovery_sha256 expected_installation_fingerprint expected_restore_generation <<<"$row"
  [[ "$opid" =~ ^[0-9a-fA-F-]{36}$ ]] || return 1
  log "Database protection operation claimed: id=$opid type=$optype backup=$category/$filename"
  case "$optype" in
    backup)
      if ! local_storage_ready_quiet; then
        operation_update "$opid" failed storage-verification-required "Host-local recovery storage is unavailable." || return 1
        runtime_publish || true
        return 0
      fi
      if [[ "$category" == "snapshots" ]]; then
        if ! replication_ready_quiet; then
          operation_update "$opid" failed replication-not-ready "Physical snapshot replication capability is unavailable." || return 1
          runtime_publish || true
          return 0
        fi
        operation_update "$opid" running creating-physical-snapshot || return 1
        if (snapshot_backup); then
          local latest filename_done public_id_done operation_result
          latest="$SPOOL/state/latest-snapshots.json"
          filename_done="$(jq -r '.filename // empty' "$latest" 2>/dev/null || true)"
          public_id_done="$(jq -r '.public_id // empty' "$latest" 2>/dev/null || true)"
          operation_result="$(jq -cn --arg recovery_id "$filename_done" --arg recovery_public_id "$public_id_done" \
            '{recovery_id:$recovery_id,recovery_public_id:$recovery_public_id,source_format:"physical-snapshot"}')"
          operation_update "$opid" verified snapshot-verified "" "$operation_result" || return 1
        else
          operation_update "$opid" failed snapshot-failed "Physical snapshot failed; inspect backup_agent logs." || return 1
        fi
      else
        operation_update "$opid" running creating-logical-backup || return 1
        if (logical_backup daily manual "database-${opid:0:8}" admin-ui); then
          local latest filename_done public_id_done operation_result
          latest="$SPOOL/state/latest-daily.json"
          filename_done="$(jq -r '.filename // empty' "$latest" 2>/dev/null || true)"
          public_id_done="$(jq -r '.public_id // empty' "$latest" 2>/dev/null || true)"
          operation_result="$(jq -cn --arg recovery_id "$filename_done" --arg recovery_public_id "$public_id_done" \
            '{recovery_id:$recovery_id,recovery_public_id:$recovery_public_id,source_format:"logical-dump"}')"
          operation_update "$opid" verified backup-verified "" "$operation_result" || return 1
        else
          operation_update "$opid" failed backup-failed "Backup failed; inspect backup_agent logs." || return 1
        fi
      fi
      ;;
    restore_drill)
      if ! local_storage_ready_quiet; then
        operation_update "$opid" failed backup-storage-unavailable "Backup storage is unavailable; production database was not modified." || return 1
        runtime_publish || true
        return 0
      fi
      if ! (restore_drill_selected "$category" "$filename" "$opid"); then
        operation_update "$opid" failed restore-drill-failed "Restore drill failed; production database was not modified." || return 1
      fi
      ;;
    restore)
      if ! local_storage_ready_quiet; then
        operation_update "$opid" failed protected-restore-unavailable "Production restore requires verified protected pre-restore backup storage." || return 1
        runtime_publish || true
        return 0
      fi
      if ! validate_restore_request_fence "$category" "$filename" "$recovery_public_id" "$recovery_sha256" "$expected_installation_fingerprint" "$expected_restore_generation"; then
        operation_update "$opid" failed restore-fence-rejected "Restore confirmation fence is stale or the selected recovery point changed." || return 1
        return 0
      fi
      local restore_rc=0
      (restore_selected_enterprise "$category" "$filename" "$opid" "$recovery_public_id" "$recovery_sha256" "$expected_installation_fingerprint" "$expected_restore_generation") || restore_rc=$?
      if (( restore_rc != 0 )); then
        if (( restore_rc == 42 )); then
          operation_update "$opid" failed restore-fence-rejected "Restore confirmation fence changed immediately before cutover." || return 1
        else
          operation_update "$opid" failed restore-failed "Restore failed; inspect backup_agent logs and verify the production database before retrying." || return 1
        fi
      fi
      ;;
  esac
  return 0
}

ensure_daily_today(){
  if logical_backup_done_today; then return 0; fi
  if ! auto_window_open; then
    log "Automatic daily backup not due now: window=${AUTO_WINDOW_START}-${AUTO_WINDOW_END} local time"
    return 0
  fi
  log "No successful logical backup exists for $(date '+%Y-%m-%d'); creating the single automatic backup inside ${AUTO_WINDOW_START}-${AUTO_WINDOW_END}"
  logical_backup daily daily scheduled-window automatic
}

snapshot_due(){
  local last failed now
  last="$(cat "$SPOOL/state/last-snapshot-epoch" 2>/dev/null || echo 0)"
  failed="$(cat "$SPOOL/state/last-snapshot-failure-epoch" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  # Any failure newer than the last success is retried on the next scheduler
  # pass/startup rather than being hidden until the normal 2-day interval.
  (( failed > last )) && return 0
  (( now - last >= SNAPSHOT_DAYS * 86400 ))
}

health(){
  pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 || { echo "database unavailable" >&2; return 1; }
  local_storage_ready_quiet || { echo "host-local recovery storage unavailable" >&2; return 1; }
  recovery_bridge_health_quiet || { echo "private recovery bridge unavailable" >&2; return 1; }
  return 0
}
status(){
  echo "Last self-test epoch: $(cat "$SPOOL/state/last-self-test-success-epoch" 2>/dev/null || echo never)"
  echo "Last logical backup date: $(cat "$SPOOL/state/last-daily-date" 2>/dev/null || echo never)"
  echo "Last logical backup type: $(cat "$SPOOL/state/last-daily-type" 2>/dev/null || echo unknown)"
  "$LOCAL_STORE" catalog "$LOCAL_ROOT" \
    | jq -r '.recovery_points[] | [.public_id,.kind,.purpose,.created_at,(.size_bytes|tostring),(.verified|tostring)] | @tsv'
}
scheduler_once(){
  local now verify_last verify_age current_hhmm now_minutes verify_minutes
  sync_local_catalog_if_due || log "WARNING: host-local recovery catalog projection is not synchronized"
  runtime_publish || log "WARNING: database-protection runtime heartbeat update failed"
  reconcile_restore_cutovers || true
  reconcile_stale_database_operations || true
  process_database_operation || true
  # Exactly one automatic logical-backup attempt per local calendar day, and
  # only while the configured 20:00-22:00 maintenance window is open.  The
  # attempt marker is written before pg_dump so a failed attempt, process
  # restart, or bookkeeping error can never create a rapid backup loop.
  # A verified manual backup already taken today suppresses this automatic run.
  if local_storage_ready_quiet && auto_window_open && ! logical_backup_done_today \
      && ! attempted_today "$SPOOL/state/last-auto-daily-attempt-date"; then
    mark_attempt_today "$SPOOL/state/last-auto-daily-attempt-date"
    if (ensure_daily_today); then
      rm -f "$SPOOL/state/last-auto-daily-failure-date"
    else
      date '+%Y-%m-%d' > "$SPOOL/state/last-auto-daily-failure-date"
      log "ERROR: today's single automatic logical-backup attempt failed; no automatic retry will run today (manual backup remains available)"
    fi
  fi

  # Physical snapshots are also limited to one automatic attempt on an
  # eligible date and only inside the same maintenance window.  Failures are
  # surfaced as unhealthy; an operator may retry manually without the daemon
  # hammering PostgreSQL every few minutes.
  if local_storage_ready_quiet && replication_ready_quiet && auto_window_open && snapshot_due \
      && ! attempted_today "$SPOOL/state/last-auto-snapshot-attempt-date"; then
    mark_attempt_today "$SPOOL/state/last-auto-snapshot-attempt-date"
    if ! (snapshot_backup); then
      log "ERROR: today's single automatic physical-snapshot attempt failed; no automatic retry will run today (manual snapshot remains available)"
    fi
  fi

  now="$(date +%s)"
  verify_last="$(cat "$SPOOL/state/last-restore-verify-epoch" 2>/dev/null || echo 0)"
  verify_age=$((now-verify_last))
  current_hhmm="${POSTGRES_BACKUP_TEST_NOW_HHMM:-$(date '+%H:%M')}"
  now_minutes="$(clock_minutes "$current_hhmm")"
  verify_minutes="$(clock_minutes "$VERIFY_TIME")"
  if auto_window_open && { (( verify_last == 0 )) || (( verify_age >= 7 * 86400 )); } \
      && ! attempted_today "$SPOOL/state/last-restore-verify-attempt-date" \
      && (( now_minutes >= verify_minutes )); then
    mark_attempt_today "$SPOOL/state/last-restore-verify-attempt-date"
    if ! (verify_restore_latest); then
      log "ERROR: weekly restore verification failed; no automatic retry will run again today"
    fi
  fi
}

daemon(){
  daemon_preflight
  start_recovery_bridge
  trap 'stop_recovery_bridge' EXIT
  trap 'exit 0' INT TERM
  # Recover any persisted destructive-restore cutover first.  After that, any
  # remaining running operation belongs to the previous backup-agent process
  # and cannot still be executing, so fail it immediately instead of blocking
  # the one-active-operation constraint for up to six hours.
  reconcile_restore_cutovers || true
  reconcile_orphaned_database_operations_on_startup || true
  log "Database protection engine started. Verified host-local recovery bundles are canonical. Automatic logical=ONE attempt/day inside ${AUTO_WINDOW_START}-${AUTO_WINDOW_END}; snapshot=ONE attempt when due; TZ=$TZ"
  while true; do
    kill -0 "$RECOVERY_BRIDGE_PID" >/dev/null 2>&1 || fail "private recovery bridge exited unexpectedly"
    scheduler_once
    sleep 15
  done
}

cmd="${1:-daemon}"; shift || true
case "$cmd" in
  daemon) daemon ;;
  scheduler-once) scheduler_once ;;
  self-test) self_test ;;
  daily) logical_backup daily daily forced-cli automatic ;;
  manual) logical_backup daily manual "${1:-cli}" manual ;;
  ensure-daily) ensure_daily_today ;;
  window-status) if auto_window_open; then echo "open ${AUTO_WINDOW_START}-${AUTO_WINDOW_END}"; else echo "closed ${AUTO_WINDOW_START}-${AUTO_WINDOW_END}"; fi ;;
  snapshot) snapshot_backup ;;
  pre-upgrade) logical_backup pre-upgrade pre-upgrade "${1:-$MREADER_VERSION}" upgrade ;;
  pre-restore) logical_backup pre-restore pre-restore "${1:-manual}" restore ;;
  restore-control) restore_control_snapshot ;;
  initialize-restore-state) initialize_restore_state ;;
  resolve-restore-request) resolve_restore_request "${1:?restore selector required}" ;;
  restore-latest-daily) restore_daily latest ;;
  restore-daily) restore_daily "${1:?backup filename required}" ;;
  resolve-public-id) "$LOCAL_STORE" resolve-public-id "$LOCAL_ROOT" "${1:?public recovery id required}" ;;
  restore-public-id) restore_public_id "${1:?public recovery id required}" "${2:?installation fingerprint required}" "${3:?restore generation required}" "${4:?source sha256 required}" ;;
  restore-drill-public-id) restore_drill_public_id "${1:?public recovery id required}" ;;
  restore-backup) restore_backup_cli "${1:?backup category required}" "${2:?backup filename or latest required}" ;;
  restore-latest-snapshot) restore_backup_cli snapshots latest ;;
  verify-restore-latest) verify_restore_latest ;;
  health) health ;;
  status|list) status ;;
  *) echo "Usage: mreader-backup-agent {daemon|scheduler-once|self-test|daily|manual [label]|ensure-daily|window-status|snapshot|pre-upgrade [label]|pre-restore [label]|restore-control|initialize-restore-state|resolve-restore-request SELECTOR|resolve-public-id PUBLIC_ID|restore-public-id PUBLIC_ID INSTALLATION_FINGERPRINT RESTORE_GENERATION SOURCE_SHA256|restore-drill-public-id PUBLIC_ID|restore-latest-daily|restore-latest-snapshot|verify-restore-latest|health|status}" >&2; exit 2 ;;
esac
