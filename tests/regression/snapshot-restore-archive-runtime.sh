#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/recovery/staging/mreader-snapshot-test" "$TMP/spool" "$TMP/base"
printf '16\n' > "$TMP/base/PG_VERSION"
tar -czf "$TMP/base.tar.gz" -C "$TMP/base" .
mkdir -p "$TMP/pkg"; cp "$TMP/base.tar.gz" "$TMP/pkg/base.tar.gz"
tar -cf "$TMP/recovery/staging/mreader-snapshot-test/snapshot.tar" -C "$TMP/pkg" .
jq -n '{schema_version:1,recovery_id:"mreader-snapshot-test",type:"physical",purpose:"snapshot",
  scope:"postgres_cluster",database:"manhwa",postgres_major:16,mreader_version:"test",
  created_at:"2026-09-12T00:00:00Z",verification:"verified",files:["snapshot.tar"],
  checksums_file:"checksums.sha256"}' > "$TMP/recovery/staging/mreader-snapshot-test/manifest.json"
(cd "$TMP/recovery/staging/mreader-snapshot-test" && sha256sum snapshot.tar manifest.json > checksums.sha256)
"$ROOT/scripts/backup/local-recovery-store.sh" publish-staged \
  "$TMP/recovery" "$TMP/recovery/staging/mreader-snapshot-test" >/dev/null
cat > "$TMP/bin/postgres" <<'SH'
#!/bin/sh
echo 'postgres (PostgreSQL) 16.10'
SH
cat > "$TMP/bin/pg_isready" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$TMP/bin/su-exec" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$TMP/bin/chown" <<'SH'
#!/bin/sh
exit 0
SH
cat > "$TMP/bin/pg_dump" <<'SH'
#!/bin/sh
printf 'FAKE-CUSTOM-LOGICAL-DUMP\n'
SH
cat > "$TMP/bin/pg_restore" <<'SH'
#!/bin/sh
exit 0
SH
chmod +x "$TMP/bin"/*

export PATH="$TMP/bin:$PATH"
export POSTGRES_BACKUP_LOCAL_ROOT="$TMP/recovery"
export POSTGRES_BACKUP_SPOOL="$TMP/recovery/staging/backup-agent"
export MREADER_LOCAL_RECOVERY_STORE="$ROOT/scripts/backup/local-recovery-store.sh"
export POSTGRES_DB=manhwa POSTGRES_USER=manhwa POSTGRES_PASSWORD=test
# Load function definitions only; do not execute the agent command dispatcher.
source <(sed '/^cmd="${1:-daemon}"/,$d' "$ROOT/scripts/backup/backup-agent.sh")
operation_update(){ return 0; }
apply_current_migrations(){ return 0; }
validate_database_contents(){ printf '3,7,11\n'; }
validate_recovery_database_state(){
  printf '%s\n' '{"counts":"3,7,11","server_encoding":"UTF8","latest_migration":"060_fixture.sql","orphan_rows":0,"bad_page_encoding":0,"unvalidated_foreign_keys":0,"required_grants":true,"extra_databases":[]}'
}

opid=11111111-1111-1111-1111-111111111111
snapshot_restore_drill_selected snapshots mreader-snapshot-test "$opid"
converted="$TMP/recovery/staging/backup-agent/converted.dump"
snapshot_convert_to_logical snapshots mreader-snapshot-test "$opid" "$converted"
grep -q 'FAKE-CUSTOM-LOGICAL-DUMP' "$converted"

# Major-version mismatch must be rejected before any isolated server is accepted.
rm -rf "$TMP/base" "$TMP/pkg"; mkdir -p "$TMP/base" "$TMP/pkg"
printf '15\n' > "$TMP/base/PG_VERSION"
tar -czf "$TMP/pkg/base.tar.gz" -C "$TMP/base" .
tar -cf "$TMP/bad-major.tar" -C "$TMP/pkg" .
if snapshot_stage_start "$TMP/bad-major.tar" "$TMP/stage-major" 55432; then
  echo 'ERROR: PostgreSQL major-version mismatch was accepted' >&2; exit 1
fi

# External tablespaces are intentionally refused because an automated physical
# restore cannot safely recreate arbitrary host tablespace paths.
rm -rf "$TMP/base" "$TMP/pkg"; mkdir -p "$TMP/base" "$TMP/pkg"
printf '16\n' > "$TMP/base/PG_VERSION"
printf '12345 /external/tablespace\n' > "$TMP/base/tablespace_map"
tar -czf "$TMP/pkg/base.tar.gz" -C "$TMP/base" .
tar -cf "$TMP/bad-tablespace.tar" -C "$TMP/pkg" .
if snapshot_stage_start "$TMP/bad-tablespace.tar" "$TMP/stage-ts" 55432; then
  echo 'ERROR: external tablespace snapshot was accepted' >&2; exit 1
fi

# Archive traversal must be refused before extraction.
printf 'x\n' > "$TMP/escape-source"
tar -cf "$TMP/traversal.tar" --transform='s#escape-source#../escape#' -C "$TMP" escape-source
if tar_paths_safe plain "$TMP/traversal.tar"; then
  echo 'ERROR: traversal archive path was accepted' >&2; exit 1
fi

echo 'snapshot restore archive/runtime contract PASS'
