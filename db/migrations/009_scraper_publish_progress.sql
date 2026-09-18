ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_progress JSONB NOT NULL
    DEFAULT '{
      "phase": "not_started",
      "percent": 0,
      "message": "Publish has not started.",
      "total_chapters": 0,
      "chapters_completed": 0,
      "total_source_pages": 0,
      "source_pages_completed": 0,
      "final_pages_written": 0,
      "catalog_verified": false,
      "catalog_verified_chapters": 0,
      "reader_verified_chapters": 0,
      "reader_verified_images": 0,
      "verification_errors": []
    }'::jsonb;

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_attempt INTEGER NOT NULL DEFAULT 0;

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_started_at TIMESTAMPTZ NULL;

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_finished_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_publish_status
    ON scraper_series_drafts(workflow_status, updated_at DESC);
