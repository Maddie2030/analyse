#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

# Browser/API readiness is a capability contract, not one global storage bit.
[[ -f db/migrations/042_database_protection_runtime.sql ]]
grep -q 'CREATE TABLE IF NOT EXISTS database_protection_runtime' db/migrations/042_database_protection_runtime.sql
grep -q 'backup_agent_runtime' services/scraper_service/app/database_protection.py
grep -q '_require_database_capability' services/scraper_service/app/database_facade.py
grep -q '"restore_drill"' services/scraper_service/app/database_protection.py
grep -q 'runtime: {' frontend/src/api/client.ts
grep -q 'Recovery engine' frontend/src/pages/AdminDatabase.tsx
grep -q 'canRestoreDrill' frontend/src/pages/AdminDatabase.tsx
grep -q '!canRestoreDrill' frontend/src/pages/AdminDatabase.tsx
grep -q '!canLogicalBackup' frontend/src/pages/AdminDatabase.tsx
grep -q '!canPhysicalSnapshot' frontend/src/pages/AdminDatabase.tsx
grep -q '!canRestore' frontend/src/pages/AdminDatabase.tsx
! grep -q 'disabled={[^}]*!storage?.healthy' frontend/src/pages/AdminDatabase.tsx

# The operation engine reports host-local storage and replication independently.
grep -q 'daemon_preflight' scripts/backup/backup-agent.sh
grep -q 'runtime_publish' scripts/backup/backup-agent.sh
grep -q 'local_storage_ready_quiet' scripts/backup/backup-agent.sh
grep -q "'local_storage_ready'" scripts/backup/backup-agent.sh
grep -q 'restore_drill.*true' scripts/backup/backup-agent.sh
grep -q 'up -d --build backup_agent' scripts/hybrid/stateful-up.sh
grep -q 'host-local recovery root' scripts/hybrid/stateful-up.sh
! grep -q 'backup_agent pre-upgrade' scripts/hybrid/stateful-up.sh
! grep -q 'nas-integrate-remote.sh' scripts/hybrid/stateful-up.sh
! grep -q 'NAS_SEAWEEDFS' scripts/backup/backup-agent.sh
! grep -q 'POSTGRES_BACKUP_NAS_PATH' scripts/backup/backup-agent.sh
! grep -q 'remote_file_url' scripts/backup/backup-agent.sh

# Browser-facing code must continue hiding internal topology.
! grep -E -q '/srv/|/backups/mreader/postgres|storage-location\.json|mount_source|physical_volume_root|NAS_SSH_USER' frontend/src/pages/AdminDatabase.tsx

echo 'database protection runtime integration static contract PASS'
