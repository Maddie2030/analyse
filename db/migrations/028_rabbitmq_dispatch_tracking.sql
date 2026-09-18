-- v1.2.0: explicit RabbitMQ dispatch tracking.
-- PostgreSQL remains authoritative for accepted work. These timestamps record
-- that RabbitMQ publisher confirms succeeded so periodic recovery only
-- republishes genuinely deferred/stale work instead of duplicating a backlog.

ALTER TABLE media_operations
    ADD COLUMN IF NOT EXISTS queue_dispatched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_heartbeat_at TIMESTAMPTZ;

ALTER TABLE scraper_batch_items
    ADD COLUMN IF NOT EXISTS queue_dispatched_at TIMESTAMPTZ;

ALTER TABLE scraper_batch_items
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_heartbeat_at TIMESTAMPTZ;

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS queue_dispatched_at TIMESTAMPTZ;

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS queue_dispatched_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_media_operations_dispatch_pending
    ON media_operations (created_at)
    WHERE status IN ('queued', 'retry') AND queue_dispatched_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_batch_items_dispatch_pending
    ON scraper_batch_items (updated_at)
    WHERE status = 'queued' AND queue_dispatched_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_dispatch_pending
    ON scraper_series_drafts (updated_at)
    WHERE workflow_status IN ('queued_discovery', 'queued_publish')
      AND queue_dispatched_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_chapters_dispatch_pending
    ON scraper_series_draft_chapters (updated_at)
    WHERE (stage_status = 'queued' OR publish_status = 'pending')
      AND queue_dispatched_at IS NULL;
