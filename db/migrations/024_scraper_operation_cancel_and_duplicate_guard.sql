-- Operation-wide scraper cancellation and exact-series duplicate guard metadata.
ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS operation_cancel_requested_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS operation_cancel_requested_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS duplicate_series_id UUID NULL REFERENCES series(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS duplicate_series_slug VARCHAR(255) NULL,
    ADD COLUMN IF NOT EXISTS duplicate_series_title VARCHAR(255) NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_cancel_requested
    ON scraper_series_drafts(operation_cancel_requested_at)
    WHERE operation_cancel_requested_at IS NOT NULL;
