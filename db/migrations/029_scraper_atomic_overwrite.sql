-- v1.2.0 RC3: make scraper batch overwrite non-destructive.
-- The existing published chapter remains live while replacement assets are
-- processed. The worker swaps page rows atomically only after conversion succeeds.

ALTER TABLE scraper_batch_items
    ADD COLUMN IF NOT EXISTS overwrite_requested_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_scraper_batch_items_overwrite_pending
    ON scraper_batch_items (updated_at)
    WHERE overwrite_requested_at IS NOT NULL
      AND status IN ('queued','processing','failed_error');

COMMENT ON COLUMN scraper_batch_items.overwrite_requested_at IS
    'Admin-approved replacement intent. existing_chapter_id remains live until the replacement page set commits atomically.';
