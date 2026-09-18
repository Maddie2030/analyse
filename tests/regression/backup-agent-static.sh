#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
grep -q 'REPL_USER=' scripts/backup/backup-agent.sh
grep -q 'PGPASSWORD="$REPL_PASSWORD" pg_basebackup' scripts/backup/backup-agent.sh
grep -q 'local_storage_ready_quiet' scripts/backup/backup-agent.sh
grep -q 'finish_local_logical_bundle' scripts/backup/backup-agent.sh
grep -q 'finish_local_snapshot_bundle' scripts/backup/backup-agent.sh
grep -q 'MREADER_DB_PROTECTION_ROOT' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'configured snapshot role' scripts/backup/backup-agent.sh
grep -q "replication=true" scripts/backup/backup-agent.sh
grep -q "IDENTIFY_SYSTEM" scripts/backup/backup-agent.sh
grep -q 'repair-replication)' scripts/backup/postgres-backup.sh
grep -q 'backup_agent self-test' scripts/hybrid/stateful-up.sh
grep -q 'configure-replication.sh' scripts/hybrid/stateful-up.sh
grep -q 'samenet scram-sha-256' scripts/backup/configure-replication.sh
grep -q 'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS' scripts/backup/configure-replication.sh
grep -q 'diagnose)' scripts/backup/postgres-backup.sh
echo 'backup agent static regression PASSED'
grep -q 'backup_identity' scripts/backup/backup-agent.sh
grep -q 'created_at' scripts/backup/backup-agent.sh
grep -q 'sync_local_catalog_if_due' scripts/backup/backup-agent.sh
grep -q 'copy-artifact' scripts/backup/backup-agent.sh
grep -q 'logical_backup_done_today' scripts/backup/backup-agent.sh
! grep -q 'process_manual_request' scripts/backup/backup-agent.sh
[[ ! -e services/scraper_service/app/backup_requests.py ]]
! grep -q '/api/scraper/admin/backups' services/scraper_service/app/main.py
! grep -q 'requestAdminBackup' frontend/src/api/client.ts
! grep -q 'getAdminBackupStatus' frontend/src/api/client.ts
! grep -q 'Back up database now' frontend/src/pages/AdminDashboard.tsx
[[ -f db/migrations/036_admin_backup_requests.sql ]]
[[ -f db/migrations/050_retire_backup_requests.sql ]]
grep -q 'INSERT INTO database_operations' db/migrations/050_retire_backup_requests.sql
grep -q 'DROP TABLE backup_requests' db/migrations/050_retire_backup_requests.sql
[[ -x tests/regression/backup-daily-policy.sh ]]
grep -q 'POSTGRES_BACKUP_AUTO_WINDOW_START' scripts/backup/backup-agent.sh
grep -q 'POSTGRES_BACKUP_AUTO_WINDOW_END' scripts/backup/backup-agent.sh
grep -q 'auto_window_open' scripts/backup/backup-agent.sh
grep -q 'POSTGRES_BACKUP_AUTO_WINDOW_START' deploy/compose/docker-compose.hybrid-stateful.yml
grep -q 'POSTGRES_BACKUP_AUTO_WINDOW_END' deploy/compose/docker-compose.hybrid-stateful.yml

grep -q 'last-auto-daily-attempt-date' scripts/backup/backup-agent.sh
grep -q 'last-auto-snapshot-attempt-date' scripts/backup/backup-agent.sh
grep -q 'last-restore-verify-attempt-date' scripts/backup/backup-agent.sh
! grep -q 'POSTGRES_BACKUP_AUTO_RETRY_SECONDS' scripts/backup/backup-agent.sh
! grep -q 'POSTGRES_BACKUP_AUTO_RETRY_SECONDS' deploy/compose/docker-compose.hybrid-stateful.yml

grep -q 'scheduler-once)' scripts/backup/backup-agent.sh
grep -q 'RETURNING id::text' scripts/backup/backup-agent.sh
grep -q 'if (ensure_daily_today); then' scripts/backup/backup-agent.sh
grep -q 'if ! (snapshot_backup); then' scripts/backup/backup-agent.sh
[[ -f db/migrations/037_backup_request_restart_recovery.sql ]]
! grep -q 'POSTGRES_BACKUP_VERIFY_DAY' deploy/compose/docker-compose.hybrid-stateful.yml

grep -q 'storage_contract_fail' scripts/backup/backup-agent.sh
grep -q 'exit 42' scripts/backup/backup-agent.sh
grep -q 'refusing to run migrations' scripts/hybrid/stateful-up.sh
grep -q 'up -d --build backup_agent' scripts/hybrid/stateful-up.sh

! grep -q -- '-printf' scripts/backup/backup-agent.sh scripts/backup/local-recovery-store.sh
