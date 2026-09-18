-- Retire the duplicate Admin Dashboard backup queue. Preserve its history in
-- the canonical database_operations ledger without replaying uncertain work.

INSERT INTO database_operations (
    operation_type,
    status,
    phase,
    requested_by,
    requested_by_username,
    requested_at,
    started_at,
    completed_at,
    error,
    metadata,
    result
)
SELECT
    'backup',
    CASE
        WHEN legacy.status = 'queued' AND NOT EXISTS (
            SELECT 1 FROM database_operations current
             WHERE current.status IN ('queued', 'running')
        ) THEN 'queued'
        WHEN legacy.status = 'queued' THEN 'cancelled'
        WHEN legacy.status = 'running' THEN 'failed'
        ELSE legacy.status
    END,
    CASE
        WHEN legacy.status = 'queued' AND NOT EXISTS (
            SELECT 1 FROM database_operations current
             WHERE current.status IN ('queued', 'running')
        ) THEN 'migrated-queued'
        WHEN legacy.status = 'queued' THEN 'superseded-by-canonical-operation'
        WHEN legacy.status = 'running' THEN 'migration-recovery-required'
        WHEN legacy.status = 'verified' THEN 'legacy-verified-record'
        ELSE 'legacy-failed-record'
    END,
    legacy.requested_by,
    legacy.requested_by_username,
    legacy.requested_at,
    legacy.started_at,
    CASE
        WHEN legacy.status = 'queued' AND NOT EXISTS (
            SELECT 1 FROM database_operations current
             WHERE current.status IN ('queued', 'running')
        ) THEN NULL
        ELSE COALESCE(legacy.completed_at, now())
    END,
    CASE
        WHEN legacy.status = 'running' THEN
            'Legacy backup execution was interrupted during queue consolidation; inspect recovery artifacts before requesting a new backup.'
        WHEN legacy.status = 'queued' AND EXISTS (
            SELECT 1 FROM database_operations current
             WHERE current.status IN ('queued', 'running')
        ) THEN 'Legacy queued request was superseded by an active canonical database operation.'
        ELSE legacy.error
    END,
    jsonb_strip_nulls(jsonb_build_object(
        'migrated_from', 'backup_requests',
        'legacy_request_id', legacy.id,
        'legacy_backup_filename', legacy.backup_filename,
        'legacy_remote_url', legacy.remote_url,
        'legacy_metadata', legacy.metadata
    )),
    CASE
        WHEN legacy.status = 'verified' THEN jsonb_build_object(
            'legacy_record_only', true,
            'restorable_from_local_catalog', false
        )
        ELSE '{}'::jsonb
    END
FROM backup_requests legacy;

DROP TABLE backup_requests;
