-- v1.1.5a durable Media operations + transactional media lifecycle events.
--
-- SeaweedFS remains the blob store and ARQ/Valkey remains execution transport.
-- PostgreSQL is the source of truth for accepted Media work so queue outages do
-- not lose an already-staged upload. media.uploaded and media.processed are
-- written through event_outbox from the same transaction as the operation
-- state they describe; business success never depends on broker availability.

CREATE TABLE IF NOT EXISTS media_operations (
    operation_id UUID PRIMARY KEY,
    job_type VARCHAR(32) NOT NULL
        CHECK (job_type IN ('thumbnail-generation', 'chapter-ingestion')),
    status VARCHAR(16) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'retry', 'completed', 'failed')),

    series_id UUID NULL REFERENCES series(id) ON DELETE SET NULL,
    series_slug VARCHAR(255) NOT NULL,
    event_partition_key VARCHAR(255) NOT NULL,
    chapter_id UUID NULL REFERENCES chapters(id) ON DELETE SET NULL,
    chapter_slug VARCHAR(255) NULL,

    staged_object_path VARCHAR(700) NOT NULL,
    input_filename VARCHAR(255) NULL,
    input_content_type VARCHAR(120) NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    result JSONB NULL
        CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
    output_paths JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(output_paths) = 'array'),

    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT NULL,
    last_queue_error TEXT NULL,

    uploaded_event_id UUID NULL REFERENCES event_outbox(event_id) ON DELETE SET NULL,
    processed_event_id UUID NULL REFERENCES event_outbox(event_id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    failed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_media_operations_recoverable
    ON media_operations(status, updated_at, created_at)
    WHERE status IN ('queued', 'retry', 'processing');

CREATE INDEX IF NOT EXISTS ix_media_operations_series
    ON media_operations(series_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_media_operations_chapter
    ON media_operations(chapter_id, created_at DESC)
    WHERE chapter_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_media_operations_created
    ON media_operations(created_at DESC);

COMMENT ON TABLE media_operations IS
    'Durable Media-service operation ledger. Accepted staged work survives Valkey/ARQ outages; lifecycle events are transactionally paired with operation state.';
COMMENT ON COLUMN media_operations.uploaded_event_id IS
    'event_outbox row for media.uploaded committed with accepted/queued Media state.';
COMMENT ON COLUMN media_operations.processed_event_id IS
    'event_outbox row for the one terminal media.processed event committed with completed/failed Media state.';
