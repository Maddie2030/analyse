-- Durable admin-triggered PostgreSQL backup requests.
-- The Kubernetes scraper API only records the request. The host-side
-- backup_agent claims and executes it so Docker/Kubernetes boundaries stay clean.

CREATE TABLE IF NOT EXISTS backup_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_type TEXT NOT NULL DEFAULT 'manual' CHECK (backup_type IN ('manual')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','verified','failed')),
    requested_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    requested_by_username TEXT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    backup_filename TEXT NULL,
    remote_url TEXT NULL,
    error TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_backup_requests_requested_at
    ON backup_requests (requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_requests_status
    ON backup_requests (status, requested_at);

-- Only one manually requested logical backup should consume resources at once.
-- Concurrent admin clicks coalesce onto the same active request.
CREATE UNIQUE INDEX IF NOT EXISTS uq_backup_requests_one_active
    ON backup_requests ((1))
    WHERE status IN ('queued','running');
