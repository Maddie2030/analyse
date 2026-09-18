#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

[[ -f db/migrations/041_database_protection_operations.sql ]]
[[ -f db/migrations/042_database_protection_runtime.sql ]]
[[ -f db/migrations/049_database_recovery_points.sql ]]
grep -q "CREATE TABLE IF NOT EXISTS database_operations" db/migrations/041_database_protection_operations.sql
grep -q "operation_type IN ('backup','restore_drill','restore')" db/migrations/041_database_protection_operations.sql
grep -q "uq_database_operations_one_active" db/migrations/041_database_protection_operations.sql

grep -q 'APIRouter(prefix="/api/admin/database"' services/scraper_service/app/database_facade.py
! grep -q '/api/scraper/admin/database' services/scraper_service/app/main.py
grep -q 'RESTORE {payload.backup_id}' services/scraper_service/app/database_facade.py
grep -q 'resolve_recovery_point' services/scraper_service/app/database_facade.py
grep -q 'database_recovery_points' services/scraper_service/app/local_recovery_catalog.py

grep -q 'process_database_operation' scripts/backup/backup-agent.sh
grep -q 'creating-pre-restore-safety-backup' scripts/backup/backup-agent.sh
grep -q 'atomic-cutover' scripts/backup/backup-agent.sh
grep -q 'migrating-staged-database' scripts/backup/backup-agent.sh
grep -q 'database-operations-' scripts/backup/backup-agent.sh
grep -q 'run_cli_database_operation restore ' scripts/backup/backup-agent.sh
grep -Fq 'queue_cli_database_operation "$operation_type"' scripts/backup/backup-agent.sh
grep -q 'snapshot_convert_to_logical' scripts/backup/backup-agent.sh
grep -q 'starting-isolated-snapshot-cluster' scripts/backup/backup-agent.sh
grep -q 'restore-latest-snapshot' scripts/backup/backup-agent.sh
! grep -q 'Dropping and recreating database' scripts/backup/backup-agent.sh
grep -q 'COPY db/migrations /migrations' ops/postgres-backup/Dockerfile

[[ -x ops/nas-seaweedfs/start.sh ]]
grep -q 'storage-contract.sh' ops/nas-seaweedfs/start.sh
grep -q 'ops/nas-seaweedfs/start.sh' scripts/storage/nas-up.sh
grep -q 'root_source' ops/nas-seaweedfs/storage-contract.sh
grep -q 'storage-location.json' ops/nas-seaweedfs/storage-contract.sh

grep -q 'path="/admin/database"' frontend/src/App.tsx
grep -q 'Database Protection' frontend/src/pages/AdminDatabase.tsx
grep -q 'local_storage_ready' frontend/src/pages/AdminDatabase.tsx
grep -q 'RESTORE ' frontend/src/pages/AdminDatabase.tsx

# Browser-facing database protection must never expose internal storage topology.
grep -q 'public_recovery_point' services/scraper_service/app/database_facade.py
grep -q 'public_local_storage_status' services/scraper_service/app/database_facade.py
! grep -E -q '/srv/|/backups/mreader/postgres|filer_url|logical_filer_root|expected_physical_root|physical_volume_root|mount_source|POSTGRES_BACKUP_NAS_PATH|NAS_VOLUME_DATA_DIR|storage-location\.json' frontend/src/pages/AdminDatabase.tsx
! grep -q '/api/scraper/admin/database' services/scraper_service/app/database_facade.py
grep -q '/backups/{backup_id}/download' services/scraper_service/app/database_facade.py

# Database protection must not gain host-level escape hatches.
! grep -R -E '/var/run/docker\.sock|kubeconfig|hostPID:[[:space:]]*true|privileged:[[:space:]]*true' \
  services/scraper_service frontend/src/pages/AdminDatabase.tsx deploy/docker-desktop-hybrid/admin-apps.yaml

echo 'database protection static contract PASS'

# Operation result JSON must not use the Bash `${5:-{}}` construction: when an
# argument is present it appends a stray `}` and corrupts jsonb writes.
! grep -Fq 'result="${5:-{}}"' scripts/backup/backup-agent.sh
grep -q 'database operation result must be a JSON object' scripts/backup/backup-agent.sh
grep -q 'database-operation ledger update failed' scripts/backup/backup-agent.sh
grep -q 'reconcile_orphaned_database_operations_on_startup' scripts/backup/backup-agent.sh
