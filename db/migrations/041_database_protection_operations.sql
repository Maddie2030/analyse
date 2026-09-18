-- Enterprise database-protection operation queue for admin backup/restore workflows.
CREATE TABLE IF NOT EXISTS database_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_type TEXT NOT NULL CHECK (operation_type IN ('backup','restore_drill','restore')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','verified','completed','failed','cancelled')),
    phase TEXT NOT NULL DEFAULT 'queued',
    category TEXT NULL,
    backup_filename TEXT NULL,
    requested_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    requested_by_username TEXT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_database_operations_requested_at ON database_operations (requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_database_operations_status ON database_operations (status, requested_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_database_operations_one_active
    ON database_operations ((1)) WHERE status IN ('queued','running');
