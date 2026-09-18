ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_cancel_requested_at TIMESTAMPTZ NULL;

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS publish_worker_heartbeat_at TIMESTAMPTZ NULL;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_status VARCHAR(32) NOT NULL DEFAULT 'pending';

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_error TEXT NULL;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_progress JSONB NOT NULL
    DEFAULT '{
      "phase": "pending",
      "percent": 0,
      "message": "Chapter has not started publishing.",
      "source_pages_total": 0,
      "source_pages_completed": 0,
      "final_pages_written": 0
    }'::jsonb;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_attempt INTEGER NOT NULL DEFAULT 0;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_started_at TIMESTAMPTZ NULL;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS publish_finished_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_publish_recovery
    ON scraper_series_drafts(workflow_status, publish_worker_heartbeat_at)
    WHERE workflow_status IN ('queued_publish', 'publishing');

CREATE INDEX IF NOT EXISTS ix_scraper_series_draft_chapters_publish_status
    ON scraper_series_draft_chapters(draft_id, publish_status);
