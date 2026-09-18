-- RC4.85: do not replay a legacy backup request merely because migration 050
-- copied an unproven queued row into the canonical database_operations ledger.
-- Historical migration bytes remain unchanged; this forward repair executes in
-- the same locked migration run before current application workloads resume.

UPDATE database_operations
SET status = 'failed',
    phase = 'migration-recovery-required',
    completed_at = COALESCE(completed_at, now()),
    error = COALESCE(
        error,
        'Legacy queued backup was not proven accepted before queue consolidation; inspect verified recovery artifacts and request a new backup.'
    ),
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'reconciled_by', '053_legacy_operation_reconciliation.sql',
        'replay_allowed', false,
        'recovery_required', true
    )
WHERE metadata->>'migrated_from' = 'backup_requests'
  AND phase = 'migrated-queued'
  AND status = 'queued';

COMMENT ON TABLE database_operations IS
    'Canonical database-protection operation ledger. Legacy queue rows are history only unless acceptance was proven by the canonical operation engine.';
