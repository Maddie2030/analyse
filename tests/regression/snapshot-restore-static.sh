#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
AGENT=scripts/backup/backup-agent.sh

# Physical snapshots are first-class drill/restore sources, but are never fed
# directly to pg_restore. They must boot in an isolated PostgreSQL cluster and
# be converted to a validated logical archive before the normal cutover engine.
grep -q 'snapshot_stage_start' "$AGENT"
grep -q "listen_addresses=''" "$AGENT"
grep -q 'unix_socket_directories' "$AGENT"
grep -q 'physical snapshot PostgreSQL major version' "$AGENT"
grep -q 'external tablespaces; automated restore is refused' "$AGENT"
grep -q 'snapshot_restore_drill_selected' "$AGENT"
grep -q 'snapshot_convert_to_logical' "$AGENT"
grep -q 'converting-snapshot-to-logical-stage' "$AGENT"
grep -q 'source_format.*physical-snapshot' "$AGENT"
grep -q 'restore_logical_source_enterprise' "$AGENT"
grep -q 'creating-pre-restore-safety-backup' "$AGENT"
grep -q 'atomic-cutover' "$AGENT"

grep -q 'physical snapshot outer tar is unreadable' scripts/backup/backup-agent.sh
grep -q 'Physical snapshot' frontend/src/pages/AdminDatabase.tsx
grep -q 'Restore drill' frontend/src/pages/AdminDatabase.tsx
grep -q 'latest-snapshot' scripts/backup/postgres-restore.sh

echo 'snapshot restore static contract PASS'
