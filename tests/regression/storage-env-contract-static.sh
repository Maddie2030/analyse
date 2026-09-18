#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

[[ -x scripts/storage/backup-storage-doctor.sh ]]
[[ -x scripts/storage/nas-verify.sh ]]
[[ -x scripts/storage/nas-up.sh ]]
[[ -x ops/nas-seaweedfs/storage-contract.sh ]]

grep -q 'postgres-backup.sh.*check-storage' scripts/storage/backup-storage-doctor.sh
grep -q 'resolve-db-protection-root.sh' scripts/backup/postgres-backup.sh
! grep -Eq 'POSTGRES_BACKUP_NAS_PATH|storage-location.json|curl|kubectl' scripts/storage/backup-storage-doctor.sh

grep -Fq '${NAS_SEAWEEDFS_PORT:-8888}:8888' ops/nas-seaweedfs/docker-compose.yml
grep -q 'actual SeaweedFS /data source' ops/nas-seaweedfs/storage-contract.sh
grep -q 'POSTGRES_BACKUP_NAS_PATH must stay under backups/' ops/nas-seaweedfs/storage-contract.sh

grep -q 'NAS_VOLUME_DATA_DIR=/srv/seaweed/hdd/volumes' ops/nas-seaweedfs/.env.example
grep -q 'POSTGRES_BACKUP_EXPECTED_PHYSICAL_ROOT=/srv/seaweed/hdd/volumes' ops/nas-seaweedfs/.env.example
grep -q 'MUST exactly match POSTGRES_BACKUP_NAS_PATH' ops/nas-seaweedfs/.env.example
! grep -q 'classify_storage_contract' services/scraper_service/app/database_protection.py
! grep -q 'fetch_storage_proof' services/scraper_service/app/database_protection.py

grep -q 'Local recovery storage' frontend/src/pages/AdminDatabase.tsx
grep -q 'backend-only' frontend/src/pages/AdminDatabase.tsx
! grep -E -q '/srv/|/backups/mreader/postgres|POSTGRES_BACKUP|NAS_VOLUME_DATA_DIR|storage-location\.json' frontend/src/pages/AdminDatabase.tsx

grep -q 'publish-running' scripts/storage/nas-verify.sh
grep -q 'check-running' scripts/storage/nas-status.sh
grep -q 'running-container-bind' ops/nas-seaweedfs/storage-contract.sh
grep -q 'No SeaweedFS data was moved or restarted' ops/nas-seaweedfs/storage-contract.sh
[[ -x scripts/env/migrate-known-settings.sh ]]
grep -q 'mreader-rc\*/.env' scripts/hybrid-up.sh
grep -q 'before-rc485-local-recovery' scripts/env/migrate-known-settings.sh
echo 'storage env contract static PASS (source checks only)'
