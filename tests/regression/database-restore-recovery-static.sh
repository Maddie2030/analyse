#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
AGENT=scripts/backup/backup-agent.sh

grep -q 'restore-cutover-' "$AGENT"
grep -q 'reconcile_restore_cutovers' "$AGENT"
grep -q 'rollback_database_cutover' "$AGENT"
grep -q 'restore_import_audit' "$AGENT"
grep -q 'restore_mark_superseded_operations' "$AGENT"
grep -q 'audit-import-rollback' "$AGENT"
grep -q 'validation-rollback' "$AGENT"
grep -q 'persistent recovery journal retained' "$AGENT"
grep -q 'completed-cutover recovery could not validate/import audit state' "$AGENT"
grep -q '\$RESTORE_CONTROL_DIR/restore-cutover-' "$AGENT"
grep -q '\$SPOOL/state/restore-cutover-' "$AGENT"
# An audit import failure must not be ignored after a destructive cutover.
! grep -q 'restore_import_audit "$audit_sql" || true' "$AGENT"
# Restore always creates a fresh rollback artifact before atomic cutover.
grep -q 'logical_backup pre-restore pre-restore' "$AGENT"

echo 'database restore recovery static contract PASS'
