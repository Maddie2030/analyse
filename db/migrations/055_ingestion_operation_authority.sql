-- RC4.85 prerequisite for the Catalog publication boundary.
-- One canonical ingestion operation header supplies actor/source/fence/cancel authority
-- across manual upload, batch, existing-series scrape and new-series scrape workflows.

CREATE TABLE IF NOT EXISTS ingestion_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_kind VARCHAR(40) NOT NULL,
    requesting_actor_id UUID NOT NULL,
    parent_operation_id UUID NULL REFERENCES ingestion_operations(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    phase VARCHAR(64) NOT NULL DEFAULT 'queued',
    source_revision BIGINT NOT NULL DEFAULT 1,
    revision BIGINT NOT NULL DEFAULT 1,
    lease_generation BIGINT NOT NULL DEFAULT 1,
    selected_count INTEGER NOT NULL DEFAULT 0,
    staged_count INTEGER NOT NULL DEFAULT 0,
    published_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    cancel_requested_at TIMESTAMPTZ NULL,
    acknowledged_at TIMESTAMPTZ NULL,
    error_code VARCHAR(96) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ingestion_operations_status_check CHECK (
        status IN (
            'queued', 'running', 'needs_review', 'cancel_requested', 'cancelled',
            'completed', 'completed_with_errors', 'failed'
        )
    ),
    CONSTRAINT ingestion_operations_source_revision_check CHECK (source_revision >= 1),
    CONSTRAINT ingestion_operations_revision_check CHECK (revision >= 1),
    CONSTRAINT ingestion_operations_lease_generation_check CHECK (lease_generation >= 1),
    CONSTRAINT ingestion_operations_counts_check CHECK (
        selected_count >= 0 AND staged_count >= 0 AND published_count >= 0 AND failed_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_ingestion_operations_status_updated
    ON ingestion_operations(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_operations_actor_updated
    ON ingestion_operations(requesting_actor_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_operations_parent
    ON ingestion_operations(parent_operation_id)
    WHERE parent_operation_id IS NOT NULL;

COMMENT ON TABLE ingestion_operations IS
    'Canonical user-visible ingestion lifecycle header and publication fence authority.';
