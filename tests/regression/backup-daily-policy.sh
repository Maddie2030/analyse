#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/recovery/staging/backup-agent"

make_fake() {
  local name="$1"
  shift
  printf '#!/usr/bin/env bash\n%s\n' "$*" > "$TMP/bin/$name"
  chmod 0755 "$TMP/bin/$name"
}

make_fake pg_isready 'exit 0'
make_fake pg_dump '
if [[ "${FAKE_PG_DUMP_FAIL:-0}" == 1 ]]; then
  printf "attempt\n" >> "${FAKE_DUMP_COUNT:?}"
  exit 1
fi
printf "PGDMP-policy-test"'
make_fake pg_dumpall 'printf "%s\n" "-- PostgreSQL globals" "CREATE ROLE mreader;"'
make_fake pg_restore 'exit 0'
make_fake pg_basebackup 'exit 1'
make_fake psql '
args="$*"
# psql -c/-Atc reads SQL from argv and must not wait on the regression
# runner stdin.  Only consume stdin for heredoc/file-fed invocations.
if [[ ! " $args " =~ [[:space:]]-[A-Za-z]*c([[:space:]]|$) ]]; then
  cat >/dev/null || true
fi
if [[ "$args" == *"server_version_num"* ]]; then printf "160010\n"
elif [[ "$args" == *"rolreplication"* ]]; then printf "no\n"
fi
exit 0'
make_fake curl 'exit 99'

export PATH="$TMP/bin:$PATH"
export POSTGRES_PASSWORD=test
export POSTGRES_DB=mreader
export POSTGRES_USER=mreader
export POSTGRES_BACKUP_LOCAL_ROOT="$TMP/recovery"
export POSTGRES_BACKUP_SPOOL="$TMP/recovery/staging/backup-agent"
export MREADER_LOCAL_RECOVERY_STORE="$ROOT/scripts/backup/local-recovery-store.sh"
export MREADER_SYNC_RECOVERY_CATALOG="$ROOT/scripts/backup/sync-local-recovery-catalog.sh"
export MREADER_VERSION=vtest
export TZ=Asia/Kolkata
export POSTGRES_BACKUP_AUTO_WINDOW_START=20:00
export POSTGRES_BACKUP_AUTO_WINDOW_END=22:00
AGENT="$ROOT/scripts/backup/backup-agent.sh"

# Outside the maintenance window the automatic path is a no-op.
export POSTGRES_BACKUP_TEST_NOW_HHMM=12:00
"$AGENT" ensure-daily >/dev/null
[[ ! -d "$TMP/recovery/dumps/automatic" ]]

# A verified manual bundle satisfies today's logical protection requirement.
export POSTGRES_BACKUP_TEST_NOW_HHMM=20:30
"$AGENT" manual policy >/dev/null
manual_count="$(find "$TMP/recovery/dumps/manual" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$manual_count" == 1 ]]
"$AGENT" ensure-daily >/dev/null
[[ "$(find "$TMP/recovery/dumps/manual" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" == 1 ]]

# If scheduler markers disappear, reconstruct today's state from verified local
# manifests instead of creating a duplicate dump.
rm -f "$POSTGRES_BACKUP_SPOOL/state/last-daily-date" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-success-epoch" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-type"
"$AGENT" ensure-daily >/dev/null
[[ "$(find "$TMP/recovery/dumps/manual" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" == 1 ]]
[[ "$(cat "$POSTGRES_BACKUP_SPOOL/state/last-daily-type")" == local-catalog ]]

# With no recovery point from today, exactly one automatic dump is created.
find "$TMP/recovery/dumps/manual" -mindepth 1 -maxdepth 1 -type d -exec rm -rf -- {} +
rm -f "$POSTGRES_BACKUP_SPOOL/state/last-daily-date" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-success-epoch" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-type"
"$AGENT" ensure-daily >/dev/null
[[ "$(find "$TMP/recovery/dumps/automatic" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" == 1 ]]
"$AGENT" ensure-daily >/dev/null
[[ "$(find "$TMP/recovery/dumps/automatic" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" == 1 ]]

# A failed scheduled attempt is marked before capture and is not retried in a
# tight scheduler loop on the same date.
find "$TMP/recovery/dumps/automatic" -mindepth 1 -maxdepth 1 -type d -exec rm -rf -- {} +
rm -f "$POSTGRES_BACKUP_SPOOL/state/last-daily-date" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-success-epoch" \
      "$POSTGRES_BACKUP_SPOOL/state/last-daily-type" \
      "$POSTGRES_BACKUP_SPOOL/state/last-auto-daily-attempt-date"
date +%s > "$POSTGRES_BACKUP_SPOOL/state/last-snapshot-epoch"
date +%s > "$POSTGRES_BACKUP_SPOOL/state/last-restore-verify-epoch"
export FAKE_PG_DUMP_FAIL=1
export FAKE_DUMP_COUNT="$TMP/dump-attempts"
: > "$FAKE_DUMP_COUNT"
"$AGENT" scheduler-once >/dev/null 2>&1 || true
"$AGENT" scheduler-once >/dev/null 2>&1 || true
[[ "$(wc -l < "$FAKE_DUMP_COUNT" | tr -d ' ')" == 1 ]]
[[ "$(cat "$POSTGRES_BACKUP_SPOOL/state/last-auto-daily-attempt-date")" == "$(date '+%Y-%m-%d')" ]]

echo 'backup local daily/manual policy regression PASSED'
