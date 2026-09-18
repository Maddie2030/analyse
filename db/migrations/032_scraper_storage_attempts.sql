-- v1.3.0 RC4.8: durable scraper storage-attempt ledger.
--
-- External/object storage cannot participate in the PostgreSQL transaction.
-- Record every *possible* production path before the PUT so a power loss or an
-- ambiguous COMMIT acknowledgement can be recovered without ever deleting a
-- canonically-published object.

CREATE TABLE IF NOT EXISTS scraper_storage_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_type VARCHAR(32) NOT NULL CHECK (
        operation_type IN ('series_cover','chapter_publish','batch_publish','batch_stage_create','existing_draft_publish','existing_draft_stage_create')
    ),
    draft_id UUID NULL REFERENCES scraper_series_drafts(id) ON DELETE SET NULL,
    draft_chapter_id UUID NULL REFERENCES scraper_series_draft_chapters(id) ON DELETE SET NULL,
    batch_item_id UUID NULL REFERENCES scraper_batch_items(id) ON DELETE SET NULL,
    batch_id UUID NULL REFERENCES scraper_batch_uploads(id) ON DELETE SET NULL,
    local_staging_prefix TEXT NULL,
    object_paths JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(object_paths) = 'array'),
    status VARCHAR(24) NOT NULL DEFAULT 'active' CHECK (
        status IN ('active','committed','cleanup_queued','cleanup_complete')
    ),
    canonical_entity_id UUID NULL,
    cleanup_job_id UUID NULL REFERENCES lifecycle_cleanup_jobs(id) ON DELETE SET NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_active
    ON scraper_storage_attempts(heartbeat_at, created_at, id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_cleanup
    ON scraper_storage_attempts(cleanup_job_id, updated_at)
    WHERE status = 'cleanup_queued';

CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_draft
    ON scraper_storage_attempts(draft_id, created_at DESC)
    WHERE draft_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_batch
    ON scraper_storage_attempts(batch_id, created_at DESC)
    WHERE batch_id IS NOT NULL;

COMMENT ON TABLE scraper_storage_attempts IS
    'Short-lived crash-recovery ledger for scraper writes that cross PostgreSQL and storage transaction boundaries. object_paths are cleared after canonical commit or durable cleanup handoff.';
